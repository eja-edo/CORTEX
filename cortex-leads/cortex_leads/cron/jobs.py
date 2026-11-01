"""Cron jobs, templates only (WP19, 0 token): numbers and ids come from tables, no text is written.
Each returns the new row, or None when there was nothing to say or the slot was already done."""
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.domain.pack import load_pack
from cortex_leads.notify import service as notify
from cortex_leads.tools.v0 import dropped_leads

SILENT_HOURS = 24
QUIET_MAX_DAYS = 7  # past a week it is the weekly list's work, not the morning's
CAPPED_LOOKBACK = timedelta(days=2)
MAX_LISTED = 50


def _utc(day: date, tz: str) -> datetime:
    return datetime.combine(day, time(0), tzinfo=ZoneInfo(tz))


async def owed_followups(session: AsyncSession, sandbox: m.Sandbox, slot: date, now: datetime,
                         taken: set[str]) -> dict[str, list[str]]:
    """What is still owed though nobody is waiting on an answer: a promise that has come (`due`), a customer
    who went quiet after staff answered (`quiet`), a job the daily staff cap dropped (`capped`). Computed from
    state, so a missed or skipped event cannot lose a conversation. Each conversation is listed once, in
    the most urgent group (`due` first); `taken` holds the ids of the unanswered list, which `due` overrides."""
    c = m.Conversation
    pending_ai_outcome = exists().where(
        m.ContactFact.conversation_id == c.id, m.ContactFact.kind == "outcome",
        m.ContactFact.status == "candidate", m.ContactFact.source.like("ai:%"))
    base = [c.tenant_id == sandbox.tenant_id, c.sandbox_id == sandbox.id, c.state == "open",
            c.offchannel_contact.is_not(True), ~pending_ai_outcome]
    priority = load_pack(sandbox).priority_intents
    queries = {
        "due": select(c.id).where(*base, c.promised_date <= slot).order_by(c.promised_date.asc()),
        "quiet": select(c.id).where(
            *base, c.last_staff_at.is_not(None), c.last_staff_at <= now - timedelta(hours=SILENT_HOURS),
            c.last_staff_at >= now - timedelta(days=QUIET_MAX_DAYS),
            or_(c.last_customer_at.is_(None), c.last_staff_at >= c.last_customer_at),
            or_(c.promised_date.is_(None), c.promised_date <= slot),
            *([c.intent.in_(priority)] if priority else [])).order_by(c.last_staff_at.asc()),
        "capped": select(c.id).join(m.DecisionLog, m.DecisionLog.conversation_id == c.id).where(
            *base, m.DecisionLog.decision == "job_skipped_budget", m.DecisionLog.at >= now - CAPPED_LOOKBACK,
            or_(c.last_staff_at.is_(None), c.last_staff_at < m.DecisionLog.at)).order_by(m.DecisionLog.at.asc()),
    }
    out: dict[str, list[str]] = {}
    for key, q in queries.items():
        skip = set() if key == "due" else taken  # a promise that came due says more than "nobody answered"
        ids = [str(i) for i in (await session.execute(q.limit(MAX_LISTED * 2))).scalars() if str(i) not in skip]
        out[key] = list(dict.fromkeys(ids))[:MAX_LISTED]
        taken |= set(out[key])
    return out


async def morning_list(session: AsyncSession, sandbox: m.Sandbox, tz: str, now: datetime, slot: date
                       ) -> m.StaffTask | None:
    """Who to look after today: customers left without an answer, promises that came due, customers gone
    quiet after an answer, jobs the cap dropped, and today's trial seats."""
    leads = await dropped_leads(session, sandbox.tenant_id, sandbox.id, now, silent_hours=SILENT_HOURS,
                                limit=MAX_LISTED)
    today = (await session.execute(select(func.count()).select_from(m.Booking).where(
        m.Booking.sandbox_id == sandbox.id, m.Booking.status == "confirmed",
        m.Booking.starts_at >= _utc(slot, tz), m.Booking.starts_at < _utc(slot + timedelta(days=1), tz)))).scalar_one()
    drafts = (await session.execute(select(func.count()).select_from(m.Draft).where(
        m.Draft.sandbox_id == sandbox.id, m.Draft.status == "proposed"))).scalar_one()
    owed = await owed_followups(session, sandbox, slot, now, {str(c.id) for c in leads})
    lead_ids = [str(c.id) for c in leads if str(c.id) not in owed["due"]]
    if not lead_ids and not today and not any(owed.values()):
        return None
    payload = {"leads": lead_ids, **owed, "bookings_today": today, "drafts_waiting": drafts}
    return await _once(session, m.StaffTask, "task", sandbox, now, kind="morning_list", for_date=slot,
                       payload=payload)


async def _once(session: AsyncSession, model: Any, notice: str, sandbox: m.Sandbox, now: datetime, **cols: Any):
    """INSERT ... ON CONFLICT DO NOTHING on the slot's unique key; push staff only when it was new."""
    new_id = (await session.execute(insert(model).values(
        id=uuid7(), tenant_id=sandbox.tenant_id, sandbox_id=sandbox.id, created_at=now, **cols)
        .on_conflict_do_nothing().returning(model.id))).scalar()
    if new_id is None:
        return None
    await notify.enqueue(session, sandbox.tenant_id, notice, new_id, now)
    return await session.get(model, new_id)


