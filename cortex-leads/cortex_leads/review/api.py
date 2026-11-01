"""Staff review queue (DESIGN §5.7). The only place a human sees draft text; every read is audited.
'sent' records that the human sent it themselves; 'approved' ("Duyệt & gửi") queues the message
through the send_message tool -> outbox -> bridge, the single send path (A9)."""
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from cortex_leads.channels.policy import window_state
from cortex_leads.core.context import RunContext, Scope, StaffPrincipal
from cortex_leads.core.envelope import BlockedCode, ToolResult
from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.ingest.api import get_now
from cortex_leads.review.auth import Caller, require
from cortex_leads.skills.registry import TURN_EVENT
from cortex_leads.tools.registry import default_registry

router = APIRouter()
STAFF = require("staff", "owner")
CLOCK = Depends(get_now)  # overridable in tests; staff_ui passes `now` explicitly
DraftStatus = Literal["proposed", "approved", "sent", "edited", "self", "skipped", "expired", "blocked",
                      "failed"]


class ActionBody(BaseModel):
    action: Literal["approved", "sent", "edited", "self", "skipped"]
    edited_text: str | None = None


def _actor(c: Caller) -> str:
    return f"staff:{c.staff_ref}" if c.staff_ref else f"{c.role}:-"


@router.get("/drafts")
async def list_drafts(caller: Caller = STAFF, status: DraftStatus = "proposed",
                      limit: int = 100) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(caller.tenant_id) as s:
        rows = (await s.execute(
            select(m.Draft, m.Conversation)
            .join(m.Conversation, m.Conversation.id == m.Draft.conversation_id)
            .where(m.Draft.status == status).order_by(m.Draft.created_at).limit(min(limit, 200)))).all()
        s.add(m.ActionLog(tenant_id=caller.tenant_id, action_id=uuid7(), actor=_actor(caller),
                          tool="review.list_drafts", args_masked={"status": status},
                          status="ok", evidence={"count": len(rows)}))
    return {"drafts": [{
        "id": str(d.id), "conversation_id": str(c.id), "status": d.status, "route": d.route, "text": d.text,
        "claims": d.claims, "reason_code": d.reason_code, "created_at": wire(d.created_at),
        # Evaluated now, not when drafted: basis "human_agent" means a person must type it (R6).
        "window": {**(w := window_state(c.channel_kind, c.last_customer_at, now)),
                   "expires_at": wire(w["expires_at"])},
    } for d, c in rows]}


@router.post("/drafts/{draft_id}/action")
async def act_on_draft(draft_id: str, body: ActionBody, caller: Caller = STAFF,
                       now: datetime = CLOCK) -> dict[str, Any]:
    if body.action == "edited" and not (body.edited_text or "").strip():
        raise HTTPException(422, "edited_text is required for 'edited'")
    try:
        did = UUID(draft_id)
    except ValueError:
        raise HTTPException(404, "draft not found") from None
    refused: ToolResult | None = None
    async with tenant_session(caller.tenant_id) as s:
        d = (await s.execute(select(m.Draft).where(m.Draft.id == did).with_for_update())).scalar_one_or_none()
        if d is None:
            raise HTTPException(404, "draft not found")
        sends = body.action in ("sent", "edited", "approved")
        if d.status == "expired" and sends:
            raise HTTPException(409, {"code": "STALE"})
        if d.status != "proposed":
            raise HTTPException(409, {"code": "NOT_PROPOSED", "status": d.status})
        newer = (await s.execute(select(m.Message.id).where(
            m.Message.conversation_id == d.conversation_id, m.Message.sender_role == "customer",
            m.Message.occurred_at > d.created_at).limit(1))).first()
        if sends and newer:  # re-checked at click time: the customer spoke after the draft
            raise HTTPException(409, {"code": "STALE"})
        # An unchanged text in the box is not an edit.
        edited = body.edited_text if (body.edited_text or "").strip() not in ("", d.text.strip()) else None
        if body.action == "approved":
            sandbox = await s.get(m.Sandbox, d.sandbox_id)
            profile, _, ver = sandbox.profile_ref.partition("@")
            ctx = RunContext(
                run_id=d.run_id or uuid7(), tenant_id=caller.tenant_id, sandbox_id=d.sandbox_id,
                profile=profile, profile_version=int(ver or 1),
                principal=StaffPrincipal(caller.staff_ref or caller.role),
                scope=Scope(conversation_id=d.conversation_id))
            res = await default_registry(clock=lambda: now).execute(
                ctx, s, "send_message", {"draft_id": str(d.id), "text": edited},
                allowlist=["send_message"], effect_ceiling="customer")
            if res.status != "ok":  # draft stays proposed; the refusal is logged and committed below
                refused = res
                s.add(m.DecisionLog(
                    tenant_id=caller.tenant_id, run_id=d.run_id, conversation_id=d.conversation_id,
                    decision="send_refused_at_approval", at=now, reason_code=_code(res),
                    detail={"actor_kind": "staff", "codes": [f"{v.code.value}:{v.detail}" for v in res.violations]}))
        if refused is None:
            d.status, d.decided_at, d.staff_ref = (
                "approved" if body.action == "approved" else body.action), now, caller.staff_ref
            s.add(m.StaffAction(tenant_id=caller.tenant_id, draft_id=d.id, action=body.action,
                                edited_text={"edited": body.edited_text, "approved": edited}.get(body.action),
                                staff_ref=caller.staff_ref or caller.role))
            run = await s.get(m.TriggerRun, d.run_id) if d.run_id else None
            if body.action in ("sent", "edited") and not (run and run.event_type == TURN_EVENT):
                # R36: staff sent it by hand; "approved" counts at the worker. Turn replies are no touch (N5).
                (await s.get(m.Conversation, d.conversation_id)).touches += 1
            if run:
                run.staff_outcome = {"approved": "edited" if edited else "sent"}.get(body.action, body.action)
    if refused is not None:
        raise HTTPException(409, {"code": _code(refused)})
    return {"id": str(did), "status": body.action}


def _code(res: ToolResult) -> str:
    """Stable code for the UI: NOT_ALLOWED is refined by its detail (OUTBOUND_OFF, CONNECTOR_TRUST...)."""
    v = res.violations[0] if res.violations else None
    if v is None:
        return res.status.upper()
    return v.detail.upper() if v.code == BlockedCode.NOT_ALLOWED and v.detail else v.code.value
