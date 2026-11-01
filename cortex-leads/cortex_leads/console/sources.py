"""Nguồn dữ liệu & MCP (WP29): the outside sources a sandbox that does not talk to customers may read. Adding one pins what the
person reviewed (config hash, and for MCP the tool definition); a source that stops matching its pin locks itself and says why.
"Xoá" is a lock: the row, its pin and its call history stay, and it comes back with one click."""
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from cortex_leads.config import get_settings
from cortex_leads.connectors import mcp_remote
from cortex_leads.connectors.http_readonly import ConnectorError, pin_of, validate_source
from cortex_leads.console.auth import Session, need
from cortex_leads.console.sandboxes import label_of
from cortex_leads.console.trail import audit
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

router = APIRouter()
KIND_LABEL = {"http_readonly": "Nguồn HTTP chỉ-đọc", "mcp": "MCP chỉ-đọc"}
ALERT_TEXT = {"TOOL_CHANGED": "Định nghĩa của công cụ đã thay đổi sau khi bạn duyệt", "PIN_MISMATCH": "Cấu hình không còn khớp mã ghim",
              "NOT_READ_ONLY": "Máy chủ đánh dấu công cụ này là có ghi hoặc phá huỷ"}


def _host(c: m.ToolConnector) -> str:
    return urlsplit(c.source.get("url", "")).hostname or ""


def _state(c: m.ToolConnector) -> str:
    return "deleted" if c.deleted_at else "alert" if c.alert else "locked" if c.status != "active" else "active"


async def _stats(s: Any, tid: UUID, name: str, now: datetime) -> dict[str, Any]:
    base = (m.ActionLog.tool == "external_lookup", m.ActionLog.args_masked["connector"].astext == name, m.ActionLog.at >= now - timedelta(days=7))
    calls = (await s.execute(select(func.count()).select_from(m.ActionLog).where(*base))).scalar_one()
    errors = (await s.execute(select(func.count()).select_from(m.ActionLog).where(*base, m.ActionLog.status != "ok"))).scalar_one()
    last = (await s.execute(select(func.max(m.ActionLog.at)).where(m.ActionLog.tool == "external_lookup", m.ActionLog.args_masked["connector"].astext == name))).scalar()
    return {"calls_7d": calls, "errors_7d": errors, "last_at": wire(last) if last else None}


def _row(c: m.ToolConnector, sb: m.Sandbox | None) -> dict[str, Any]:
    exposed = [e.get("remote") for e in c.source.get("expose", [])] if c.kind == "mcp" else []
    return {"id": str(c.id), "name": c.name, "kind": c.kind, "kind_label": KIND_LABEL.get(c.kind, c.kind), "host": _host(c), "description": c.description,
            "state": _state(c), "alert": ALERT_TEXT.get(c.alert or "", c.alert), "alert_code": c.alert, "pinned_tools": exposed,
            "sandbox": {"id": str(sb.id), "title": label_of(sb)} if sb else None, "deleted_at": wire(c.deleted_at) if c.deleted_at else None,
            "deleted_by": c.deleted_by}


async def _attachable(s: Any) -> list[m.Sandbox]:
    """Outside data is untrusted, so only a sandbox that never talks to customers may hold it."""
    out = []
    for sb in (await s.execute(select(m.Sandbox).order_by(m.Sandbox.created_at))).scalars():
        has_channel = (await s.execute(select(func.count()).select_from(m.Connector).where(m.Connector.sandbox_id == sb.id))).scalar_one()
        if sb.purpose != "customer_care" and not has_channel:
            out.append(sb)
    return out


@router.get("/sources")
async def list_sources(sess: Session = need("sources.manage")) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        sbs = {x.id: x for x in (await s.execute(select(m.Sandbox))).scalars()}
        rows = (await s.execute(select(m.ToolConnector).order_by(m.ToolConnector.created_at))).scalars().all()
        items = [{**_row(c, sbs.get(c.sandbox_id)), **(await _stats(s, c.tenant_id, c.name, now))} for c in rows]
        can = await _attachable(s)
    live = [i for i in items if i["state"] != "deleted"]
    return {"items": items, "counts": {"all": len(live), "deleted": len(items) - len(live)},
            "attachable": [{"id": str(x.id), "title": label_of(x)} for x in can],
            "blocked": [{"id": str(x.id), "title": label_of(x)} for x in sbs.values() if x not in can]}


