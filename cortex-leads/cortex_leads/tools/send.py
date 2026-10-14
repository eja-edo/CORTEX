"""send_message: the ONLY way to reach a customer (DESIGN A9): tool -> outbox -> worker -> bridge.
The tool checks the floor the core never switches off (kill switch, opt-out, window, disclosure,
idempotency) and queues a row; it never calls a channel. It is not offered to the model: the runner
(`ai:*`, mode auto only) or the staff approve button (`staff:*`) call it with a draft id."""
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.channels.policy import window_state
from cortex_leads.core.context import CustomerPrincipal, RunContext, StaffPrincipal
from cortex_leads.core.envelope import BlockedCode, ErrorCode, ErrorInfo, ToolResult, Violation
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.guard.validator import validate_draft
from cortex_leads.privacy.redact import _fold
from cortex_leads.skills.manifest import SkillManifest
from cortex_leads.skills.registry import TURN_EVENT
from cortex_leads.tools.registry import ToolArgs, ToolRegistry, ToolSpec

Clock = Callable[[], datetime]


class SendArgs(ToolArgs):
    draft_id: UUID
    text: str | None = Field(default=None, min_length=1, max_length=2000)  # staff edit only


def effective_mode(manifest: SkillManifest | None, sandbox: m.Sandbox) -> str:
    """Skill's send_policy wins over sandbox.send_mode. `auto` also needs the skill to have opted in
    (output_kind send_to_customer + the tool): a sandbox-wide auto never upgrades an ordinary skill."""
    mode = manifest.send_policy.mode if manifest and manifest.send_policy else sandbox.send_mode
    opted_in = manifest is not None and manifest.output_kind == "send_to_customer" \
        and "send_message" in manifest.requires_tools
    return "auto" if mode == "auto" and opted_in else "manual"


def next_open(hours: dict[str, Any], tz: str, now: datetime) -> datetime:
    """`now` if inside sandbox.business_hours (tenant timezone), else the next opening time."""
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    start = time.fromisoformat(hours.get("start", "08:00"))
    if start <= local.time() < time.fromisoformat(hours.get("end", "21:00")):
        return now
    day = local.date() if local.time() < start else local.date() + timedelta(days=1)
    return datetime.combine(day, start, tzinfo=zone).astimezone(UTC)


def _v(code: BlockedCode, detail: str) -> Violation:
    return Violation(code=code, detail=detail)


