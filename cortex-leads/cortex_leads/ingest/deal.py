"""deal.updated (DESIGN §5.2/N5): the CRM says how a deal ended. Matching is exact — a connector
ref, or a phone that identifies exactly one contact in the tenant. Never a guess."""
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.ingest.format import DealContact, Event
from cortex_leads.memory.service import record_outcome


def _digits(phone: str) -> str:
    d = re.sub(r"\D", "", phone)
    return "0" + d[2:] if d.startswith("84") else d


async def _match_contact(session: AsyncSession, connector: m.Connector, who: DealContact) -> m.Contact | None:
    if who.ref is not None:
        return (await session.execute(select(m.Contact).where(
            m.Contact.connector_id == who.ref.connector_id,
            m.Contact.external_id == who.ref.external_id))).scalar_one_or_none()
    if not who.phone or len(d := _digits(who.phone)) < 9:
        return None
    last9 = d[-9:]
    rows = (await session.execute(select(m.Contact).where(
        m.Contact.phone.is_not(None),
        func.right(func.regexp_replace(m.Contact.phone, r"\D", "", "g"), 9) == last9))).scalars().all()
    return rows[0] if len(rows) == 1 else None  # ambiguous = unlinked


async def apply_deal(session: AsyncSession, connector: m.Connector, event: Event, now: datetime) -> None:
    assert event.deal and isinstance(event.contact, DealContact)
    contact = await _match_contact(session, connector, event.contact)
    conv = None
    if contact is not None:
        conv = (await session.execute(
            select(m.Conversation).where(m.Conversation.contact_id == contact.id)
            .order_by(m.Conversation.updated_at.desc()).limit(1))).scalar_one_or_none()
    await session.execute(pg_insert(m.Deal).values(
        id=uuid7(), tenant_id=connector.tenant_id, connector_id=connector.id,
        external_id=event.deal.external_id, contact_id=contact.id if contact else None,
        conversation_id=conv.id if conv else None, status=event.deal.status,
        value=event.deal.value, currency=event.deal.currency, occurred_at=event.occurred_at,
        linked=conv is not None)
        .on_conflict_do_update(  # same deal, new status: update the row, never add one
            index_elements=["tenant_id", "connector_id", "external_id"],
            set_={"status": event.deal.status, "value": event.deal.value,
                  "occurred_at": event.occurred_at, "contact_id": contact.id if contact else None,
                  "conversation_id": conv.id if conv else None, "linked": conv is not None}))
    if conv is not None:
        await record_outcome(session, conversation_id=conv.id, status=event.deal.status,
                             source=f"connector:{connector.id}", evidence_msg_ids=[], now=now)
