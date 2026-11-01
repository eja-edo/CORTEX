"""Sandbox (WP27): see them, make a new one from a template, pause or resume one. A new customer-care sandbox comes up ready
(its shipped skills live, `manual` send mode, default budget) because an empty sandbox that silently does nothing is worse
than none; it has no channel until the owner connects one."""
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.console.auth import Session, need
from cortex_leads.console.flow import feeds_and_pushes, flow_line
from cortex_leads.console.killswitch import set_paused
from cortex_leads.console.trail import audit
from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import day_start, tenant_tz
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.sandbox.bringup import DEFAULT_BUDGET
from cortex_leads.sandbox.bringup import create_sandbox as make_sandbox
from cortex_leads.sandbox.kinds import KINDS, kind_of

router = APIRouter()
TEMPLATES = [{"id": k.purpose, "label": k.label, "available": k.available, "profile": k.profile, "description": k.description,
              **({"reason": k.reason} if not k.available else {})} for k in KINDS.values() if k.listed]
PURPOSE_LABELS = {k.purpose: k.label for k in KINDS.values()}
PURPOSE_LINES = {k.purpose: k.about for k in KINDS.values() if k.about}


def label_of(sb: m.Sandbox) -> str:
    """What the owner sees: their own title if they gave one, else the template's name (never the internal key)."""
    return sb.title or PURPOSE_LABELS.get(sb.purpose, sb.name)


async def _usage(s: AsyncSession, sb: m.Sandbox, now: datetime) -> dict[str, int]:
    day = day_start(now, await tenant_tz(s, sb.tenant_id))
    base = (m.TriggerRun.sandbox_id == sb.id, m.TriggerRun.started_at >= day)
    runs = (await s.execute(select(func.count()).select_from(m.TriggerRun).where(*base))).scalar_one()
    tokens = (await s.execute(select(func.coalesce(func.sum(m.TriggerRun.tokens_in + m.TriggerRun.tokens_out), 0)).where(*base))).scalar_one()
    return {"runs": runs, "tokens": int(tokens)}


@router.get("/sandboxes")
async def list_sandboxes(sess: Session = need("sandboxes.read")) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        out = []
        for sb in (await s.execute(select(m.Sandbox).order_by(m.Sandbox.created_at))).scalars():
            by_status = dict((await s.execute(select(m.SkillVersion.status, func.count()).where(m.SkillVersion.sandbox_id == sb.id)
                                              .group_by(m.SkillVersion.status))).all())
            conns = (await s.execute(select(m.Connector).where(m.Connector.sandbox_id == sb.id))).scalars().all()
            feeds, pushes = await feeds_and_pushes(s, sb)
            kind = kind_of(sb.purpose)
            out.append({"id": str(sb.id), "title": label_of(sb), "purpose": sb.purpose, "about": PURPOSE_LINES.get(sb.purpose, ""), "status": sb.status, "send_mode": sb.send_mode,
                        "customer_facing": bool(kind and kind.customer_facing), "flow": flow_line(feeds, pushes),
                        "budget": {k: sb.budget.get(k) for k in DEFAULT_BUDGET}, "usage": await _usage(s, sb, now),
                        "skills": {"live": by_status.get("live", 0), "shadow": by_status.get("shadow", 0)},
                        "channels": [{"kind": c.channel_kind, "status": c.status, "sends": bool((c.outbound or {}).get("enabled"))} for c in conns]})
    return {"items": out, "templates": TEMPLATES}


class NewSandbox(BaseModel):
    template: str
    title: str = Field(min_length=3, max_length=60)


def _slug(existing: set[str], purpose: str) -> str:
    n = 1
    while (name := purpose if n == 1 else f"{purpose}-{n}") in existing:
        n += 1
    return name


@router.post("/sandboxes", status_code=201)
async def create_sandbox(body: NewSandbox, sess: Session = need("sandboxes.manage")) -> dict[str, Any]:
    tpl = next((t for t in TEMPLATES if t["id"] == body.template), None)
    if tpl is None:
        raise HTTPException(422, {"code": "UNKNOWN_TEMPLATE", "message": "Không có mẫu sandbox này"})
    if not tpl["available"]:
        raise HTTPException(422, {"code": "NOT_AVAILABLE", "message": tpl["reason"]})
    tid = sess.caller.tenant_id
    async with tenant_session(tid) as s:
        name = _slug({n for (n,) in (await s.execute(select(m.Sandbox.name))).all()}, body.template)
        sb = await make_sandbox(s, tid, KINDS[body.template], name=name, title=body.title.strip(), sandbox_id=uuid7())
        await audit(sess, s, "config", "sandbox.created", f"Tạo sandbox «{name}»", obj=("sandbox", str(sb.id), name),
                    metadata={"template": body.template})
    return {"id": str(sb.id), "name": name}


class SendMode(BaseModel):
    mode: Literal["auto", "manual"]


@router.post("/sandboxes/{sandbox_id}/send-mode")
async def set_send_mode(sandbox_id: UUID, body: SendMode, sess: Session = need("sandboxes.manage")) -> dict[str, Any]:
    """`manual`: every message to a customer waits for a person. `auto`: only the skills that opted in (they answer a customer who
    just wrote) may send on their own, and only through the same floor as a person's click: window, opt-out, channel, quiet hours.
    Every other skill stays a draft whatever this says. The owner's call, and a line in the activity log."""
    async with tenant_session(sess.caller.tenant_id) as s:
        sb = await s.get(m.Sandbox, sandbox_id)
        if sb is None or sb.purpose != "customer_care":
            raise HTTPException(404, "sandbox not found")
        before, sb.send_mode = sb.send_mode, body.mode
        if before != body.mode:
            await audit(sess, s, "control", "send_mode.changed", f"Chế độ gửi của «{label_of(sb)}»: {'tự gửi' if body.mode == 'auto' else 'duyệt tay'}",
                        obj=("sandbox", str(sb.id), label_of(sb)), metadata={"from": before, "to": body.mode})
    return {"send_mode": body.mode, "changed": before != body.mode}


@router.post("/sandboxes/{sandbox_id}/{verb}")
async def sandbox_verb(sandbox_id: UUID, verb: Literal["pause", "resume"], sess: Session = need("sandboxes.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        if await s.get(m.Sandbox, sandbox_id) is None:
            raise HTTPException(404, "sandbox not found")
        await set_paused(s, sess.caller.tenant_id, verb == "pause", by=sess.actor, role=sess.caller.role, now=datetime.now(UTC), sandbox_id=sandbox_id)
        status = (await s.get(m.Sandbox, sandbox_id)).status
    return {"status": status}