async def week_stats(session: AsyncSession, tenant_id, start: datetime, end: datetime) -> dict[str, int]:
    """Counts for [start, end). Only numbers leave this function."""
    def n(q: Any) -> Any:
        return session.execute(q)

    inr = lambda col: (col >= start, col < end)
    count = lambda col, *w: select(func.count()).select_from(col.class_).where(
        col.class_.tenant_id == tenant_id, *inr(col), *w)
    out = {
        "new_conversations": (await n(count(m.Conversation.created_at))).scalar_one(),
        "customer_messages": (await n(count(m.Message.occurred_at, m.Message.sender_role == "customer"))).scalar_one(),
        "drafts": (await n(count(m.Draft.created_at, m.Draft.status.not_in(("blocked", "shadow"))))).scalar_one(),
        "drafts_used": (await n(count(m.Draft.created_at, m.Draft.status.in_(("sent", "edited"))))).scalar_one(),
        "handoffs": (await n(count(m.Draft.created_at, m.Draft.needs_human.is_(True)))).scalar_one(),
        "ai_sent": (await n(count(m.Outbox.sent_at, m.Outbox.status == "sent", m.Outbox.kind == "message", m.Outbox.actor.like("ai:%")))).scalar_one(),
        "bookings": (await n(count(m.Booking.created_at))).scalar_one(),
        "bookings_cancelled": (await n(count(m.Booking.cancelled_at))).scalar_one(),
        "runs": (await n(count(m.TriggerRun.started_at))).scalar_one(),
    }
    out["tokens"] = int((await n(select(func.coalesce(func.sum(m.TriggerRun.tokens_in + m.TriggerRun.tokens_out), 0))
                         .where(m.TriggerRun.tenant_id == tenant_id, *inr(m.TriggerRun.started_at)))).scalar_one())
    status = m.ContactFact.value["status"].astext
    won = (await n(select(status, func.count()).where(
        m.ContactFact.tenant_id == tenant_id, m.ContactFact.kind == "outcome", m.ContactFact.status == "done",
        *inr(m.ContactFact.updated_at)).group_by(status))).all()
    for status in ("won", "booked", "lost"):
        out[f"outcome_{status}"] = next((c for s, c in won if s == status), 0)
    return out


async def weekly_digest(session: AsyncSession, sandbox: m.Sandbox, tz: str, now: datetime, slot: date
                        ) -> m.Digest | None:
    """The 7 days before `slot` (a Monday), against the 7 before that. `dropped_now` is a snapshot."""
    start, end, prev = (_utc(slot - timedelta(days=d), tz) for d in (7, 0, 14))
    tenant = sandbox.tenant_id
    dropped = 0
    for sb in (await session.execute(select(m.Sandbox).where(m.Sandbox.purpose == "customer_care"))).scalars():
        dropped += len(await dropped_leads(session, tenant, sb.id, now, silent_hours=SILENT_HOURS, limit=1000))
    payload = {"this": await week_stats(session, tenant, start, end),
               "prev": await week_stats(session, tenant, prev, start), "dropped_now": dropped}
    return await _once(session, m.Digest, "digest", sandbox, now, kind="weekly",
                       period_start=slot - timedelta(days=7), period_end=slot - timedelta(days=1), payload=payload)


async def monthly_digest(session: AsyncSession, sandbox: m.Sandbox, tz: str, now: datetime, slot: date
                         ) -> m.Digest | None:
    """The calendar month before `slot` (the 1st), against the month before that. Numbers only, as the weekly one."""
    last_day = slot - timedelta(days=1)
    first_day = last_day.replace(day=1)
    prev_first = (first_day - timedelta(days=1)).replace(day=1)
    start, end, prev = (_utc(d, tz) for d in (first_day, slot, prev_first))
    tenant = sandbox.tenant_id
    dropped = 0
    for sb in (await session.execute(select(m.Sandbox).where(m.Sandbox.purpose == "customer_care"))).scalars():
        dropped += len(await dropped_leads(session, tenant, sb.id, now, silent_hours=SILENT_HOURS, limit=1000))
    payload = {"kind": "monthly", "this": await week_stats(session, tenant, start, end),
               "prev": await week_stats(session, tenant, prev, start), "dropped_now": dropped}
    return await _once(session, m.Digest, "digest", sandbox, now, kind="monthly",
                       period_start=first_day, period_end=last_day, payload=payload)


async def scan_signals(session: AsyncSession, sandbox: m.Sandbox, tz: str, now: datetime, slot: date) -> int | None:
    """AI tổng, daily and 0 token: metadata in, proposals out. Returns how many were new."""
    from cortex_leads.supervisor.signals import read_findings, record

    return await record(session, sandbox.tenant_id, await read_findings(sandbox.tenant_id, now), now) or None
