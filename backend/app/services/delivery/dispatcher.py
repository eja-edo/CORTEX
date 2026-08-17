"""Fan-out: one Notification → N delivery rows, one per applicable channel.

**Why this hangs off `create_notification_*` and not off the Attention
Gate.** The Gate is the single place that decides *whether to speak* (P1),
and that stays true. But it is not the only place a Notification is born:
`attention_bundle.flush_due_bundles` deliberately creates one without
re-entering the Gate (it already *is* the Gate's output for the candidates
it bundles — see that module's docstring). Hanging fan-out on the Gate
would mean the "trong lúc bạn bận có 4 việc" bundle — by definition
produced while the user was not looking at the screen, and so the single
most push-worthy notification the system emits — is the one thing that
never gets pushed. The real single exit point is notification creation, so
that is where the fan-out goes. P2 (detection ≠ delivery) extends by one
notch rather than bending: the Gate decides whether, this decides where.

**Why an outbox instead of just calling the adapter.** The delivery rows
are written in the same transaction as the Notification. Calling a push
service or a bot API directly from here would have to happen either before
the commit — delivering something a rollback then erases — or after it,
losing the delivery if the process dies in the gap. Two of the five
notification call sites run inside background workers that swallow
exceptions and retry the whole loop later, which turns that gap from
theoretical into scheduled. An INSERT beside an INSERT has neither failure
mode, and gives retry state a home. `DeliveryWorker` drains it.

Inline adapters (in-app/SSE) are the exception, executed here rather than
by the worker, and only *after* the commit — the SSE frame tells the
browser to fetch a row that must already be visible to another connection.
That ordering is inherited from the code this replaced and is not
incidental.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import (
    AttentionChannel,
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    UserChannel,
)
from app.ids import uuid7
from app.services.attention_levels import meets_min_level
from app.services.delivery.base import DeliveryPayload
from app.services.delivery.registry import get_adapter
from app.utils.logger import get_logger

logger = get_logger(__name__)

SKIP_NO_ADAPTER = "no_adapter"
SKIP_BELOW_MIN_LEVEL = "below_min_level"
SKIP_UNVERIFIED = "unverified"


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class PlannedDelivery:
    """A planned row, flattened to plain values.

    Returned instead of the ORM objects because the caller commits between
    planning and running the inline half, and reading an attribute off an
    expired instance there would emit a lazy refresh on a session the
    caller may have already handed back.
    """

    delivery_id: UUID
    channel: AttentionChannel
    user_channel_id: UUID | None
    inline: bool
    status: DeliveryStatus


def _channels_stmt(user_id: UUID):
    return select(UserChannel).where(
        UserChannel.user_id == user_id,
        UserChannel.enabled.is_(True),
        # In-app is delivered implicitly to every user, with no row of its
        # own (see NotificationDelivery.user_channel_id). A registered
        # in_app row — which the settings API refuses to create — would
        # otherwise produce a second, duplicate delivery beside it.
        UserChannel.channel != AttentionChannel.IN_APP,
    )


def _plan_rows(
    notification: Notification, user_channels: list[UserChannel]
) -> tuple[list[NotificationDelivery], list[PlannedDelivery]]:
    """Pure planning step: decide one row per candidate channel.

    Shared by both session flavours — the only thing the sync and async
    paths do differently is how they read `user_channels` and how they
    flush, so that is all that is duplicated below.
    """
    payload = DeliveryPayload.from_notification(notification)
    level = payload.effective_level

    rows: list[NotificationDelivery] = []
    planned: list[PlannedDelivery] = []

    candidates: list[tuple[AttentionChannel, UserChannel | None]] = [
        (AttentionChannel.IN_APP, None),
        *((uc.channel, uc) for uc in user_channels),
    ]

    for channel, user_channel in candidates:
        adapter = get_adapter(channel)
        status = DeliveryStatus.PENDING
        skip_reason: str | None = None

        if adapter is None:
            status, skip_reason = DeliveryStatus.SKIPPED, SKIP_NO_ADAPTER
        elif user_channel is not None and adapter.requires_verification and user_channel.verified_at is None:
            status, skip_reason = DeliveryStatus.SKIPPED, SKIP_UNVERIFIED
        elif user_channel is not None and not meets_min_level(level, user_channel.min_level):
            status, skip_reason = DeliveryStatus.SKIPPED, SKIP_BELOW_MIN_LEVEL

        # The id is assigned here rather than left to the column default:
        # that default only fires at flush time, and `PlannedDelivery` has
        # to carry the id back to the caller for the inline pass that runs
        # after the commit. Reading `row.id` before the flush yields None,
        # which turns the later `session.get` into a silent no-op — the
        # delivery would be sent and never marked sent.
        delivery_id = uuid7()
        row = NotificationDelivery(
            id=delivery_id,
            notification_id=notification.id,
            user_id=notification.user_id,
            channel=channel,
            user_channel_id=user_channel.id if user_channel is not None else None,
            status=status,
            skip_reason=skip_reason,
        )
        rows.append(row)
        planned.append(
            PlannedDelivery(
                delivery_id=delivery_id,
                channel=channel,
                user_channel_id=user_channel.id if user_channel is not None else None,
                inline=bool(adapter is not None and adapter.inline),
                status=status,
            )
        )

    return rows, planned


async def plan_deliveries_async(
    session: AsyncSession, notification: Notification
) -> list[PlannedDelivery]:
    """Add one delivery row per applicable channel. **Does not commit** —
    the caller's commit is what makes this atomic with the notification."""
    user_channels = list((await session.execute(_channels_stmt(notification.user_id))).scalars().all())
    rows, planned = _plan_rows(notification, user_channels)
    for row in rows:
        session.add(row)
    await session.flush()
    return planned