def _make_send(clock: Clock):
    async def send_message(ctx: RunContext, session: AsyncSession, a: SendArgs) -> ToolResult:
        now = clock()
        ai = isinstance(ctx.principal, CustomerPrincipal)
        if ctx.scope.conversation_id is None or not (ai or isinstance(ctx.principal, StaffPrincipal)):
            return ToolResult(status="blocked", violations=[_v(BlockedCode.NOT_ALLOWED, "principal")])
        draft = (await session.execute(select(m.Draft).where(
            m.Draft.id == a.draft_id, m.Draft.conversation_id == ctx.scope.conversation_id,
            m.Draft.sandbox_id == ctx.sandbox_id).with_for_update())).scalar_one_or_none()
        if draft is None:
            return ToolResult(status="not_found", error=ErrorInfo(code=ErrorCode.NOT_FOUND))
        action_id = uuid5(draft.id, "send")  # one draft, one message, whoever asks and however often
        if prior := (await session.execute(
                select(m.Outbox).where(m.Outbox.action_id == action_id))).scalar_one_or_none():
            return ToolResult(status="ok", replayed=True, action_id=action_id,
                              data={"outbox_id": str(prior.id), "status": prior.status})
        if draft.status != "proposed":
            return ToolResult(status="blocked", violations=[_v(BlockedCode.NOT_ALLOWED, "draft_not_proposed")])
        if draft.route != "channel":  # R39: for a person to phone/Zalo; no path to the outbox, ever
            return ToolResult(status="blocked", violations=[_v(BlockedCode.NOT_ALLOWED, "offchannel_draft")])
        conv = await session.get(m.Conversation, draft.conversation_id)
        contact = await session.get(m.Contact, conv.contact_id)
        sandbox = await session.get(m.Sandbox, conv.sandbox_id)
        connector = await session.get(m.Connector, conv.connector_id)
        tenant = await session.get(m.Tenant, ctx.tenant_id)
        run = await session.get(m.TriggerRun, draft.run_id) if draft.run_id else None
        sv = (await session.execute(select(m.SkillVersion).where(
            m.SkillVersion.sandbox_id == sandbox.id, m.SkillVersion.name == run.skill_name,
            m.SkillVersion.version == run.skill_version))).scalar_one_or_none() if run else None
        manifest = SkillManifest(**sv.manifest) if sv else None
        policy = manifest.send_policy if manifest and manifest.send_policy else None

        if ai and draft.needs_human:  # WP16 handoff: a person's call, whatever the mode
            return ToolResult(status="blocked", violations=[_v(BlockedCode.NOT_ALLOWED, "handoff_draft")])
        if ai and effective_mode(manifest, sandbox) != "auto":  # A9: manual never reaches the outbox
            return ToolResult(status="blocked", violations=[_v(BlockedCode.NOT_ALLOWED, "manual_mode")])
        if ai and a.text:
            return ToolResult(status="blocked", violations=[_v(BlockedCode.NOT_ALLOWED, "ai_cannot_edit")])
        vs: list[Violation] = []
        # --- floor: the same for ai:* and staff:* ---
        if tenant.status != "active" or sandbox.status == "paused":
            vs.append(_v(BlockedCode.PAUSED, "sandbox_or_tenant"))
        if connector.status != "active":
            vs.append(_v(BlockedCode.PAUSED, "connector"))
        out = connector.outbound or {}
        if not out.get("enabled") or not out.get("url"):
            vs.append(_v(BlockedCode.NOT_ALLOWED, "outbound_off"))
        if connector.trust not in ("official", "partner") or (
                connector.trust == "partner" and connector.contract_test_passed_at is None):
            vs.append(_v(BlockedCode.NOT_ALLOWED, "connector_trust"))
        if contact.opted_out or conv.state == "opted_out":
            vs.append(Violation(code=BlockedCode.OPTED_OUT))
        window = window_state(conv.channel_kind, conv.last_customer_at, now)
        if not window["open"]:
            vs.append(_v(BlockedCode.WINDOW_CLOSED, "closed"))
        elif ai and window["basis"] != "free":  # N3: human_agent is for a person typing by hand
            vs.append(_v(BlockedCode.WINDOW_CLOSED, "human_only"))
        not_before = now
        turn = run is not None and run.event_type == TURN_EVENT  # the customer just wrote: no waiting for opening hours
        if ai:  # --- ai-only: validator again (N2), must_handoff, per-contact cap, business hours ---
            rows = list((await session.execute(select(m.CatalogItem).where(
                m.CatalogItem.tenant_id == ctx.tenant_id, or_(
                    m.CatalogItem.code.in_([str(c.get("source_id")) for c in draft.claims]),
                    m.CatalogItem.id.in_([u for c in draft.claims if (u := _uuid(c.get("source_id")))]))
            ))).scalars())
            vs += validate_draft(  # touches were checked by draft_followup, so neutralised here
                draft.text, draft.claims, rows, never_say=manifest.never_say, touches=0, max_touches=1,
                opted_out=False, has_new_info=True, now=now)
            last = (await session.execute(select(m.Message.text).where(
                m.Message.conversation_id == conv.id, m.Message.sender_role == "customer")
                .order_by(m.Message.occurred_at.desc()).limit(1))).scalar_one_or_none()
            if last and draft.text != manifest.handoff_reply and any(  # the holding line IS the handoff
                    _fold(p) in _fold(last) for p in manifest.must_handoff if p.strip()):
                vs.append(_v(BlockedCode.NOT_ALLOWED, "must_handoff"))
            cap = (policy.auto_when.get("max_per_contact_per_day") if policy else None)
            if cap is not None and (await session.execute(
                    select(func.count()).select_from(m.Outbox)
                    .join(m.Conversation, m.Conversation.id == m.Outbox.conversation_id)
                    .where(m.Conversation.contact_id == contact.id, m.Outbox.actor.like("ai:%"),
                           m.Outbox.status.in_(("queued", "sending", "sent")),
                           m.Outbox.created_at >= now - timedelta(days=1)))).scalar_one() >= cap:
                vs.append(_v(BlockedCode.TOUCH_LIMIT, "per_contact_per_day"))
            not_before = now if turn else next_open(sandbox.business_hours, tenant.timezone, now)
            if not_before > now and window["expires_at"] and window["expires_at"] <= not_before:
                vs.append(_v(BlockedCode.WINDOW_CLOSED, "closes_before_opening"))
        if vs:
            return ToolResult(status="blocked", violations=vs)

        row = m.Outbox(
            id=uuid7(), tenant_id=ctx.tenant_id, action_id=action_id, conversation_id=conv.id,
            connector_id=connector.id, draft_id=draft.id, actor=ctx.actor,
            text=a.text if (a.text and not ai) else draft.text,
            disclosure=f"Trợ lý AI của {tenant.name}" if ai else None,  # Luật AI 134/2025
            window={"open": window["open"], "basis": window["basis"], "expires_at": (
                window["expires_at"].isoformat() if window["expires_at"] else None)},
            source={"skill": f"{run.skill_name}@{run.skill_version}" if run else None,
                    "run_id": str(draft.run_id or ctx.run_id), "turn": turn},
            status="queued", not_before=not_before, created_at=now)
        session.add(row)
        draft.status, draft.decided_at = "approved", now
        await session.flush()
        return ToolResult(status="ok", action_id=action_id, data={
            "outbox_id": str(row.id), "status": "queued", "not_before": not_before.isoformat()})

    return send_message


def _uuid(v: Any) -> UUID | None:
    try:
        return UUID(str(v))
    except ValueError:
        return None


def register_send(reg: ToolRegistry, clock: Clock | None = None) -> None:
    reg.register(ToolSpec(
        "send_message", "Xếp tin của một nháp vào hàng gửi cho khách. Chỉ lõi và nút duyệt của nhân viên gọi.",
        SendArgs, "customer", "v0", _make_send(clock or (lambda: datetime.now(UTC)))))
