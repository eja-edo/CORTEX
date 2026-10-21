"""Customer run (DESIGN §5.5): one job -> one stateless run -> a draft for staff or nothing.
In `auto` mode the only way out to a customer is the `send_message` tool -> outbox (A9)."""
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.channels.policy import window_state
from cortex_leads.core.context import CustomerPrincipal, RunContext, Scope
from cortex_leads.core.envelope import BlockedCode, ToolResult
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import list_active_tenants, system_session, tenant_session
from cortex_leads.domain.pack import load_pack
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.llm.shape import parse_json_object
from cortex_leads.llm.types import LLMError, ShapeError
from cortex_leads.memory.service import has_pending_outcome, local_today
from cortex_leads.notify import service as notify
from cortex_leads.outbound.annotate import annotate
from cortex_leads.runner.context_builder import build_messages, recent_messages
from cortex_leads.sandbox.policy import check_budget
from cortex_leads.skills.manifest import SkillManifest
from cortex_leads.skills.profile import load_profile
from cortex_leads.skills.registry import TURN_EVENT, LoadedSkill
from cortex_leads.tools.booking import cancel_booking
from cortex_leads.tools.registry import ToolRegistry, default_registry
from cortex_leads.tools.send import effective_mode
from cortex_leads.triggers.select import select_jobs

log = logging.getLogger(__name__)
TURN_WAIT = timedelta(minutes=2)  # DESIGN §5.7: a `wait` moves the mark by this, at most once
TURN_MAX_TOUCHES = 10  # turn replies are not follow-ups (N5): the follow-up cap of 3 is not theirs to spend


def _tool_message(call_id: str, result: ToolResult) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id,
            "content": result.model_dump_json(exclude_none=True, exclude={"action_id", "replayed"})}


