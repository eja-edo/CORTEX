"""The contract every delivery channel implements.

One file per channel, one registry line, nothing else — that is the
acceptance criterion for this whole layer (bước 0). If adding web push or a
chat bot later requires editing `attention_gate.py`, `notifications.py`, or
`DeliveryWorker`, this abstraction failed and should be fixed rather than
worked around.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.models import AttentionChannel, AttentionLevel, Notification, UserChannel


@dataclass(frozen=True)
class DeliveryPayload:
    """What an adapter is given about the notification itself.

    A snapshot, not the ORM object: adapters run in a background worker,
    after the transaction that created the notification has long since
    closed, and a detached instance lazy-loading a relationship there is a
    failure mode with no good error message. Building this explicitly also
    keeps adapters honest about which fields exist — an adapter cannot
    accidentally depend on something the outbox didn't preserve.
    """

    notification_id: UUID
    user_id: UUID
    type: str
    title: str
    body: str
    content: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    reason_key: str | None = None
    attention_level: AttentionLevel | None = None
    attention_log_id: UUID | None = None

    @classmethod
    def from_notification(cls, notification: Notification) -> "DeliveryPayload":
        return cls(
            notification_id=notification.id,
            user_id=notification.user_id,
            type=notification.type,
            title=notification.title,
            body=notification.body or "",
            content=list(notification.content or []),
            actions=list(notification.actions or []),
            payload=dict(notification.payload or {}),
            reason_key=notification.reason_key,
            attention_level=notification.attention_level,
            attention_log_id=notification.attention_log_id,
        )

    @property
    def effective_level(self) -> AttentionLevel:
        """The level used for `min_level` comparisons.

        `attention_level` is null for pass-through notifications — the ones
        that never went through the Gate because they name no domain item
        (a revoked Google Calendar grant; see attention_gate.py's module
        docstring). Those get INFORM, the lowest speaking level,
        deliberately: a notification with no importance judgement behind it
        must not be able to reach a phone by *omitting* one. Anything that
        wants a push earns a level by going through the Gate.
        """
        return self.attention_level or AttentionLevel.INFORM


class DeliveryOutcome(str, Enum):
    """What happened, and what should happen next.

    Three distinctions, each of which changes what happens next:

    **RETRY vs DEAD_ADDRESS.** A push service returning 503 is worth trying
    again in a minute; a push service saying the subscription is gone will
    say so forever, and retrying it is how a delivery table fills with
    garbage and a user's settings page shows a device that will never work
    again. DEAD_ADDRESS disables the `user_channels` row.

    **RETRY vs UNAVAILABLE.** RETRY means the channel was reached and
    something about *this* delivery went wrong, so it burns an attempt and
    eventually gives up. UNAVAILABLE means the channel could not be reached
    at all — the bot process is restarting, the service is being deployed —
    which says nothing about this delivery and must not consume its budget.
    Without the distinction, a bot down for longer than the retry window
    (~15 minutes at the defaults) silently loses every notification created
    while it was gone, and a routine deploy becomes data loss. UNAVAILABLE
    retries indefinitely; `DELIVERY_MAX_AGE_HOURS` is what eventually stops
    it, on the honest ground that a day-old nudge is no longer worth
    delivering rather than that we ran out of tries.
    """

    SENT = "sent"
    RETRY = "retry"
    UNAVAILABLE = "unavailable"
    PERMANENT = "permanent"
    DEAD_ADDRESS = "dead_address"


@dataclass(frozen=True)
class DeliveryResult:
    outcome: DeliveryOutcome
    error: str | None = None

    @classmethod
    def sent(cls) -> "DeliveryResult":
        return cls(DeliveryOutcome.SENT)

    @classmethod
    def retry(cls, error: str) -> "DeliveryResult":
        return cls(DeliveryOutcome.RETRY, error)

    @classmethod
    def unavailable(cls, error: str) -> "DeliveryResult":
        """The channel's transport is down. Costs no attempt — see the
        outcome docstring."""
        return cls(DeliveryOutcome.UNAVAILABLE, error)

    @classmethod
    def permanent(cls, error: str) -> "DeliveryResult":
        return cls(DeliveryOutcome.PERMANENT, error)

    @classmethod
    def dead_address(cls, error: str) -> "DeliveryResult":
        return cls(DeliveryOutcome.DEAD_ADDRESS, error)


@runtime_checkable
class DeliveryChannelAdapter(Protocol):
    """A route out. Implementations live one-per-file in this package.

    `inline` is the only structural choice an adapter makes. An inline
    adapter runs in-process, in the same call that created the
    notification, and must therefore be fast and non-blocking — in practice
    that means in-app/SSE and nothing else. Everything that talks to a
    third party over the network sets `inline = False` and is executed by
    `DeliveryWorker` from the outbox, which is what gives it retries,
    backoff, and isolation from the request (or worker loop) that triggered
    it.

    `default_min_level` is applied once, when a channel is registered, and
    copied onto the `user_channels` row — not read live. The user must be
    able to lower their own floor and keep it; a default that reasserted
    itself on every delivery would silently overrule them.
    """

    channel: AttentionChannel
    default_min_level: AttentionLevel
    inline: bool
    #: Whether an address needs proving before anything is sent to it. False
    #: for channels where registration is itself proof (a browser handing
    #: over its own push subscription); True for anything a user can simply
    #: type (email, a chat id).
    requires_verification: bool

    async def send(self, payload: DeliveryPayload, user_channel: UserChannel | None) -> DeliveryResult:
        ...