@router.get("/sources/{source_id}")
async def source_detail(source_id: UUID, sess: Session = need("sources.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        c = await s.get(m.ToolConnector, source_id)
        if c is None:
            raise HTTPException(404, "source not found")
        sb = await s.get(m.Sandbox, c.sandbox_id)
        stats = await _stats(s, c.tenant_id, c.name, datetime.now(UTC))
        can = await _attachable(s)
    return {**_row(c, sb), **stats, "url": c.source.get("url"), "allow_hosts": c.source.get("allow_hosts", []), "auth_saved": c.secret_enc is not None,
            "auth_header": c.source.get("auth_header"), "pin": c.pin_sha256[:4] + "…" + c.pin_sha256[-4:], "pin_ok": c.pin_sha256 == pin_of(c.kind, c.source),
            "attachable": [{"id": str(x.id), "title": label_of(x)} for x in can]}


class Describe(BaseModel):
    url: str = Field(max_length=300)
    host: str = Field(max_length=120)
    auth_header: str | None = Field(default=None, max_length=60)
    secret: str | None = Field(default=None, max_length=500)


def _source(b: Describe) -> dict[str, Any]:
    return {"url": b.url.strip(), "allow_hosts": [b.host.strip()], **({"auth_header": b.auth_header} if b.auth_header else {})}


@router.post("/sources/mcp/describe")
async def describe_mcp(body: Describe, sess: Session = need("sources.manage")) -> dict[str, Any]:
    """What the server offers, to choose exactly one tool and pin it. The key is used for this call only."""
    try:
        tools = await mcp_remote.describe({**_source(body), "expose": [], "tool_pin": ""}, body.secret.encode() if body.secret else None)
    except ConnectorError as e:
        raise HTTPException(422, {"code": "SOURCE_UNREACHABLE", "message": f"Không đọc được máy chủ này ({e.code})."}) from None
    return {"tools": [{"name": t["name"], "description": t.get("description", ""), "read_only": mcp_remote.read_only(t)} for t in tools]}


class NewSource(Describe):
    kind: Literal["http_readonly", "mcp"]
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")
    description: str = Field(default="", max_length=200)
    sandbox_id: UUID
    tool: str | None = Field(default=None, max_length=80)
    arg: str = Field(default="query", max_length=40)


@router.post("/sources", status_code=201)
async def create_source(body: NewSource, sess: Session = need("sources.manage")) -> dict[str, Any]:
    source = _source(body)
    secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(body.secret.encode()) if body.secret else None
    try:
        if body.kind == "http_readonly":
            validate_source(source)
        else:
            if not body.tool:
                raise ValueError("choose the one tool to pin")
            tools = await mcp_remote.describe({**source, "expose": [], "tool_pin": ""}, body.secret.encode() if body.secret else None)
            chosen = next((t for t in tools if t["name"] == body.tool), None)
            if chosen is None:
                raise ValueError("the server has no such tool")
            if not mcp_remote.read_only(chosen):
                raise HTTPException(422, {"code": "NOT_READ_ONLY", "message": "Máy chủ đánh dấu công cụ này là có ghi hoặc phá huỷ: không gắn được."})
            source |= {"expose": [{"remote": body.tool, "arg": body.arg}], "tool_pin": mcp_remote.tool_pin([chosen])}
            mcp_remote.validate_source(source)
    except ValueError as e:
        raise HTTPException(422, {"errors": [str(e)]}) from None
    except ConnectorError as e:
        raise HTTPException(422, {"code": "SOURCE_UNREACHABLE", "message": f"Không đọc được máy chủ này ({e.code})."}) from None
    async with tenant_session(sess.caller.tenant_id) as s:
        if body.sandbox_id not in {x.id for x in await _attachable(s)}:
            raise HTTPException(409, {"code": "SANDBOX_TALKS_TO_CUSTOMERS", "message": "Sandbox này có nói chuyện với khách nên không gắn nguồn ngoài được."})
        c = m.ToolConnector(tenant_id=sess.caller.tenant_id, sandbox_id=body.sandbox_id, name=body.name, kind=body.kind, source=source,
                            description=body.description, secret_enc=secret, pin_sha256=pin_of(body.kind, source))
        s.add(c)
        try:
            await s.flush()
        except IntegrityError:
            raise HTTPException(409, {"code": "NAME_TAKEN", "message": "Đã có nguồn tên này trong sandbox đó."}) from None
        await audit(sess, s, "config", "source.created", f"Thêm nguồn dữ liệu «{body.name}»", obj=("source", str(c.id), body.name),
                    metadata={"kind": body.kind, "host": body.host, "sandbox_id": str(body.sandbox_id), "tool": body.tool, "has_key": secret is not None})
        return {"id": str(c.id)}


async def _change(source_id: UUID, sess: Session, verb: str, *, summary: str) -> m.ToolConnector:
    async with tenant_session(sess.caller.tenant_id) as s:
        c = await s.get(m.ToolConnector, source_id)
        if c is None:
            raise HTTPException(404, "source not found")
        if verb == "lock":
            if c.deleted_at:
                raise HTTPException(409, {"code": "DELETED"})
            c.deleted_at, c.deleted_by, c.status = datetime.now(UTC), sess.actor, "disabled"
        elif verb == "unlock":
            if not c.deleted_at:
                raise HTTPException(409, {"code": "NOT_DELETED"})
            c.deleted_at, c.deleted_by = None, None
            c.status = "disabled" if c.alert else "active"  # a source that tripped its pin stays stopped until reviewed
        await audit(sess, s, "config", f"source.{verb}", f"{summary} «{c.name}»", obj=("source", str(c.id), c.name), metadata={"state_after": _state(c)})
        return c


@router.post("/sources/{source_id}/review")
async def review_source(source_id: UUID, sess: Session = need("sources.manage")) -> dict[str, str]:
    """After the server changed the tool: read the definition again and, if it is still read-only, pin it as the new approved one."""
    async with tenant_session(sess.caller.tenant_id) as s:
        c = await s.get(m.ToolConnector, source_id)
        if c is None or c.deleted_at or c.kind != "mcp":
            raise HTTPException(404, "source not found")
        secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(c.secret_enc) if c.secret_enc else None
        try:
            tools = await mcp_remote.describe(c.source, secret)
        except ConnectorError as e:
            raise HTTPException(422, {"code": "SOURCE_UNREACHABLE", "message": f"Không đọc được máy chủ này ({e.code})."}) from None
        chosen = next((t for t in tools if t["name"] == c.source["expose"][0]["remote"]), None)
        if chosen is None or not mcp_remote.read_only(chosen):
            raise HTTPException(422, {"code": "NOT_READ_ONLY", "message": "Công cụ không còn, hoặc không còn là chỉ-đọc: không duyệt lại được."})
        before = c.source["tool_pin"]
        c.source = {**c.source, "tool_pin": mcp_remote.tool_pin([chosen])}
        c.pin_sha256, c.alert, c.status = pin_of(c.kind, c.source), None, "active"
        await audit(sess, s, "config", "source.reviewed", f"Duyệt lại định nghĩa công cụ của nguồn «{c.name}»", obj=("source", str(c.id), c.name),
                    metadata={"tool_pin_before": before[:12], "tool_pin_after": c.source["tool_pin"][:12]})
    return {"state": "active"}


@router.post("/sources/{source_id}/{verb}")
async def source_verb(source_id: UUID, verb: Literal["lock", "unlock"], sess: Session = need("sources.manage")) -> dict[str, str]:
    c = await _change(source_id, sess, verb, summary="Khoá nguồn" if verb == "lock" else "Khôi phục nguồn")
    return {"state": _state(c)}


class Move(BaseModel):
    sandbox_id: UUID


@router.put("/sources/{source_id}/sandbox")
async def move_source(source_id: UUID, body: Move, sess: Session = need("sources.manage")) -> dict[str, str]:
    async with tenant_session(sess.caller.tenant_id) as s:
        c = await s.get(m.ToolConnector, source_id)
        if c is None:
            raise HTTPException(404, "source not found")
        if body.sandbox_id not in {x.id for x in await _attachable(s)}:
            raise HTTPException(409, {"code": "SANDBOX_TALKS_TO_CUSTOMERS", "message": "Sandbox này có nói chuyện với khách nên không gắn nguồn ngoài được."})
        before, c.sandbox_id = c.sandbox_id, body.sandbox_id
        await audit(sess, s, "config", "source.moved", f"Chuyển nguồn «{c.name}» sang sandbox khác", obj=("source", str(c.id), c.name),
                    metadata={"from": str(before), "to": str(body.sandbox_id)})
    return {"sandbox_id": str(body.sandbox_id)}