async def _loop(session: AsyncSession, gateway: LLMGateway, registry: ToolRegistry, ctx: RunContext,
                run: m.TriggerRun, messages: list[dict[str, Any]], read_allow: list[str],
                max_calls: int, timeout_s: int) -> str | None:
    """Read-only tool loop (effect_ceiling=read). Returns the model's final text."""
    schemas = registry.openai_schemas(read_allow)
    for i in range(max_calls + 1):
        offer = bool(schemas) and i < max_calls  # the last round must answer, not call
        res = await gateway.complete(ctx, messages, tools=schemas if offer else None,
                                     timeout_s=timeout_s)
        run.tokens_in += res.tokens_in
        run.tokens_out += res.tokens_out
        run.model = res.model or run.model
        if not (offer and res.tool_calls):
            return res.content
        messages.append({"role": "assistant", "content": res.content, "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in res.tool_calls]})
        for c in res.tool_calls:
            if c.parse_error:
                out = ToolResult(status="error", note=f"Tham số không hợp lệ: {c.parse_error}")
            else:
                out = await registry.execute(ctx, session, c.name, c.arguments,
                                             allowlist=read_allow, effect_ceiling="read")
            messages.append(_tool_message(c.id, out))
    return None


def _log(session: AsyncSession, run: m.TriggerRun, conv: m.Conversation, decision: str,
         now: datetime, **detail: Any) -> None:
    session.add(m.DecisionLog(tenant_id=run.tenant_id, run_id=run.id, conversation_id=conv.id,
                              decision=decision, reason_code=run.reason_code, detail=detail, at=now))


async def run_job(session: AsyncSession, job: m.FollowupJob, gateway: LLMGateway,
                  registry: ToolRegistry, now: datetime) -> m.TriggerRun:
    """`session` must be tenant_session(job.tenant_id)."""
    sandbox = await session.get(m.Sandbox, job.sandbox_id)
    conv = await session.get(m.Conversation, job.conversation_id)
    contact = await session.get(m.Contact, conv.contact_id)
    sv = (await session.execute(select(m.SkillVersion).where(
        m.SkillVersion.sandbox_id == sandbox.id, m.SkillVersion.name == job.skill_name,
        m.SkillVersion.version == job.skill_version))).scalar_one()
    skill = LoadedSkill(sv.name, sv.version, SkillManifest(**sv.manifest), sv.body, sv.checksum)
    shadow = sv.status == "shadow"  # a trial: everything but the model's words stays out of the real world (DESIGN §5.8)
    profile = load_profile(sandbox.profile_ref)
    # The run row exists before anything else: draft.run_id needs it (WP2).
    run = m.TriggerRun(
        id=uuid7(), tenant_id=job.tenant_id, sandbox_id=sandbox.id, job_id=job.id,
        skill_name=skill.name, skill_version=skill.version, profile=profile.id,
        profile_version=profile.version, event_type=job.event_type, status="ok",
        blocked_codes=[], tokens_in=0, tokens_out=0, started_at=now)
    session.add(run)
    await session.flush()
    await session.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                          {"k": str(conv.id)})  # one run per conversation at a time

    def finish(status: str, job_status: str = "done", *codes: str, decision: str = "run_none",
               **detail: Any) -> m.TriggerRun:
        run.status, run.blocked_codes, run.finished_at = status, list(codes), now
        job.status, job.updated_at = job_status, now
        _log(session, run, conv, decision, now, skill=skill.name, **detail)
        return run

    # Hard gates first, 0 token (A2). A missing budget number denies (check_budget).
    for kind in ("runs", "tokens"):
        v = await check_budget(session, sandbox, kind, now)
        if v is not None:
            paused = v.code == BlockedCode.PAUSED
            return finish("paused" if paused else "budget_denied", "skipped", v.code.value,
                          decision="run_paused" if paused else "run_budget_denied", kind=kind)
    if conv.state != "open" or contact.opted_out:
        return finish("blocked", "skipped", BlockedCode.OPTED_OUT.value, decision="run_blocked",
                      state=conv.state)
    # N5 double stop before the LLM: an unconfirmed outcome, or a promise still in the future.
    if await has_pending_outcome(session, conv.id):
        return finish("blocked", "skipped", "PENDING_OUTCOME", decision="run_blocked",
                      reason="pending_outcome")
    if job.event_type == "conversation.silent" and conv.promised_date \
            and conv.promised_date > await local_today(session, conv.tenant_id, now):
        return finish("none", decision="run_none", reason="promised_future")
    turn = job.event_type == TURN_EVENT
    turn_msg, staff_at, handoff = conv.last_customer_msg_id, conv.last_staff_at, False  # the turn this run answers
    window = window_state(conv.channel_kind, conv.last_customer_at, now)
    # R9/R39: the validator does not check the window. Closed -> the draft goes the offchannel route
    # (staff phone/Zalo), which has no path to the outbox (N3, A9).
    route = "channel" if window["open"] else "offchannel"

    reason_codes = set(load_pack(sandbox).reason_codes)  # DESIGN A6
    ctx = RunContext(run_id=run.id, tenant_id=job.tenant_id, sandbox_id=sandbox.id,
                     profile=profile.id, profile_version=profile.version,
                     principal=CustomerPrincipal(contact_id=conv.contact_id),
                     scope=Scope(conversation_id=conv.id, job_id=job.id),
                     trigger_event_id=job.dedupe_key)
    allowed = [n for n in profile.tool_allowlist if n in skill.manifest.requires_tools]
    read_allow = [s.name for s in registry.specs_for(allowed) if s.effect == "read"]
    async def flag_human(draft_id: str, **extra: Any) -> None:  # a person's card + a push (WP17, R58)
        await session.execute(update(m.Draft).where(m.Draft.id == UUID(draft_id)).values(
            needs_human=True, **extra))
        await notify.enqueue(session, job.tenant_id, "handoff", UUID(draft_id), now)
        await annotate(session, conv, "handoff", UUID(draft_id), now)

    async def try_book(o: dict[str, Any], key: str) -> tuple[str | None, str | None]:
        """(booking id, None) | (None, why) | (None, None) when the reply books nothing. WP18."""
        code = o.get("book")
        if not (isinstance(code, str) and code.strip()):
            return None, None
        r = await registry.execute(ctx, session, "book_slot", {"slot_code": code.strip()}, allowlist=allowed,
                                   effect_ceiling="internal", idempotency_key=key)
        if r.status == "ok":
            return r.data["booking_id"], None
        return None, ", ".join(f"{v.code.value} {v.span or ''}".strip() for v in r.violations) or r.status

    async def hold() -> None:  # a person takes over, but the waiting customer is not left unanswered
        fixed = skill.manifest.handoff_reply
        if not (turn and fixed and route == "channel" and effective_mode(skill.manifest, sandbox) == "auto"):
            return
        own = out.get("customer_text") if handoff and isinstance(out.get("customer_text"), str) else None
        for i, line in enumerate([own, fixed] if own else [fixed]):  # the model's words, checked; else the fixed line
            h = await registry.execute(ctx, session, "draft_followup", {
                "text": line, "reason_code": out["reason_code"], "has_new_info": True,
                "claims": out.get("claims", []) if line == own else [],
                "max_touches": TURN_MAX_TOUCHES, "never_say": skill.manifest.never_say, "route": route},
                allowlist=allowed, effect_ceiling="internal", idempotency_key=f"hold:{job.id}:{i}")
            if h.status == "proposed":
                break
        if h.status == "proposed":
            sent = await registry.execute(ctx, session, "send_message", {"draft_id": h.data["draft_id"]},
                                          allowlist=allowed, effect_ceiling=profile.effect_ceiling)  # type: ignore[arg-type]
            _log(session, run, conv, "turn_hold_sent" if sent.status == "ok" else "turn_hold_failed", now,
                 skill=skill.name)

    booked: str | None = None
    try:
        recent = await recent_messages(session, conv)
        for attempt in (0, 1):  # one retry for a non-JSON answer (the gateway already retries transient errors)
            try:
                messages = await build_messages(session, profile, skill, conv, contact, window, recent, turn=turn)
                final = await _loop(session, gateway, registry, ctx, run, messages, read_allow,
                                    profile.max_tool_calls, profile.timeout_s)
                out = parse_json_object(final)
                break
            except ShapeError:
                if attempt:
                    raise
                log.warning("customer run: model answer was not usable JSON, retrying once")
        # Facts first (N5): what the customer said can end this run before any draft.
        if isinstance(out.get("facts"), list) and out["facts"] and not shadow:
            labels = {f"m{i}": r.id for i, r in enumerate(recent, 1)}
            raw = [{"kind": f.get("kind"), "value": f.get("value"), "evidence_msg_ids": [
                       str(labels[e]) for e in f.get("evidence") or [] if e in labels]}
                   for f in out["facts"] if isinstance(f, dict)]
            rec = await registry.execute(ctx, session, "record_facts", {"facts": raw},
                                         allowlist=["record_facts"], effect_ceiling="internal",
                                         idempotency_key=f"facts:{job.id}")
            data = rec.data or {}
            if data.get("outcome_candidate") or (
                    data.get("promised_active") and job.event_type == "conversation.silent"):
                return finish("none", decision="run_none", reason="promised_future"
                              if data.get("promised_active") else "outcome_candidate")
        act = out.get("act")
        if turn and act in ("reply", "handoff"):  # same path as a draft from here on
            handoff, act = act == "handoff", "draft"
            await session.refresh(conv, ["last_customer_msg_id", "last_staff_at"])  # spoke during the LLM call?
            if conv.last_customer_msg_id != turn_msg or conv.last_staff_at != staff_at:
                return finish("none", decision="turn_stale")
        if turn and act == "wait" and shadow:
            run.act = "none"
            return finish("none", decision="shadow_wait")
        if turn and act == "wait":
            # Conditional on the same turn: a message that arrived meanwhile has already re-armed the mark.
            waited = await session.execute(update(m.Conversation).where(
                m.Conversation.id == conv.id, m.Conversation.last_customer_msg_id == turn_msg,
                m.Conversation.reply_waits < 1).values(
                reply_waits=m.Conversation.reply_waits + 1, reply_check_at=now + TURN_WAIT))
            run.act = "none"
            return finish("none", decision="turn_wait" if waited.rowcount else "turn_wait_spent")
        if act == "none":
            run.act = "none"
            run.reason_code = out.get("reason_code") if out.get("reason_code") in reason_codes else None
            return finish("none", basis=window["basis"])
        if act != "draft" or not isinstance(out.get("text"), str):
            raise ShapeError("act must be 'none' or 'draft' with a text")
        limits = skill.manifest.limits
        if turn and out.get("reason_code") not in reason_codes:
            out["reason_code"] = "khong_ro"  # the turn skill asks no reason from the model
        if turn and not handoff and not shadow:  # WP18: the seat is held BEFORE the reply that confirms it is written
            booked, why = await try_book(out, f"book:{job.id}")
            if why:
                messages += [{"role": "assistant", "content": final}, {"role": "user", "content": (
                    f"Không giữ được chỗ ({why}). Đừng xác nhận lịch đó với khách. Gọi list_open_slots, chọn lịch "
                    'khác còn chỗ (ghi "book") rồi viết lại cùng JSON; không có lịch hợp thì act handoff.')}]
                out2 = parse_json_object(await _loop(session, gateway, registry, ctx, run, messages, read_allow,
                                                     profile.max_tool_calls, profile.timeout_s))
                if out2.get("act") == "reply" and isinstance(out2.get("text"), str):
                    out = {**out2, "reason_code": out["reason_code"]}
                    booked, why = await try_book(out, f"book:{job.id}:2")
                if why or booked is None and out2.get("act") != "reply":  # no seat to promise: a person's call
                    note = out2.get("text") if out2.get("act") == "handoff" and isinstance(out2.get("text"), str) else (
                        "Khách muốn đặt lịch học thử nhưng hệ thống chưa giữ được chỗ. Nhờ anh/chị xếp lịch cho khách.")
                    out, handoff, booked = {"reason_code": out["reason_code"], "text": note, "claims": [],
                                            "customer_text": out2.get("customer_text")}, True, None
        res = await registry.execute(  # the validator runs inside this tool (A7)
            ctx, session, "draft_followup",
            {"text": out["text"], "reason_code": out.get("reason_code"),
             "has_new_info": True if turn else out.get("has_new_info"), "claims": out.get("claims", []),
             "max_touches": TURN_MAX_TOUCHES if turn else limits.get("max_touches", 2), "never_say": skill.manifest.never_say,
             "route": route},
            allowlist=allowed, effect_ceiling="internal", idempotency_key=str(job.id))
        if turn and not handoff and res.status == "blocked":  # one rewrite, told why, before a person is needed
            why = "; ".join(f"{v.code.value} {v.span or v.detail or ''}".strip() for v in res.violations)
            messages += [{"role": "assistant", "content": final}, {"role": "user", "content": (
                f"Câu trả lời bị chặn: {why}. Viết lại cùng JSON: bỏ đúng các cụm bị cấm nêu trên, bỏ mọi "
                "số/ngày không có trong catalog (kể cả số khách vừa nói), không hứa việc bạn không tự làm được. "
                "Không chắc thì act handoff.")}]
            out2 = parse_json_object(await _loop(session, gateway, registry, ctx, run, messages, read_allow,
                                                 profile.max_tool_calls, profile.timeout_s))
            if out2.get("act") == "reply" and isinstance(out2.get("text"), str) \
                    and (not out2.get("book") or out2.get("book") == out.get("book")):  # the seat is the one held
                out = {**out2, "reason_code": out["reason_code"]}
                res = await registry.execute(ctx, session, "draft_followup", {
                    "text": out["text"], "reason_code": out["reason_code"], "has_new_info": True,
                    "claims": out.get("claims", []), "max_touches": TURN_MAX_TOUCHES,
                    "never_say": skill.manifest.never_say, "route": route},
                    allowlist=allowed, effect_ceiling="internal", idempotency_key=f"{job.id}:rewrite")
        if shadow:  # written and validated like a real one, then put where only the owner reads it
            if res.status == "proposed":
                await session.execute(update(m.Draft).where(m.Draft.id == UUID(res.data["draft_id"])).values(status="shadow"))
                run.act = "draft"
                return finish("ok", decision="shadow_draft", draft_id=res.data["draft_id"])
            return finish("blocked", "done", *[v.code.value for v in res.violations], decision="shadow_blocked")
        if booked and res.status != "proposed":  # the confirming reply was blocked: do not keep a seat nobody was told of
            await cancel_booking(session, UUID(booked), by=ctx.actor, now=now)
    except (LLMError, ShapeError) as e:
        job.attempts += 1
        if booked:  # the model failed after a seat was held: the customer was told nothing
            await cancel_booking(session, UUID(booked), by=ctx.actor, now=now)
        if turn and not shadow:  # the model failed, the customer is still waiting: a person's card + the fixed line
            out, handoff = {"reason_code": "khong_ro"}, True
            card = await registry.execute(ctx, session, "draft_followup", {
                "text": "Hệ thống chưa soạn được câu trả lời cho lượt này, nhờ anh/chị trả lời khách.",
                "reason_code": "khong_ro", "has_new_info": True, "claims": [], "max_touches": TURN_MAX_TOUCHES,
                "never_say": [], "route": route}, allowlist=allowed, effect_ceiling="internal",
                idempotency_key=f"{job.id}:error")
            if card.status == "proposed":
                await flag_human(card.data["draft_id"])
                await hold()
        return finish("error", "failed", decision="run_error", error=type(e).__name__)
    run.act, run.reason_code = "draft", out.get("reason_code") if out.get("reason_code") in reason_codes else None

    if res.status == "proposed":
        if handoff:  # DESIGN §5.7: a person's call (discount, complaint, out of catalog): never auto
            await flag_human(res.data["draft_id"])
            await hold()
        if route == "offchannel":
            return finish("ok", decision="draft_offchannel", channel=conv.channel_kind)
        if effective_mode(skill.manifest, sandbox) == "auto" and not handoff:
            # Layer 1 of A9 allows it; the tool re-checks the floor. Anything but `ok` leaves the draft
            # `proposed` for staff, which is the fallback to manual.
            sent = await registry.execute(
                ctx, session, "send_message", {"draft_id": res.data["draft_id"]}, allowlist=allowed,
                effect_ceiling=profile.effect_ceiling)  # type: ignore[arg-type]
            if sent.status == "ok":
                return finish("ok", decision="send_queued", basis=window["basis"],
                              not_before=sent.data["not_before"])
            codes = [f"{v.code.value}:{v.detail}" for v in sent.violations] or [sent.status]
            _log(session, run, conv, "fallback_manual", now, skill=skill.name, codes=codes)
            if turn:  # refused at the send floor (must_handoff, window…): a person's card, the customer told
                await flag_human(res.data["draft_id"])
                await hold()
        return finish("ok", decision="draft_proposed", basis=window["basis"],
                      human_typed_only=window["basis"] == "human_agent")
    if res.status == "blocked" and turn and res.data:  # R50: a customer is waiting; silence drops them
        await flag_human(res.data["draft_id"], status="proposed")  # a person's card, never sent by AI (send.py)
        await hold()
        return finish("ok", decision="turn_handoff_blocked", codes=[v.code.value for v in res.violations])
    if res.status == "blocked":
        return finish("blocked", "done", *[v.code.value for v in res.violations],
                      decision="draft_blocked", basis=window["basis"])
    job.attempts += 1  # tool-level error (e.g. malformed claims)
    return finish("error", "failed", decision="run_error",
                  error=res.error.code.value if res.error else res.status)


async def run_pending(now: datetime, gateway: LLMGateway, registry: ToolRegistry | None = None,
                      *, limit: int = 50) -> int:
    """Select (0 token) then write: runs up to `limit` jobs per tenant. Returns runs done."""
    registry = registry or default_registry(clock=lambda: now)
    async with system_session() as s:
        tenants: list[UUID] = await list_active_tenants(s)
    done = 0
    for tid in tenants:
        async with tenant_session(tid) as session:
            for sb in (await session.execute(select(m.Sandbox))).scalars().all():
                for job in (await select_jobs(session, sb, now))[:limit]:
                    job_id = job.id
                    try:
                        async with session.begin_nested():  # a crash costs one job, not the batch
                            await run_job(session, job, gateway, registry, now)
                    except Exception:
                        log.exception("run_job crashed")
                        await session.execute(update(m.FollowupJob).where(
                            m.FollowupJob.id == job_id).values(
                            status="failed", attempts=m.FollowupJob.attempts + 1))
                    done += 1
    return done
