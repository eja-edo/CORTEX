"""Cài đặt (WP39-41): what a business owner used to need the command line for. The profile (name, time zone, opening hours, the name the
AI introduces itself by), where staff pushes go, which channels feed the business, and one page that gathers what decides how far the
AI may go. Owner only (`settings.manage`). Tenant and actor come from the session (A3); a secret is shown once, in the answer that
makes it, and never again (not in the log, not in the audit trail, not in a later read)."""
import re
import secrets
from datetime import UTC, datetime, time
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from cortex_leads.audit.service import diff
from cortex_leads.channels.policy import CHANNEL_POLICIES
from cortex_leads.config import get_settings
from cortex_leads.connectors.egress import EgressError, ensure_callable
from cortex_leads.console.auth import Session, need
from cortex_leads.console.sandboxes import label_of
from cortex_leads.console.trail import audit
from cortex_leads.core.identity import ai_disclosure, clean_ai_name
from cortex_leads.core.ids import new_connector_id
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.notify.probe import send_test

router = APIRouter(prefix="/settings")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
TELEGRAM_CHAT = re.compile(r"^-?\d{3,20}$")


def _refuse(code: str, message: str, status: int = 422) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


# --- WP39 business profile ---------------------------------------------------------------------------
class Hours(BaseModel):
    start: str
    end: str


