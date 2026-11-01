"""Contact memory + promise lifecycle (DESIGN N5, §5.3). Every fact is validated against evidence
(customer messages of the same conversation); the AI can never move the clock or the conversation
state on its own word alone. All time comes in as `now`."""
import json
from datetime import date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.clock.schedule import compute_next_check_at
from cortex_leads.core.errors import CortexError
from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import wire_date
from cortex_leads.db import models as m
from cortex_leads.domain.pack import DomainPack, load_pack
from cortex_leads.guard.facts import HORIZON_DAYS, extract_date_candidates, is_vague
from cortex_leads.outbound.annotate import annotate

ContactFact = m.ContactFact
CONV_SCOPED = {"promised_date", "outcome", "offchannel"}  # one live fact per conversation
STATE_OF = {"won": "won", "booked": "booked", "lost": "lost", "cancelled": "lost"}
Outcome = Literal["booked", "won", "lost", "cancelled", "reopen"]


class MemoryError(CortexError):
    """.code: NO_EVIDENCE | EVIDENCE_NOT_CUSTOMER | EVIDENCE_OTHER_CONVERSATION |
    DATE_NOT_IN_EVIDENCE | DATE_OUT_OF_RANGE | UNKNOWN_KIND | TOO_MANY_FACTS | BAD_VALUE | NOT_FOUND"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


async def _conv(session: AsyncSession, conversation_id: UUID) -> m.Conversation:
    conv = await session.get(m.Conversation, conversation_id, with_for_update=True)
    if conv is None:
        raise MemoryError("NOT_FOUND", "conversation")
    return conv


async def _tz(session: AsyncSession, tenant_id: UUID) -> str:
    return (await session.execute(select(m.Tenant.timezone).where(m.Tenant.id == tenant_id))).scalar_one()


async def local_today(session: AsyncSession, tenant_id: UUID, now: datetime) -> date:
    return now.astimezone(ZoneInfo(await _tz(session, tenant_id))).date()


async def _pack(session: AsyncSession, conv: m.Conversation) -> DomainPack:
    return load_pack(await session.get(m.Sandbox, conv.sandbox_id))


async def _evidence(session: AsyncSession, conv: m.Conversation, ids: list[UUID],
                    required: bool) -> list[str]:
    if not ids:
        if required:
            raise MemoryError("NO_EVIDENCE")
        return []
    rows = (await session.execute(select(m.Message).where(m.Message.id.in_(ids)))).scalars().all()
    if len(rows) != len(set(ids)) or any(r.conversation_id != conv.id for r in rows):
        raise MemoryError("EVIDENCE_OTHER_CONVERSATION")
    if any(r.sender_role != "customer" for r in rows):
        raise MemoryError("EVIDENCE_NOT_CUSTOMER")
    return [r.text for r in rows]


async def _rearm(session: AsyncSession, conv: m.Conversation, now: datetime) -> None:
    conv.next_check_at = None if conv.offchannel_contact else compute_next_check_at(
        conv.last_customer_at, conv.last_staff_at, conv.promised_date, conv.state,
        await _tz(session, conv.tenant_id), now)


async def _cancel_work(session: AsyncSession, conv: m.Conversation, now: datetime, *,
                       drafts: bool) -> tuple[int, int]:
    jobs = (await session.execute(update(m.FollowupJob).where(
        m.FollowupJob.conversation_id == conv.id, m.FollowupJob.status == "pending")
        .values(status="skipped", updated_at=now).returning(m.FollowupJob.id))).all()
    exp = (await session.execute(update(m.Draft).where(
        m.Draft.conversation_id == conv.id, m.Draft.status == "proposed")
        .values(status="expired", decided_at=now).returning(m.Draft.id))).all() if drafts else []
    return len(jobs), len(exp)


def _check_value(kind: str, value: Any, pack: DomainPack, today: date) -> dict[str, Any]:
    if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=False)) > 500:
        raise MemoryError("BAD_VALUE", "value must be a small object")
    if kind == "promised_date":
        try:
            d = date.fromisoformat(str(value.get("date")))
        except ValueError:
            raise MemoryError("BAD_VALUE", "date must be YYYY-MM-DD") from None
        if not today < d <= today + timedelta(days=HORIZON_DAYS):
            raise MemoryError("DATE_OUT_OF_RANGE")
        return {"date": wire_date(d)}
    if kind == "decision_maker" and value.get("role") not in pack.decision_maker_roles:
        raise MemoryError("BAD_VALUE", "role")
    if kind == "outcome" and value.get("status") not in {*STATE_OF, "reopen"}:
        raise MemoryError("BAD_VALUE", "status")
    return value


async def _supersede(session: AsyncSession, fact: ContactFact, statuses: tuple[str, ...], now: datetime) -> None:
    q = update(ContactFact).where(
        ContactFact.contact_id == fact.contact_id, ContactFact.kind == fact.kind,
        ContactFact.id != fact.id, ContactFact.status.in_(statuses))
    if fact.kind in CONV_SCOPED:
        q = q.where(ContactFact.conversation_id == fact.conversation_id)
    await session.execute(q.values(status="superseded", superseded_by=fact.id, updated_at=now))


async def _project(session: AsyncSession, conv: m.Conversation, fact: ContactFact, now: datetime) -> None:
    """Active fact -> the column the rest of the system reads."""
    if fact.kind == "promised_date":
        conv.promised_date = date.fromisoformat(fact.value["date"])
        await _rearm(session, conv, now)
    elif fact.kind == "decision_maker":
        (await session.get(m.Contact, conv.contact_id)).decision_maker = fact.value["role"]
    elif fact.kind == "offchannel":
        conv.offchannel_contact, conv.next_check_at = True, None
        await _cancel_work(session, conv, now, drafts=False)


async def _new_fact(session: AsyncSession, conv: m.Conversation, kind: str, value: dict[str, Any],
                    evidence: list[UUID], source: str, status: str, now: datetime) -> ContactFact:
    fact = ContactFact(id=uuid7(), tenant_id=conv.tenant_id, contact_id=conv.contact_id,
                       conversation_id=conv.id, kind=kind, value=value, evidence_msg_ids=evidence,
                       source=source, status=status, created_at=now, updated_at=now)
    session.add(fact)
    await session.flush()
    await _supersede(session, fact, ("active", "candidate") if status == "active" else ("candidate",), now)
    if status == "active":
        await _project(session, conv, fact, now)
    return fact


async def record_fact(session, *, conversation_id: UUID, kind: str, value: dict, evidence_msg_ids: list[UUID],
                      source: str, now: datetime) -> ContactFact:
    conv = await _conv(session, conversation_id)
    pack = await _pack(session, conv)
    if kind not in pack.all_fact_kinds:
        raise MemoryError("UNKNOWN_KIND", kind)
    staff, ai = source.startswith("staff:"), source.startswith("ai:")
    if not (staff or ai or source == "rule"):
        raise MemoryError("BAD_VALUE", "source")
    texts = await _evidence(session, conv, evidence_msg_ids, required=not staff)
    value = _check_value(kind, value, pack, await local_today(session, conv.tenant_id, now))
    if kind == "outcome":
        return (await _outcome(session, conv, value["status"], source, evidence_msg_ids, now))[1]
    # Only a human (or the rule layer, as a *suggestion*) decides what the AI cannot verify.
    status = "active" if staff or (ai and kind != "offchannel") else "candidate"
    if kind == "promised_date" and ai:
        tz = await _tz(session, conv.tenant_id)
        want = date.fromisoformat(value["date"])
        if not any(want in extract_date_candidates(t, now, tz) for t in texts):
            if not any(is_vague(t) for t in texts):
                raise MemoryError("DATE_NOT_IN_EVIDENCE")
            status = "candidate"
    return await _new_fact(session, conv, kind, value, evidence_msg_ids, source, status, now)


async def _outcome(session: AsyncSession, conv: m.Conversation, status: str, source: str,
                   evidence: list[UUID], now: datetime) -> tuple[m.Conversation, ContactFact]:
    if source.startswith("ai:") or source == "rule":
        if source.startswith("ai:"):  # stop nagging until a human decides
            conv.next_check_at = None
            await _cancel_work(session, conv, now, drafts=False)
        return conv, await _new_fact(session, conv, "outcome", {"status": status}, evidence,
                                     source, "candidate", now)
    fact = await _new_fact(session, conv, "outcome", {"status": status}, evidence, source, "done", now)
    await _apply_outcome(session, conv, status, now)
    return conv, fact


async def _apply_outcome(session: AsyncSession, conv: m.Conversation, status: str, now: datetime) -> None:
    if status == "reopen":
        conv.state = "open"
        await _rearm(session, conv, now)
        return
    closed = (await session.execute(update(ContactFact).where(
        ContactFact.conversation_id == conv.id, ContactFact.kind == "promised_date",
        ContactFact.status.in_(("active", "candidate")))
        .values(status="fulfilled" if status in ("won", "booked") else "cancelled", updated_at=now)
        .returning(ContactFact.id))).all()
    conv.state, conv.promised_date, conv.next_check_at = STATE_OF[status], None, None
    if STATE_OF[status] in ("won", "lost"):
        await annotate(session, conv, STATE_OF[status], conv.id, now)  # WP24: mark it on the platform if the business asked
    jobs, drafts = await _cancel_work(session, conv, now, drafts=True)
    session.add(m.DecisionLog(  # counts only: no customer text in decision_log
        tenant_id=conv.tenant_id, conversation_id=conv.id, decision="promise_closed_by_outcome",
        reason_code=status, detail={"promises": len(closed), "jobs": jobs, "drafts": drafts}, at=now))


BOOKING_SOURCE = "system:booking"


async def note_appointment(session: AsyncSession, *, conversation_id: UUID, on: date, now: datetime
                           ) -> ContactFact | None:
    """A seat the system itself holds (WP18) is the strongest evidence of a promise: it becomes the
    active `promised_date`, so follow-up waits and the "đúng hẹn" skill fires that morning. A date
    outside the horizon (today, or too far) is not noted: the booking stands, only the clock does not move."""
    conv = await _conv(session, conversation_id)
    today = await local_today(session, conv.tenant_id, now)
    if not today < on <= today + timedelta(days=HORIZON_DAYS):
        return None
    return await _new_fact(session, conv, "promised_date", {"date": wire_date(on)}, [],
                           BOOKING_SOURCE, "active", now)


async def release_appointment(session: AsyncSession, *, conversation_id: UUID, now: datetime) -> bool:
    """The booking behind the promise was cancelled: the promise goes with it (only if the system made it)."""
    conv = await _conv(session, conversation_id)
    gone = (await session.execute(update(ContactFact).where(
        ContactFact.conversation_id == conv.id, ContactFact.kind == "promised_date",
        ContactFact.source == BOOKING_SOURCE, ContactFact.status == "active")
        .values(status="cancelled", updated_at=now).returning(ContactFact.id))).all()
    if gone:
        conv.promised_date = None
        if conv.state == "open":
            await _rearm(session, conv, now)
    return bool(gone)


async def record_outcome(session, *, conversation_id: UUID, status: Outcome, source: str,
                         evidence_msg_ids: list[UUID], now: datetime) -> m.Conversation:
    conv = await _conv(session, conversation_id)
    if status not in {*STATE_OF, "reopen"}:
        raise MemoryError("BAD_VALUE", "status")
    await _evidence(session, conv, evidence_msg_ids, required=source.startswith("ai:"))
    return (await _outcome(session, conv, status, source, evidence_msg_ids, now))[0]


async def mark_offchannel(session, *, conversation_id: UUID, channel: Literal["phone", "zalo_personal", "in_person"],
                          staff_ref: str, now: datetime) -> ContactFact:
    conv = await _conv(session, conversation_id)
    return await _new_fact(session, conv, "offchannel", {"channel": channel}, [],
                           f"staff:{staff_ref}", "active", now)


async def _fact(session: AsyncSession, fact_id: UUID, *statuses: str) -> tuple[ContactFact, m.Conversation]:
    fact = await session.get(ContactFact, fact_id, with_for_update=True)
    if fact is None or fact.conversation_id is None:
        raise MemoryError("NOT_FOUND", "fact")
    if fact.status not in statuses:
        raise MemoryError("BAD_VALUE", f"fact is {fact.status}")
    return fact, await _conv(session, fact.conversation_id)


async def confirm_fact(session, fact_id: UUID, *, staff_ref: str, now: datetime) -> ContactFact:
    fact, conv = await _fact(session, fact_id, "candidate")
    if fact.kind == "outcome":
        await _apply_outcome(session, conv, fact.value["status"], now)
        fact.status, fact.updated_at = "done", now
        return fact
    if fact.kind == "promised_date":  # the date may have slipped into the past while it waited
        _check_value(fact.kind, fact.value, await _pack(session, conv),
                     await local_today(session, conv.tenant_id, now))
    await _supersede(session, fact, ("active", "candidate"), now)
    fact.status, fact.updated_at = "active", now
    await _project(session, conv, fact, now)
    return fact


async def reject_fact(session, fact_id: UUID, *, staff_ref: str, now: datetime) -> ContactFact:
    fact, conv = await _fact(session, fact_id, "candidate", "active")
    was_active, fact.status, fact.updated_at = fact.status == "active", "rejected", now
    if fact.kind == "promised_date" and was_active:
        conv.promised_date = None
    elif fact.kind == "decision_maker" and was_active:
        (await session.get(m.Contact, conv.contact_id)).decision_maker = None
    if fact.kind in ("outcome", "promised_date") and conv.state == "open":
        await _rearm(session, conv, now)  # tracking the AI had paused resumes
    return fact


async def list_facts(session, *, contact_id: UUID, include_inactive: bool = False) -> list[ContactFact]:
    q = select(ContactFact).where(ContactFact.contact_id == contact_id)
    if not include_inactive:
        q = q.where(ContactFact.status == "active")
    return list((await session.execute(q.order_by(ContactFact.created_at))).scalars())


async def pending_confirmations(session, *, sandbox_id: UUID) -> list[ContactFact]:
    q = (select(ContactFact).join(m.Conversation, m.Conversation.id == ContactFact.conversation_id)
         .where(m.Conversation.sandbox_id == sandbox_id, ContactFact.status == "candidate")
         .order_by(ContactFact.created_at))
    return list((await session.execute(q)).scalars())


async def has_pending_outcome(session: AsyncSession, conversation_id: UUID) -> bool:
    """Only an AI-proposed outcome blocks; a keyword-rule guess ("chưa chốt đâu") never does (R31)."""
    return (await session.execute(select(ContactFact.id).where(
        ContactFact.conversation_id == conversation_id, ContactFact.kind == "outcome",
        ContactFact.status == "candidate", ContactFact.source.like("ai:%")).limit(1))).first() is not None


async def capture_from_message(session: AsyncSession, conv: m.Conversation, message_id: UUID,
                               text: str, now: datetime) -> None:
    """0-token rules on a customer message: suggestions only (status candidate), they never
    touch the clock or the state. Needs a human to confirm."""
    if conv.state != "open":
        return
    pack, tz = await _pack(session, conv), await _tz(session, conv.tenant_id)
    guesses: list[tuple[str, dict[str, Any]]] = []
    if dates := extract_date_candidates(text, now, tz):
        guesses.append(("promised_date", {"date": wire_date(min(dates))}))
    if status := pack.match_outcome(text):
        guesses.append(("outcome", {"status": status}))
    for kind, value in guesses:
        try:
            async with session.begin_nested():
                await record_fact(session, conversation_id=conv.id, kind=kind, value=value,
                                  evidence_msg_ids=[message_id], source="rule", now=now)
        except MemoryError:
            pass


async def opt_out(session: AsyncSession, conv: m.Conversation, *, source: str, now: datetime) -> None:
    """The contact does not want to be written to. The flag is on the contact (every conversation, every
    sender checks it); this conversation leaves every list and its pending work is dropped."""
    contact = await session.get(m.Contact, conv.contact_id)
    if contact.opted_out and conv.state == "opted_out":
        return
    contact.opted_out = True
    conv.state, conv.next_check_at, conv.reply_check_at = "opted_out", None, None
    jobs, drafts = await _cancel_work(session, conv, now, drafts=True)
    session.add(m.DecisionLog(  # counts only: no customer text in decision_log
        tenant_id=conv.tenant_id, conversation_id=conv.id, decision="contact_opted_out",
        reason_code=source.split(":")[0], detail={"jobs": jobs, "drafts": drafts}, at=now))


async def opt_in(session: AsyncSession, conversation_id: UUID, *, source: str, now: datetime) -> None:
    """A person undoes a wrong or changed opt-out. Only a person: the AI never calls this."""
    if not source.startswith("staff:"):
        raise MemoryError("BAD_VALUE", "source")
    conv = await _conv(session, conversation_id)
    (await session.get(m.Contact, conv.contact_id)).opted_out = False
    if conv.state == "opted_out":
        conv.state = "open"
        await _rearm(session, conv, now)
    session.add(m.DecisionLog(tenant_id=conv.tenant_id, conversation_id=conv.id, decision="contact_opted_in",
                              reason_code="staff", detail={}, at=now))
