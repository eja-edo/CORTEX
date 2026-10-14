"""Pancake conversation/message -> Cortex Event Format v1 (DESIGN §5.2).

Field names come from https://developer.pancake.biz/openapi/openapi.yaml (Message.from.*).
`sender.role` is the load-bearing field: it drives the silence clock. Rules, first match wins:
  1. from.is_automated or from.ai_generated        -> bot   (stored, never moves the clock)
  2. from.admin_id or from.uid (a Pancake staff)   -> staff (+ staff.external_id)
  3. from.id == page_id (page-side, no admin info) -> bot   (cannot prove a human wrote it; a wrong
                                                            "staff" would hide a dropped lead)
  4. anything else                                 -> customer
"""
from datetime import UTC, datetime
from typing import Any

FORMAT = "cortex.event/1"


def parse_time(value: str) -> datetime:
    """Pancake datetimes are UTC without an offset (spec 'Dates and timezones')."""
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def sender_role(frm: dict[str, Any], page_id: str) -> tuple[str, str | None]:
    if frm.get("is_automated") or frm.get("ai_generated"):
        return "bot", None
    staff_id = frm.get("admin_id") or frm.get("uid")
    if staff_id:
        return "staff", str(staff_id)
    if str(frm.get("id")) == str(page_id):
        return "bot", None
    return "customer", None


def map_message(msg: dict[str, Any], *, page_id: str, conversation_id: str, customer: dict[str, Any],
                channel_kind: str) -> dict[str, Any] | None:
    """Returns None for items that carry nothing to ingest (hidden/removed, empty)."""
    if msg.get("is_removed"):
        return None
    text = (msg.get("original_message") or "").strip() or None
    attachments = [{"type": a.get("type"), "url": a.get("url")}
                   for a in msg.get("attachments") or [] if a.get("type") != "system_message"]
    if not text and not attachments:
        return None
    role, staff_ref = sender_role(msg.get("from") or {}, page_id)
    ev: dict[str, Any] = {
        "type": "message.created",
        "external_id": f"pancake:{page_id}:{msg['id']}",  # stable across polls: dedupe key
        "occurred_at": parse_time(msg["inserted_at"]).isoformat(),
        "channel": {"kind": channel_kind, "account_ref": page_id},
        "conversation": {"external_id": conversation_id},
        "contact": {"external_id": str(customer["id"]),
                    **({"display_name": customer["name"]} if customer.get("name") else {})},
        "sender": {"role": role},
        "text": text,
        "attachments": attachments,
    }
    if staff_ref:
        ev["staff"] = {"external_id": staff_ref}
    return ev
