"""Chiều ngược về kênh (T2, DESIGN §5.8 `capabilities: [add_tag, add_note]`): mark the conversation on the
platform where staff work ("AI: cần người", "AI: đã đặt lịch"). Not a message to the customer, so it has no
window, no disclosure and no touch; but it is an outward write, so it is a row in the same outbox, delivered by the
same worker to the same signed bridge, and only if the business turned it on:

    connector.outbound = {enabled, url, capabilities: [..., "add_tag", "add_note"],
                          tags: {"handoff": "AI: cần người"}, notes: {"booking": "AI đã giữ chỗ học thử"}}

The text is the business's own fixed string for that event: nothing a customer or a model wrote can reach it."""
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m

EVENTS = ("booking", "handoff", "won", "lost")
KINDS = {"add_tag": "tags", "add_note": "notes"}  # capability -> the connector.outbound map that holds its texts


async def annotate(session: AsyncSession, conv: m.Conversation, event: str, ref: UUID | str, now: datetime) -> int:
    """Queue the tag / note the connector maps to `event`. Returns how many rows were queued (0 = nothing configured)."""
    if event not in EVENTS:
        raise ValueError(f"unknown annotation event {event!r}")
    cn = await session.get(m.Connector, conv.connector_id)
    out: dict[str, Any] = (cn.outbound or {}) if cn else {}
    if cn is None or cn.status != "active" or not (out.get("enabled") and out.get("url")):
        return 0
    queued = 0
    for kind, key in KINDS.items():
        text = (out.get(key) or {}).get(event)
        if not text or kind not in (out.get("capabilities") or []):
            continue
        done = await session.execute(insert(m.Outbox).values(
            id=uuid7(), tenant_id=conv.tenant_id, action_id=uuid5(NAMESPACE_URL, f"{kind}:{conv.id}:{event}:{ref}"),
            conversation_id=conv.id, connector_id=cn.id, kind=kind, actor="system:annotate", text=str(text)[:200],
            source={"event": event}, status="queued", created_at=now).on_conflict_do_nothing())
        queued += done.rowcount
    return queued
