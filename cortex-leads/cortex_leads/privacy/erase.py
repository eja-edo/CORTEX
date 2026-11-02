"""Exporting and erasing what the system holds about one customer (DESIGN §6, nhóm C). A customer is a `contact`; their data is every
conversation of that contact.

Erasure here is anonymising in place, not `DELETE`: the app role has no DELETE on these tables (widening that is a bigger risk than the
thing it would buy), and the rows hold no personal data once their words, name, number and platform id are gone, while the counts, the
dates and the foreign keys the rest of the system leans on stay true. The platform id is replaced, so a customer who writes again is a
new contact and starts from nothing. It runs in one transaction: all of it or none of it. What it cannot reach is listed in
`NOT_REACHED` and is said to the person who asks."""
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.errors import CortexError
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m

GONE = "[đã xoá theo yêu cầu]"
NOT_REACHED = [
    "Nhật ký hoạt động (bất biến theo thiết kế; không chứa tên hay lời của khách).",
    "Bản tóm tắt tuần/tháng đã sinh trước đó (chỉ có số liệu gộp).",
    "Bản sao lưu cơ sở dữ liệu đã tạo trước thời điểm xoá.",
]


class EraseBlocked(CortexError):
    """A message to this customer is being sent right now: wait for it to land, then erase."""


async def _contact_of(s: AsyncSession, conversation_id: UUID) -> tuple[m.Contact, list[m.Conversation]]:
    conv = await s.get(m.Conversation, conversation_id)
    if conv is None:
        raise LookupError("conversation")
    contact = await s.get(m.Contact, conv.contact_id)
    convs = list((await s.execute(select(m.Conversation).where(m.Conversation.contact_id == contact.id).order_by(m.Conversation.created_at))).scalars())
    return contact, convs


async def export_customer(s: AsyncSession, conversation_id: UUID) -> dict[str, Any]:
    contact, convs = await _contact_of(s, conversation_id)
    ids = [c.id for c in convs]
    msgs = (await s.execute(select(m.Message).where(m.Message.conversation_id.in_(ids)).order_by(m.Message.occurred_at))).scalars().all()
    drafts = (await s.execute(select(m.Draft).where(m.Draft.conversation_id.in_(ids)).order_by(m.Draft.created_at))).scalars().all()
    facts = (await s.execute(select(m.ContactFact).where(m.ContactFact.contact_id == contact.id).order_by(m.ContactFact.created_at))).scalars().all()
    books = (await s.execute(select(m.Booking).where(m.Booking.contact_id == contact.id).order_by(m.Booking.created_at))).scalars().all()
    return {"contact": {"name": contact.display_name, "phone": contact.phone, "platform_id": contact.external_id, "opted_out": contact.opted_out,
                        "created_at": wire(contact.created_at)},
            "conversations": [{"id": str(c.id), "channel": c.channel_kind, "state": c.state, "created_at": wire(c.created_at)} for c in convs],
            "messages": [{"conversation_id": str(x.conversation_id), "from": x.sender_role, "text": x.text, "at": wire(x.occurred_at)} for x in msgs],
            "drafts": [{"conversation_id": str(d.conversation_id), "status": d.status, "text": d.text, "at": wire(d.created_at)} for d in drafts],
            "facts": [{"kind": f.kind, "value": f.value, "status": f.status} for f in facts],
            "bookings": [{"slot": b.slot_code, "starts_at": wire(b.starts_at), "status": b.status} for b in books]}


async def erase_customer(s: AsyncSession, conversation_id: UUID, now: datetime) -> dict[str, int]:
    """Counts of what was changed (no personal data in them). Raises EraseBlocked while a send is in flight."""
    contact, convs = await _contact_of(s, conversation_id)
    ids = [c.id for c in convs]
    if (await s.execute(select(func.count()).select_from(m.Outbox).where(m.Outbox.conversation_id.in_(ids), m.Outbox.status == "sending"))).scalar_one():
        raise EraseBlocked("a message to this customer is being sent")
    # Platform ids first: they are how the raw events are found, and they are about to be replaced.
    conv_ext = [c.external_id for c in convs]
    n: dict[str, int] = {}

    def done(key: str, result: Any) -> None:
        n[key] = result.rowcount or 0

    # Stop anything that would still reach the customer.
    done("drafts_expired", await s.execute(update(m.Draft).where(m.Draft.conversation_id.in_(ids), m.Draft.status.in_(("proposed", "approved")))
                                           .values(status="expired", decided_at=now)))
    done("outbox_cancelled", await s.execute(update(m.Outbox).where(m.Outbox.conversation_id.in_(ids), m.Outbox.status == "queued")
                                             .values(status="cancelled", reason="ERASED")))
    done("jobs_skipped", await s.execute(update(m.FollowupJob).where(m.FollowupJob.conversation_id.in_(ids), m.FollowupJob.status == "pending")
                                         .values(status="skipped")))
    # The words.
    done("messages", await s.execute(update(m.Message).where(m.Message.conversation_id.in_(ids))
                                     .values(text=GONE, external_id=func.concat("erased:", m.Message.id))))
    done("drafts", await s.execute(update(m.Draft).where(m.Draft.conversation_id.in_(ids)).values(text=GONE, claims=[])))
    draft_ids = select(m.Draft.id).where(m.Draft.conversation_id.in_(ids))
    done("staff_edits", await s.execute(update(m.StaffAction).where(m.StaffAction.draft_id.in_(draft_ids)).values(edited_text=None)))
    done("outbox", await s.execute(update(m.Outbox).where(m.Outbox.conversation_id.in_(ids)).values(text=GONE, source={}, disclosure=None)))
    done("facts", await s.execute(update(m.ContactFact).where(m.ContactFact.contact_id == contact.id)
                                  .values(value={"erased": True}, evidence_msg_ids=[], status="rejected", updated_at=now)))
    payload = m.IngestEvent.payload
    done("raw_events", await s.execute(update(m.IngestEvent).where(
        m.IngestEvent.connector_id == contact.connector_id,
        (payload["conversation"]["external_id"].astext.in_(conv_ext)) | (payload["contact"]["external_id"].astext == contact.external_id))
        .values(payload={"erased": True})))
    # The person: nothing left that names them, nothing may be sent to them, and their next message is a new contact.
    done("conversations", await s.execute(update(m.Conversation).where(m.Conversation.id.in_(ids)).values(
        external_id=func.concat("erased:", m.Conversation.id), last_customer_msg_id=None, next_check_at=None, reply_check_at=None,
        promised_date=None, updated_at=now)))
    contact.display_name, contact.phone, contact.decision_maker, contact.opted_out = None, None, None, True
    contact.external_id = f"erased:{contact.id}"
    await s.flush()
    return n
