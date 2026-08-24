"""DeliveryWorker — drains the `notification_deliveries` outbox.

Same shape as `AttentionBundleWorker` and `StateEvaluator` on purpose: a
background loop on its own thread with its own async engine bound to that
thread's event loop (see StateEvaluator.start's comment for why a shared
engine would be wrong here). Where those two turn *time passing* into an
event, this turns a committed delivery row into an actual message on a
channel outside the browser.

Nothing in here knows what a push or a bot is. It claims rows, hands them
to whichever adapter the registry has for that channel, and writes down
what came back — so adding a channel never means touching this file. That
is the point of the layer.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, or_, select, update

from app.config import settings
from app.database_async import make_async_sessionmaker
from app.models import DeliveryStatus, Notification, NotificationDelivery, UserChannel
from app.services.delivery.base import DeliveryOutcome, DeliveryPayload, DeliveryResult
from app.services.delivery.dispatcher import SKIP_NO_ADAPTER
from app.services.delivery.registry import get_adapter
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _backoff_seconds(attempts: int) -> int:
    """BASE * 2^(attempts-1), so attempt 1 waits BASE. Capped at an hour:
    beyond that the retry is no longer chasing a transient failure, and a
    delivery that old is stale news to the user anyway."""
    exponent = max(attempts - 1, 0)
    return min(settings.DELIVERY_RETRY_BASE_SECONDS * (2**exponent), 3600)


async def _claim_batch(session, limit: int) -> list[UUID]:
    """Atomically move up to `limit` due rows to SENDING and return their ids.

    `FOR UPDATE SKIP LOCKED` inside the subquery is what makes it safe to
    run more than one worker: two sweeps racing take disjoint rows instead
    of both sending the same notification. `attempts` is incremented on
    claim rather than on completion so that a worker crashing mid-send
    still burns an attempt — otherwise a send that reliably kills the
    worker would be retried forever.

    Rows stuck in SENDING past `DELIVERY_STALE_SENDING_SECONDS` are
    reclaimed by the same query: that state means the worker that claimed
    them is gone.
    """
    now = _naive_utcnow()
    stale_before = now - timedelta(seconds=settings.DELIVERY_STALE_SENDING_SECONDS)

    claimable = (
        select(NotificationDelivery.id)
        .where(
            or_(
                and_(
                    NotificationDelivery.status == DeliveryStatus.PENDING,
                    or_(
                        NotificationDelivery.next_attempt_at.is_(None),
                        NotificationDelivery.next_attempt_at <= now,
                    ),
                ),
                and_(
                    NotificationDelivery.status == DeliveryStatus.SENDING,
                    NotificationDelivery.updated_at < stale_before,
                ),
            )
        )
        .order_by(NotificationDelivery.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )

    stmt = (
        update(NotificationDelivery)
        .where(NotificationDelivery.id.in_(claimable.scalar_subquery()))
        .values(
            status=DeliveryStatus.SENDING,
            attempts=NotificationDelivery.attempts + 1,
            updated_at=now,
        )
        .returning(NotificationDelivery.id)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    ids = list(result.scalars().all())
    await session.commit()
    return ids


def _is_expired(delivery: NotificationDelivery, now: datetime) -> bool:
    """Too old to be worth delivering.

    The stop condition for UNAVAILABLE retries, which are otherwise
    unbounded. It is deliberately about *age*, not attempts: "this nudge is
    stale news" is a true statement about the user's experience, whereas
    "we tried five times" is a statement about our infrastructure that the
    user never asked about. It also prevents the failure mode that makes
    unbounded retry dangerous — a bot down overnight coming back and
    flooding someone with yesterday's reminders.
    """
    created = delivery.created_at
    if created is None:  # pragma: no cover — column is NOT NULL
        return False
    return created < now - timedelta(hours=settings.DELIVERY_MAX_AGE_HOURS)


def _apply_result(
    delivery: NotificationDelivery, user_channel: UserChannel | None, result: DeliveryResult
) -> None:
    now = _naive_utcnow()

    if result.outcome is DeliveryOutcome.UNAVAILABLE:
        delivery.last_error = result.error
        if _is_expired(delivery, now):
            delivery.status = DeliveryStatus.FAILED
            delivery.next_attempt_at = None
            return
        # Give back the attempt `_claim_batch` spent. The channel was never
        # reached, so this delivery has not actually been tried — charging
        # it would let an outage exhaust the budget of every queued
        # notification without a single one having been attempted.
        delivery.attempts = max((delivery.attempts or 1) - 1, 0)
        delivery.status = DeliveryStatus.PENDING
        # Fixed short interval rather than exponential: the wait is for a
        # process to come back, not for congestion to clear, and backing off
        # to eight minutes would leave a bot that restarted in two seconds
        # idle for the rest of it.
        delivery.next_attempt_at = now + timedelta(
            seconds=settings.DELIVERY_UNAVAILABLE_RETRY_SECONDS
        )
        return

    if result.outcome is DeliveryOutcome.SENT:
        delivery.status = DeliveryStatus.SENT
        delivery.delivered_at = now
        delivery.last_error = None
        delivery.next_attempt_at = None
        if user_channel is not None:
            user_channel.last_used_at = now
        return

    delivery.last_error = result.error

    if result.outcome is DeliveryOutcome.DEAD_ADDRESS:
        delivery.status = DeliveryStatus.FAILED
        delivery.next_attempt_at = None
        if user_channel is not None:
            # The address is gone, not busy. Leaving the row enabled would
            # mean every future notification queues a delivery that cannot
            # succeed, and the settings page would keep showing a device
            # that will never ring again.
            user_channel.enabled = False
        return

    if result.outcome is DeliveryOutcome.PERMANENT:
        delivery.status = DeliveryStatus.FAILED
        delivery.next_attempt_at = None
        return

    # RETRY
    if (delivery.attempts or 0) >= settings.DELIVERY_MAX_ATTEMPTS:
        delivery.status = DeliveryStatus.FAILED
        delivery.next_attempt_at = None
        return
    delivery.status = DeliveryStatus.PENDING
    delivery.next_attempt_at = now + timedelta(seconds=_backoff_seconds(delivery.attempts or 1))


async def _process_one(session, delivery_id: UUID) -> bool:
    """Returns True if the row ended up SENT. Each delivery gets its own
    transaction: one bad row must not roll back the ones already handled in
    the same sweep."""
    delivery = await session.get(NotificationDelivery, delivery_id)
    if delivery is None:  # pragma: no cover — claimed a moment ago
        return False

    adapter = get_adapter(delivery.channel)
    if adapter is None:
        # The channel lost its adapter between planning and sending (a
        # rollback of a feature, most likely). Not an error and not
        # retryable — record it the same way planning would have.
        delivery.status = DeliveryStatus.SKIPPED
        delivery.skip_reason = SKIP_NO_ADAPTER
        await session.commit()
        return False

    notification = await session.get(Notification, delivery.notification_id)
    if notification is None:
        # The notification was deleted while queued. Nothing to deliver and
        # nothing wrong — the FK is ON DELETE CASCADE, so this only happens
        # in the window between claim and load.
        delivery.status = DeliveryStatus.SKIPPED
        delivery.skip_reason = "notification_gone"
        await session.commit()
        return False

    user_channel = (
        await session.get(UserChannel, delivery.user_channel_id)
        if delivery.user_channel_id is not None
        else None
    )

    try:
        result = await asyncio.wait_for(
            adapter.send(DeliveryPayload.from_notification(notification), user_channel),
            timeout=settings.DELIVERY_SEND_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        result = DeliveryResult.retry(
            f"timeout after {settings.DELIVERY_SEND_TIMEOUT_SECONDS}s"
        )
    except Exception as exc:
        # An adapter raising rather than returning a result is a bug in the
        # adapter, but treating it as retryable is the safer read: a
        # transient library error shouldn't permanently drop a nudge, and
        # DELIVERY_MAX_ATTEMPTS still bounds it.
        logger.exception("Adapter for %s raised while sending delivery %s", delivery.channel, delivery_id)
        result = DeliveryResult.retry(f"{type(exc).__name__}: {exc}")

    _apply_result(delivery, user_channel, result)
    await session.commit()
    return delivery.status is DeliveryStatus.SENT


async def run_sweep(session, limit: int | None = None) -> int:
    """One pass over the outbox. Returns how many deliveries were sent.

    Split out from the loop so tests can drive a sweep directly instead of
    waiting on a poll interval — the same shape `flush_due_bundles` uses.
    """
    batch = limit if limit is not None else settings.DELIVERY_WORKER_BATCH_SIZE
    claimed = await _claim_batch(session, batch)
    sent = 0
    for delivery_id in claimed:
        try:
            if await _process_one(session, delivery_id):
                sent += 1
        except Exception:
            await session.rollback()
            logger.exception("Failed to process delivery %s", delivery_id)
    return sent


class DeliveryWorker:
    """Background worker that drains pending notification deliveries."""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._db_engine = None
        self._session_maker = None

    @property
    def poll_interval_seconds(self) -> int:
        return settings.DELIVERY_WORKER_POLL_SECONDS

    async def start(self):
        self._db_engine, self._session_maker = make_async_sessionmaker()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("DeliveryWorker started with poll interval=%ds", self.poll_interval_seconds)
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("DeliveryWorker: task cancelled during shutdown")
            raise
        finally:
            await self._cleanup()

    async def stop(self):
        self._running = False
        logger.info("DeliveryWorker stopping...")
        if self._task and not self._task.done():
            self._task.cancel()

    async def _cleanup(self):
        if self._db_engine is not None:
            try:
                await self._db_engine.dispose()
            except Exception as exc:
                logger.warning("DeliveryWorker: DB engine dispose failed: %s", exc)
            self._db_engine = None
            self._session_maker = None

    async def _run_loop(self):
        try:
            while self._running:
                try:
                    async with self._session_maker() as db:
                        sent = await run_sweep(db)
                        if sent:
                            logger.info("DeliveryWorker sent %d notification deliver(ies)", sent)
                except Exception as e:
                    logger.exception("Error in delivery worker loop: %s", e)

                await asyncio.sleep(self.poll_interval_seconds)
        except asyncio.CancelledError:
            logger.info("DeliveryWorker: run loop cancelled, exiting cleanly")
            raise
