"""Cortex Action Format v1, outbound half (DESIGN §5.2). Core -> bridge, signed with the same
`ingest.signing.sign` and the connector secret the bridge already holds."""
import json
from datetime import datetime
from typing import Any, Literal

from cortex_leads.channels.policy import WindowState
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.ingest.signing import sign

FORMAT = "cortex.action/1"
# Reasons a bridge may give (DESIGN §5.2). Anything else is stored as REFUSED_OTHER, so the
# supervisor view (which shows `reason`) can never carry free text.
REFUSALS = {"OUTBOUND_DISABLED", "AI_SEND_DISABLED", "WINDOW_CLOSED", "PLATFORM_POLICY",
            "QUIET_HOURS", "RATE_LIMIT", "NOT_SUPPORTED"}


def build_action(row: m.Outbox, conv: m.Conversation, connector: m.Connector,
                 window: WindowState) -> dict[str, Any]:
    out = connector.outbound or {}
    if row.kind != "message":  # a mark on the platform, not a message: no text to the customer, no window, no disclosure
        return {"format": FORMAT, "action_id": str(row.action_id), "type": row.kind,
                "channel": {"kind": conv.channel_kind, "account_ref": out.get("account_ref") or connector.id},
                "conversation": {"external_id": conv.external_id}, "actor": row.actor,
                ("tag" if row.kind == "add_tag" else "note"): row.text, "source": row.source}
    action: dict[str, Any] = {
        "format": FORMAT, "action_id": str(row.action_id), "type": "send_message",
        "channel": {"kind": conv.channel_kind, "account_ref": out.get("account_ref") or connector.id},
        "conversation": {"external_id": conv.external_id}, "actor": row.actor, "text": row.text,
        "window": {"open": window["open"], "basis": window["basis"],
                   "expires_at": wire(window["expires_at"])},
        "source": row.source}
    if row.disclosure:  # mandatory whenever the actor is ai:* (Luật AI 134/2025)
        action["disclosure"] = row.disclosure
    return action


def encode(action: dict[str, Any], secret: bytes, now: datetime) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(action, ensure_ascii=False).encode()
    ts = int(now.timestamp())
    return body, {"X-Cortex-Timestamp": str(ts), "X-Cortex-Signature": sign(secret, ts, body),
                  "Content-Type": "application/json"}


Outcome = tuple[Literal["sent", "refused", "error"], str, str | None]


def parse_result(http_status: int, data: Any) -> Outcome:
    """(kind, reason, external_message_id). `error` reasons: RETRY (may heal) or FATAL."""
    if http_status >= 500 or http_status == 429:
        return "error", "RETRY", None
    if http_status != 200 or not isinstance(data, dict):
        return "error", "FATAL", None
    status = data.get("status")
    if status == "sent":  # a missing id must not turn a delivered message into a retry
        return "sent", "", str(data["external_message_id"]) if data.get("external_message_id") else None
    if status == "refused":
        reason = data.get("reason")
        return "refused", reason if reason in REFUSALS else "REFUSED_OTHER", None
    if status == "error":
        return "error", "RETRY" if data.get("retryable") is True else "FATAL", None
    return "error", "FATAL", None