class Business(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    timezone: str = Field(min_length=1, max_length=64)
    hours: Hours
    ai_name: str | None = Field(default=None, max_length=60)


def _check_business(b: Business) -> tuple[str, str, Hours, str | None]:
    name = " ".join(b.name.split())
    if len(name) < 2:
        raise _refuse("BAD_NAME", "Tên doanh nghiệp cần ít nhất 2 ký tự.")
    try:
        ZoneInfo(b.timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise _refuse("BAD_TIMEZONE", "Múi giờ không hợp lệ (ví dụ Asia/Ho_Chi_Minh).") from None
    if not HHMM.match(b.hours.start) or not HHMM.match(b.hours.end):
        raise _refuse("BAD_HOURS", "Giờ làm việc phải có dạng HH:MM, ví dụ 08:00.")
    if time.fromisoformat(b.hours.end) <= time.fromisoformat(b.hours.start):
        raise _refuse("BAD_HOURS", "Giờ đóng cửa phải sau giờ mở cửa.")
    try:
        ai_name = clean_ai_name(b.ai_name)
    except ValueError:
        raise _refuse("BAD_AI_NAME", "Tên trợ lý chỉ gồm chữ, số, khoảng trắng và . ' - (tối đa 40 ký tự).") from None
    return name, b.timezone, b.hours, ai_name


async def _business(s: Any, tenant_id: UUID) -> dict[str, Any]:
    t = await s.get(m.Tenant, tenant_id)
    hours = {(sb.business_hours.get("start", "08:00"), sb.business_hours.get("end", "21:00")) for sb in (await s.execute(select(m.Sandbox))).scalars()}
    start, end = min(hours) if hours else ("08:00", "21:00")
    return {"name": t.name, "timezone": t.timezone, "hours": {"start": start, "end": end}, "hours_differ": len(hours) > 1,
            "ai_name": t.ai_name, "disclosure": ai_disclosure(t.name, t.ai_name)}


@router.get("/business")
async def get_business(sess: Session = need("settings.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        return await _business(s, sess.caller.tenant_id)


@router.put("/business")
async def put_business(body: Business, sess: Session = need("settings.manage")) -> dict[str, Any]:
    """The hours go to every sandbox of the business: `send_message` reads them from the sandbox it runs in, and one business has one
    set of opening hours."""
    name, tz, hours, ai_name = _check_business(body)
    async with tenant_session(sess.caller.tenant_id) as s:
        before = await _business(s, sess.caller.tenant_id)
        t = await s.get(m.Tenant, sess.caller.tenant_id)
        t.name, t.timezone, t.ai_name = name, tz, ai_name
        for sb in (await s.execute(select(m.Sandbox))).scalars():
            sb.business_hours = {**sb.business_hours, "start": hours.start, "end": hours.end}
        after = await _business(s, sess.caller.tenant_id)
        changes = diff({k: before[k] for k in ("name", "timezone", "hours", "ai_name")}, {k: after[k] for k in ("name", "timezone", "hours", "ai_name")})
        if changes:
            await audit(sess, s, "config", "settings.updated", "Sửa hồ sơ doanh nghiệp: " + ", ".join(c["field"] for c in changes),
                        obj=("tenant", str(t.id), name), changes=changes)
        return after


# --- WP40 where pushes go ----------------------------------------------------------------------------
def mask_address(kind: str, address: str) -> str:
    """What the screen may show of a destination. A webhook address is a credential in itself (R120); a chat id is not secret but
    needs no more than its tail to be recognised."""
    if kind == "mezon":
        host = re.sub(r"^https?://", "", address).split("/")[0]
        return f"{host}/…"
    return "…" + address[-4:] if len(address) > 4 else address


def _target(t: m.NotifyTarget, sandboxes: dict[UUID, str]) -> dict[str, Any]:
    return {"id": str(t.id), "kind": t.kind, "address": mask_address(t.kind, t.address), "label": t.label, "sandbox_id": str(t.sandbox_id) if t.sandbox_id else None,
            "sandbox": sandboxes.get(t.sandbox_id) if t.sandbox_id else None, "created_at": wire(t.created_at)}


@router.get("/notify-targets")
async def list_targets(sess: Session = need("settings.manage")) -> dict[str, Any]:
    cfg = get_settings()
    async with tenant_session(sess.caller.tenant_id) as s:
        sandboxes = {sb.id: label_of(sb) for sb in (await s.execute(select(m.Sandbox))).scalars()}
        rows = (await s.execute(select(m.NotifyTarget).where(m.NotifyTarget.active.is_(True)).order_by(m.NotifyTarget.created_at))).scalars().all()
    return {"items": [_target(t, sandboxes) for t in rows], "telegram_ready": bool(cfg.TELEGRAM_BOT_TOKEN),
            "sandboxes": [{"id": str(i), "title": n} for i, n in sandboxes.items()]}


class NewTarget(BaseModel):
    kind: Literal["telegram", "mezon"]
    address: str = Field(min_length=3, max_length=600)
    label: str | None = Field(default=None, max_length=60)
    sandbox_id: UUID | None = None


@router.post("/notify-targets", status_code=201)
async def add_target(body: NewTarget, sess: Session = need("settings.manage")) -> dict[str, Any]:
    address = body.address.strip()
    if body.kind == "telegram":
        if not TELEGRAM_CHAT.match(address):
            raise _refuse("BAD_ADDRESS", "Mã nhóm Telegram là một dãy số, ví dụ -1001234567890.")
    else:
        try:
            await ensure_callable(address)
        except EgressError:
            raise _refuse("BAD_ADDRESS", "Địa chỉ webhook không dùng được: cần https, đúng máy chủ được cho phép, không chứa tài khoản.") from None
    async with tenant_session(sess.caller.tenant_id) as s:
        sandboxes = {sb.id: label_of(sb) for sb in (await s.execute(select(m.Sandbox))).scalars()}
        if body.sandbox_id is not None and body.sandbox_id not in sandboxes:
            raise HTTPException(404, "sandbox not found")
        t = m.NotifyTarget(tenant_id=sess.caller.tenant_id, kind=body.kind, address=address, label=(body.label or "").strip() or None, sandbox_id=body.sandbox_id)
        s.add(t)
        await s.flush()
        await audit(sess, s, "config", "notify_target.added", f"Thêm nơi nhận thông báo ({'Telegram' if body.kind == 'telegram' else 'Mezon'})",
                    obj=("notify_target", str(t.id), t.label), metadata={"kind": body.kind, "sandbox": bool(body.sandbox_id)})  # never the address
        return _target(t, sandboxes)


@router.delete("/notify-targets/{target_id}")
async def remove_target(target_id: UUID, sess: Session = need("settings.manage")) -> dict[str, str]:
    """The role has no DELETE on this table; a target that is switched off receives nothing, and the audit trail still points at it."""
    async with tenant_session(sess.caller.tenant_id) as s:
        t = await s.get(m.NotifyTarget, target_id)
        if t is None or not t.active:
            raise HTTPException(404, "target not found")
        t.active = False
        await audit(sess, s, "config", "notify_target.removed", "Bỏ một nơi nhận thông báo", obj=("notify_target", str(t.id), t.label), metadata={"kind": t.kind})
    return {"status": "ok"}


@router.post("/notify-targets/{target_id}/test")
async def test_target(target_id: UUID, sess: Session = need("settings.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        t = await s.get(m.NotifyTarget, target_id)
        if t is None or not t.active:
            raise HTTPException(404, "target not found")
        kind, address, label = t.kind, t.address, t.label
    token = get_settings().TELEGRAM_BOT_TOKEN
    if kind == "telegram" and not token:
        raise _refuse("NOT_CONFIGURED", "Máy chủ chưa có mã bot Telegram (CL_TELEGRAM_BOT_TOKEN), nên chưa gửi được.", 409)
    ok = await send_test(kind, address, token)
    async with tenant_session(sess.caller.tenant_id) as s:
        await audit(sess, s, "config", "notify_target.tested", "Gửi thử thông báo", obj=("notify_target", str(target_id), label),
                    result="success" if ok else "failed", metadata={"kind": kind})
    return {"ok": ok}


# --- WP41 channels -----------------------------------------------------------------------------------
def _ingest_url() -> str | None:
    base = get_settings().PUBLIC_BASE_URL
    return f"{base.rstrip('/')}/ingest/v1/events" if base else None


@router.get("/channels")
async def list_channels(sess: Session = need("settings.manage")) -> dict[str, Any]:
    """`connector` has no row level security (a bridge's signed batch finds its business by connector id), so the business is named here."""
    tid = sess.caller.tenant_id
    async with tenant_session(tid) as s:
        sandboxes = {sb.id: label_of(sb) for sb in (await s.execute(select(m.Sandbox).where(m.Sandbox.purpose == "customer_care"))).scalars()}
        rows = (await s.execute(select(m.Connector).where(m.Connector.tenant_id == tid).order_by(m.Connector.created_at))).scalars().all()
        last = dict((await s.execute(select(m.IngestEvent.connector_id, func.max(m.IngestEvent.received_at)).group_by(m.IngestEvent.connector_id))).all())
    return {"items": [{"id": c.id, "kind": c.channel_kind, "status": c.status, "sandbox": sandboxes.get(c.sandbox_id), "sandbox_id": str(c.sandbox_id),
                       "sends": bool((c.outbound or {}).get("enabled")), "created_at": wire(c.created_at),
                       "last_event_at": wire(last[c.id]) if last.get(c.id) else None} for c in rows],
            "kinds": sorted(CHANNEL_POLICIES), "sandboxes": [{"id": str(i), "title": n} for i, n in sandboxes.items()], "ingest_url": _ingest_url()}


class NewChannel(BaseModel):
    kind: str
    sandbox_id: UUID


@router.post("/channels", status_code=201)
async def add_channel(body: NewChannel, sess: Session = need("settings.manage")) -> dict[str, Any]:
    """The only moment the secret exists in clear: it goes to the bridge's configuration, and what is kept is the encrypted copy."""
    if body.kind not in CHANNEL_POLICIES:
        raise _refuse("UNKNOWN_CHANNEL", "Loại kênh này chưa được hỗ trợ.")
    tid = sess.caller.tenant_id
    async with tenant_session(tid) as s:
        sb = await s.get(m.Sandbox, body.sandbox_id)
        if sb is None or sb.purpose != "customer_care":
            raise HTTPException(404, "sandbox not found")
    cid, secret = new_connector_id(get_settings().CELL), secrets.token_urlsafe(32)
    async with system_session() as s:  # `connector` is outside row level security; the business is set from the session, not the body (A3)
        s.add(m.Connector(id=cid, tenant_id=tid, sandbox_id=body.sandbox_id, channel_kind=body.kind, trust="custom",
                          secret_enc=Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(secret.encode())))
    async with tenant_session(tid) as s:
        await audit(sess, s, "config", "channel.added", f"Thêm kênh {body.kind}", obj=("connector", cid, body.kind), metadata={"kind": body.kind})
    return {"id": cid, "kind": body.kind, "secret": secret, "ingest_url": _ingest_url()}


@router.delete("/channels/{connector_id}")
async def remove_channel(connector_id: str, sess: Session = need("settings.manage")) -> dict[str, str]:
    """Switches the channel off: a bridge's batches are refused from then on. Messages already received keep pointing at it."""
    tid = sess.caller.tenant_id
    async with system_session() as s:
        c = await s.get(m.Connector, connector_id)
        if c is None or c.tenant_id != tid or c.status == "disabled":
            raise HTTPException(404, "channel not found")
        c.status = "disabled"
        kind = c.channel_kind
    async with tenant_session(tid) as s:
        await audit(sess, s, "config", "channel.removed", f"Tắt kênh {kind}", obj=("connector", connector_id, kind), metadata={"kind": kind})
    return {"status": "ok"}


# --- the AI tab --------------------------------------------------------------------------------------
@router.get("/ai")
async def ai_overview(sess: Session = need("settings.manage")) -> dict[str, Any]:
    """Read only. Changing the send mode or pausing uses the endpoints that already do it; this gathers what decides how far the AI
    may go so the owner sees it in one place."""
    async with tenant_session(sess.caller.tenant_id) as s:
        t = await s.get(m.Tenant, sess.caller.tenant_id)
        out = []
        for sb in (await s.execute(select(m.Sandbox).where(m.Sandbox.purpose == "customer_care").order_by(m.Sandbox.created_at))).scalars():
            skills = (await s.execute(select(m.SkillVersion).where(m.SkillVersion.sandbox_id == sb.id, m.SkillVersion.status.in_(("live", "shadow")),
                                                                    m.SkillVersion.deleted_at.is_(None)))).scalars().all()
            never: set[str] = set()
            handoff: set[str] = set()
            for k in skills:
                never |= {str(x) for x in k.manifest.get("never_say", [])}
                handoff |= {str(x) for x in k.manifest.get("must_handoff", [])}
            out.append({"id": str(sb.id), "title": label_of(sb), "send_mode": sb.send_mode, "status": sb.status,
                        "skills": [{"name": k.name, "status": k.status, "sends": k.manifest.get("output_kind") == "send_to_customer"} for k in skills],
                        "never_say": sorted(never), "must_handoff": sorted(handoff)})
    return {"sandboxes": out, "disclosure": ai_disclosure(t.name, t.ai_name), "generated_at": wire(datetime.now(UTC))}