def plan_deliveries_sync(session: Session, notification: Notification) -> list[PlannedDelivery]:
    """Sync twin of `plan_deliveries_async`."""
    user_channels = list(session.execute(_channels_stmt(notification.user_id)).scalars().all())
    rows, planned = _plan_rows(notification, user_channels)
    for row in rows:
        session.add(row)
    session.flush()
    return planned


async def run_inline_deliveries_async(
    session: AsyncSession, notification: Notification, planned: list[PlannedDelivery]
) -> None:
    """Execute the inline adapters and record the outcome. Call **after**
    the notification is committed — see the module docstring on ordering.

    Failures are logged, never raised: the notification is already durable
    at this point, and an SSE hiccup must not turn a successful
    `create_notification_*` into an exception for its caller. Everything
    non-inline is left `pending` for `DeliveryWorker`.
    """
    payload = DeliveryPayload.from_notification(notification)
    for item in planned:
        if not item.inline or item.status is not DeliveryStatus.PENDING:
            continue
        adapter = get_adapter(item.channel)
        if adapter is None:  # pragma: no cover — planning already checked
            continue
        try:
            result = await adapter.send(payload, None)
            await _record_inline_outcome_async(session, item.delivery_id, result)
        except Exception:
            logger.exception(
                "Inline delivery failed for notification %s on channel %s",
                notification.id, item.channel,
            )
            await session.rollback()


def run_inline_deliveries_sync(
    session: Session, notification: Notification, planned: list[PlannedDelivery]
) -> None:
    """Sync twin of `run_inline_deliveries_async`."""
    payload = DeliveryPayload.from_notification(notification)
    for item in planned:
        if not item.inline or item.status is not DeliveryStatus.PENDING:
            continue
        adapter = get_adapter(item.channel)
        if adapter is None:  # pragma: no cover — planning already checked
            continue
        send_sync = getattr(adapter, "send_sync", None)
        if send_sync is None:
            # An inline adapter with no sync entry point cannot serve the
            # threadpool callers, and quietly dropping the delivery would
            # be worse than saying so. Leaving the row `pending` also means
            # the worker will still pick it up.
            logger.warning(
                "Inline adapter for %s has no send_sync; leaving delivery %s pending",
                item.channel, item.delivery_id,
            )
            continue
        try:
            result = send_sync(payload, None)
            _record_inline_outcome_sync(session, item.delivery_id, result)
        except Exception:
            logger.exception(
                "Inline delivery failed for notification %s on channel %s",
                notification.id, item.channel,
            )
            session.rollback()


def _apply_inline_outcome(delivery: NotificationDelivery, result) -> None:
    from app.services.delivery.base import DeliveryOutcome

    delivery.attempts = (delivery.attempts or 0) + 1
    if result.outcome is DeliveryOutcome.SENT:
        delivery.status = DeliveryStatus.SENT
        delivery.delivered_at = _naive_utcnow()
    else:
        # Inline channels have no retry path — there is no worker sweep
        # behind them by construction — so anything that isn't SENT is
        # terminal here rather than backed off.
        delivery.status = DeliveryStatus.FAILED
        delivery.last_error = result.error


async def _record_inline_outcome_async(session: AsyncSession, delivery_id: UUID, result) -> None:
    delivery = await session.get(NotificationDelivery, delivery_id)
    if delivery is None:  # pragma: no cover — just written in this session
        return
    _apply_inline_outcome(delivery, result)
    await session.commit()


def _record_inline_outcome_sync(session: Session, delivery_id: UUID, result) -> None:
    delivery = session.get(NotificationDelivery, delivery_id)
    if delivery is None:  # pragma: no cover — just written in this session
        return
    _apply_inline_outcome(delivery, result)
    session.commit()
