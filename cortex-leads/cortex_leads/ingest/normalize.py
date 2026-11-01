"""Event -> contact/conversation/message, and the "new message cancels pending work" rule."""
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.channels.policy import CHANNEL_POLICIES
from cortex_leads.clock.schedule import compute_next_check_at
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.domain.pack import load_pack
from cortex_leads.guard.optout import wants_to_stop
from cortex_leads.ingest.deal import apply_deal
from cortex_leads.ingest.format import ContactRef, Event
from cortex_leads.memory.service import capture_from_message, opt_out
from cortex_leads.skills.registry import reply_after_for, silent_after_for

Status = Literal["accepted", "duplicate", "rejected"]


async def claim_event(session: AsyncSession, connector: m.Connector, external_id: str,
                      type_: str, payload: dict[str, Any], status: str, error: str | None) -> bool:
    """Idempotency gate (unique key). A previously *rejected* event may be re-sent fixed."""
    stmt = pg_insert(m.IngestEvent).values(
        id=uuid7(), tenant_id=connector.tenant_id, connector_id=connector.id,
        external_id=external_id, type=type_, payload=payload, status=status, error=error)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "connector_id", "external_id"],
        set_={"status": status, "error": error, "payload": payload, "type": type_},
        where=m.IngestEvent.status == "rejected").returning(m.IngestEvent.id)
    return (await session.execute(stmt)).first() is not None


async def apply_event_detailed(session: AsyncSession, connector: m.Connector, event: Event,
                               now: datetime) -> tuple[Status, str | None]:
    # DESIGN A3: tenant_id / sandbox_id come from the connector row, never from the body.
    payload = event.model_dump(mode="json")
    if event.type == "deal.updated":  # WP9: no channel, no conversation; see ingest/deal.py
        if not await claim_event(session, connector, event.external_id, event.type, payload,
                                 "accepted", None):
            return "duplicate", None
        await apply_deal(session, connector, event, now)
        return "accepted", None
    assert event.channel and event.conversation and isinstance(event.contact, ContactRef)
    if event.channel.kind not in CHANNEL_POLICIES or event.channel.kind != connector.channel_kind:
        err = f"channel.kind {event.channel.kind!r} does not match this connector"
        await claim_event(session, connector, event.external_id, event.type, payload,
                          "rejected", err)
        return "rejected", err
    if not await claim_event(session, connector, event.external_id, event.type, payload,
                             "accepted", None):
        return "duplicate", None

    tid = connector.tenant_id
    contact = (await session.execute(
        pg_insert(m.Contact).values(
            id=uuid7(), tenant_id=tid, connector_id=connector.id,
            external_id=event.contact.external_id, display_name=event.contact.display_name,
            phone=event.contact.phone)
        .on_conflict_do_update(
            index_elements=["tenant_id", "connector_id", "external_id"],
            set_={"display_name": m.Contact.display_name if event.contact.display_name is None
                  else event.contact.display_name,
                  "phone": m.Contact.phone if event.contact.phone is None else event.contact.phone})
        .returning(m.Contact))).scalar_one()
    await session.execute(pg_insert(m.Conversation).values(
        id=uuid7(), tenant_id=tid, sandbox_id=connector.sandbox_id, connector_id=connector.id,
        external_id=event.conversation.external_id, contact_id=contact.id,
        channel_kind=connector.channel_kind).on_conflict_do_nothing(
            index_elements=["tenant_id", "connector_id", "external_id"]))
    conv = (await session.execute(
        select(m.Conversation).where(
            m.Conversation.tenant_id == tid, m.Conversation.connector_id == connector.id,
            m.Conversation.external_id == event.conversation.external_id)
        .with_for_update())).scalar_one()

    if event.type == "message.created":
        inserted = await session.execute(pg_insert(m.Message).values(
            id=uuid7(), tenant_id=tid, conversation_id=conv.id, connector_id=connector.id,
            external_id=event.external_id, sender_role=event.sender.role,
            staff_ref=event.staff.external_id, text=event.text or "",
            occurred_at=event.occurred_at).on_conflict_do_nothing().returning(m.Message.id))
        row = inserted.first()
        if row is None:
            return "duplicate", None
        await _on_message(session, conv, event, now)
        if event.sender and event.sender.role == "customer":  # suggestions only (N5)
            await capture_from_message(session, conv, row[0], event.text or "", now)
            if wants_to_stop(event.text or ""):  # not a suggestion: acted on at once (see guard/optout.py)
                await opt_out(session, conv, source="rule", now=now)
    conv.updated_at = now
    await session.flush()
    return "accepted", None


async def apply_event(session: AsyncSession, connector: m.Connector, event: Event,
                      now: datetime) -> Status:
    return (await apply_event_detailed(session, connector, event, now))[0]


async def _on_message(session: AsyncSession, conv: m.Conversation, event: Event,
                      now: datetime) -> None:
    role, at = event.sender.role, event.occurred_at
    if role == "customer":
        if conv.last_customer_at is None or at >= conv.last_customer_at:
            conv.last_customer_at, conv.last_customer_msg_id = at, event.external_id
        # DESIGN A6: intents come from the sandbox's domain pack; an empty pack assigns none.
        sandbox = await session.get(m.Sandbox, conv.sandbox_id)
        if sandbox and (intent := load_pack(sandbox).match_intent(event.text or "")):
            conv.intent = intent
    elif role == "staff":
        if conv.last_staff_at is None or at > conv.last_staff_at:
            conv.last_staff_at = at
    # bot messages are neither customer nor staff speech: they move no clock.
    if role == "bot":
        conv.reply_check_at = None
        return
    tz = (await session.execute(
        select(m.Tenant.timezone).where(m.Tenant.id == conv.tenant_id))).scalar_one()
    conv.next_check_at = None if conv.offchannel_contact else compute_next_check_at(
        conv.last_customer_at, conv.last_staff_at, conv.promised_date, conv.state, tz, now,
        await silent_after_for(session, conv.sandbox_id))
    # DESIGN §5.7 `turn`: each customer message slides the "finished talking" mark; staff/bot clear it.
    conv.reply_check_at, conv.reply_waits = None, 0
    if role == "customer" and conv.state == "open" and not conv.offchannel_contact and not (
            await session.get(m.Contact, conv.contact_id)).opted_out \
            and (after := await reply_after_for(session, conv.sandbox_id)) is not None:
        conv.reply_check_at = conv.last_customer_at + after  # = at, unless it arrived late
    # DESIGN §5.7: a new message only cancels/postpones, never creates work.
    jobs = (await session.execute(
        update(m.FollowupJob).where(
            m.FollowupJob.tenant_id == conv.tenant_id, m.FollowupJob.conversation_id == conv.id,
            m.FollowupJob.status == "pending")
        .values(status="skipped", updated_at=now).returning(m.FollowupJob.id))).all()
    drafts = (await session.execute(
        update(m.Draft).where(
            m.Draft.tenant_id == conv.tenant_id, m.Draft.conversation_id == conv.id,
            m.Draft.status == "proposed",
            # a person's card waits for a person: the customer was told someone will answer (WP16)
            *([m.Draft.needs_human.is_(False)] if role == "customer" else []))
        .values(status="expired", decided_at=now).returning(m.Draft.id))).all()
    for decision, n in (("job_cancelled_new_message", len(jobs)), ("draft_expired", len(drafts))):
        if n:  # counts and role only: no customer text in decision_log
            session.add(m.DecisionLog(tenant_id=conv.tenant_id, conversation_id=conv.id,
                                      decision=decision, reason_code="new_message",
                                      detail={"count": n, "sender_role": role}, at=now))
