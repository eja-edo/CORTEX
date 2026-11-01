"""Trigger engine (DESIGN §5.7): 0 token, equality-only matching, one job per (skill, dedupe_key)."""
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.sandbox.policy import is_paused
from cortex_leads.skills.manifest import parse_duration
from cortex_leads.skills.registry import (
    TURN_EVENT,
    LoadedSkill,
    live_skills_for,
    match,
    shadow_skills_for,
    silent_after,
)

Source = Literal["clock", "engine", "event"]
STAFF_ACTIVE = timedelta(minutes=10)  # DESIGN §5.7: staff spoke this recently = they have the conversation
TURN_MAX_AGE = timedelta(hours=6)  # an older "turn" is imported history or a long outage, not a customer waiting


def dedupe_key(conv: m.Conversation, event_type: str) -> str:
    if event_type == "conversation.promised_date_reached":
        return f"promised:{conv.id}:{conv.promised_date}"
    if event_type == TURN_EVENT:  # once per turn; a `wait` bumps reply_waits so the turn may fire again
        return f"turn:{conv.id}:{conv.last_customer_msg_id}:{conv.reply_waits}"
    anchor = conv.last_customer_msg_id or (wire(conv.last_staff_at) if conv.last_staff_at else "none")
    return f"silent:{conv.id}:{anchor}"


def _log(session: AsyncSession, conv: m.Conversation, decision: str, reason: str | None,
         now: datetime, detail: dict[str, Any] | None = None) -> None:
    session.add(m.DecisionLog(tenant_id=conv.tenant_id, conversation_id=conv.id, decision=decision,
                              reason_code=reason, detail=detail or {}, at=now))


async def _turn_skip(session: AsyncSession, conv: m.Conversation, now: datetime) -> str | None:
    """0-token rules of the customer turn: only answer a customer nobody is answering."""
    last = (await session.execute(select(m.Message.sender_role).where(
        m.Message.conversation_id == conv.id).order_by(m.Message.occurred_at.desc()).limit(1))).scalar_one_or_none()
    if last != "customer":
        return "last_not_customer"
    if conv.last_staff_at is not None and now - conv.last_staff_at <= STAFF_ACTIVE:
        return "staff_active"
    if conv.last_customer_at is not None and now - conv.last_customer_at > TURN_MAX_AGE:
        return "turn_too_old"
    return None


async def _last_touch(session: AsyncSession, conv: m.Conversation) -> datetime | None:
    """Latest message that actually went to the customer: outbox sent, or staff sent/approved a draft."""
    sent = (await session.execute(select(func.max(m.Outbox.sent_at)).where(
        m.Outbox.conversation_id == conv.id, m.Outbox.status == "sent"))).scalar_one()
    decided = (await session.execute(select(func.max(m.Draft.decided_at)).where(
        m.Draft.conversation_id == conv.id,
        m.Draft.status.in_(("sent", "edited", "approved"))))).scalar_one()
    return max((t for t in (sent, decided) if t is not None), default=None)


def _ready(skill: LoadedSkill, conv: m.Conversation, event_type: str, touch: datetime | None,
           now: datetime) -> tuple[datetime, str | None]:
    """When this skill may fire, and why not yet (`not_due_yet` | `min_gap`)."""
    at, why = now, None
    if event_type == "conversation.silent":
        last = max((t for t in (conv.last_customer_at, conv.last_staff_at) if t), default=None)
        if last is not None and last + silent_after(skill) > now:
            at, why = last + silent_after(skill), "not_due_yet"
    gap = skill.manifest.limits.get("min_gap")
    if touch is not None and gap and touch + parse_duration(gap) > max(at, now):
        at, why = touch + parse_duration(gap), "min_gap"
    return at, why


async def on_conversation_event(session: AsyncSession, conversation: m.Conversation,
                                event_type: str, now: datetime, *,
                                source: Source = "clock") -> list[m.FollowupJob]:
    if source == "engine":  # DESIGN §5.7: events the engine caused never match again
        _log(session, conversation, "event_ignored", "source_engine", now, {"event": event_type})
        return []
    if conversation.offchannel_contact or conversation.state != "open":  # N5: a human has it / it is over
        _log(session, conversation, "event_ignored", "offchannel" if conversation.offchannel_contact
             else "not_open", now, {"event": event_type})
        return []
    sandbox = await session.get(m.Sandbox, conversation.sandbox_id)
    if sandbox is None or is_paused(sandbox):
        _log(session, conversation, "event_ignored", "paused", now, {"event": event_type})
        return []
    if event_type == TURN_EVENT and (why := await _turn_skip(session, conversation, now)):
        if why == "staff_active":  # R44: staff may walk away; look again once their 10 minutes are up
            conversation.reply_check_at = conversation.last_staff_at + STAFF_ACTIVE
        _log(session, conversation, "event_ignored", why, now, {"event": event_type})
        return []
    touch = await _last_touch(session, conversation)
    for sk in (s for s in await shadow_skills_for(session, sandbox.id, event_type) if match(s, conversation)):
        if _ready(sk, conversation, event_type, touch, now)[1] is None:  # a trial runs beside the live skill, never instead of it
            await _enqueue(session, conversation, sandbox, sk, event_type, now, shadow=True)
    matched = [s for s in await live_skills_for(session, sandbox.id, event_type)
               if match(s, conversation)]
    if not matched:
        _log(session, conversation, "no_matching_skill", None, now, {"event": event_type})
        return []
    ready, later = [], []
    for sk in matched:
        at, why = _ready(sk, conversation, event_type, touch, now)
        if why is None:
            ready.append(sk)
        else:
            later.append(at)
            _log(session, conversation, why, None, now, {"skill": sk.name, "at": wire(at)})
    if later:  # re-time the clock to the earliest skill that is not ready yet (the sweeper cleared it)
        conversation.next_check_at = min(later)
    if not ready:
        return []
    # One job per event (DESIGN §5.5): the most specific match wins, name breaks ties; a skill that
    # already fired for this silence is skipped so a later-due sibling can still go.
    for skill in sorted(ready, key=lambda s: (-len(s.manifest.trigger.match), s.name)):
        if job := await _enqueue(session, conversation, sandbox, skill, event_type, now):
            return [job]
    return []


async def _enqueue(session: AsyncSession, conversation: m.Conversation, sandbox: m.Sandbox, skill: LoadedSkill,
                   event_type: str, now: datetime, *, shadow: bool = False) -> m.FollowupJob | None:
    """One job per (skill, silence). A shadow job has its own key, so a trial of a new version of a live
    skill does not take the live one's place."""
    key = dedupe_key(conversation, event_type)
    row = (await session.execute(pg_insert(m.FollowupJob).values(
        id=uuid7(), tenant_id=conversation.tenant_id, sandbox_id=sandbox.id,
        conversation_id=conversation.id, skill_name=skill.name, skill_version=skill.version,
        event_type=event_type, dedupe_key=f"shadow:{key}" if shadow else key, status="pending",
        not_before=now, created_at=now, updated_at=now)
        .on_conflict_do_nothing(index_elements=["tenant_id", "sandbox_id", "skill_name", "dedupe_key"])
        .returning(m.FollowupJob.id))).first()
    if row is None:  # already fired for this silence
        return None
    job = (await session.execute(select(m.FollowupJob).where(m.FollowupJob.id == row[0]))).scalar_one()
    _log(session, conversation, "shadow_job_created" if shadow else "job_created", None, now,
         {"skill": skill.name, "version": skill.version, "event": event_type})
    return job
