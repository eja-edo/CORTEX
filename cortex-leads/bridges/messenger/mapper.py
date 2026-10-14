"""Messenger `messaging` item -> Event Format v1. `sender.role` rules (R13/R26) are in README; an UNKNOWN echo
app_id counts as staff (a bot taken for staff misses one lead; a person taken for bot ruins H1)."""
import logging
from datetime import UTC, datetime
from typing import Any

log, _warned = logging.getLogger("bridges.messenger"), set[str]()


def sender_role(message: dict[str, Any], own_app_id: str = "", human_apps: frozenset[str] = frozenset(),
                bot_apps: frozenset[str] = frozenset()) -> tuple[str, str | None]:
    if not message.get("is_echo"):
        return "customer", None
    app = str(message.get("app_id") or "")
    if not app:
        return "staff", None
    if app == own_app_id:
        return "bot", "own"
    if app in human_apps | bot_apps:
        return ("staff" if app in human_apps else "bot"), app
    if app not in _warned:
        _warned.add(app)
        log.warning("echo from unknown app_id %s treated as staff; list it in MESSENGER_HUMAN/BOT_APP_IDS", app)
    return "staff", f"unknown:{app}"


def map_messaging(item: dict[str, Any], *, page_id: str, own_app_id: str = "", human_apps: frozenset[str] = frozenset(),
                  bot_apps: frozenset[str] = frozenset()) -> dict[str, Any] | None:
    """None for events that carry no message (delivery, read, postback, empty)."""
    msg = item.get("message")
    if not isinstance(msg, dict) or not msg.get("mid"):
        return None
    text = (msg.get("text") or "").strip() or None
    attachments = [{"type": a.get("type"), "url": (a.get("payload") or {}).get("url")}
                   for a in msg.get("attachments") or []]
    if not text and not attachments:
        return None
    echo = bool(msg.get("is_echo"))
    role, echo_app = sender_role(msg, own_app_id, human_apps, bot_apps)
    psid = str(((item.get("recipient") if echo else item.get("sender")) or {}).get("id") or "")
    if not psid or not item.get("timestamp"):
        return None
    return {
        "type": "message.created",
        "external_id": f"messenger:{page_id}:{msg['mid']}",
        "occurred_at": datetime.fromtimestamp(int(item["timestamp"]) / 1000, UTC).isoformat(),
        "channel": {"kind": "messenger", "account_ref": page_id},
        "conversation": {"external_id": psid},
        "contact": {"external_id": psid},
        "sender": {"role": role},
        "text": text,
        "attachments": attachments,
        "meta": {"echo_app": echo_app} if echo_app else {},
    }
