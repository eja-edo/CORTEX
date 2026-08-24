"""Integration tests for the delivery outbox and its worker (bước 0).

Runs against the real dev Postgres on the throwaway isolated account (see
tests/integration/isolated_user.py), because the claim query sweeps *every*
pending delivery row rather than filtering by title the way most tests here
can.

What these are actually protecting:

- that a Notification now leaves a paper trail of where it went, so "the
  user never got told" stops being unanswerable;
- that a claimed row is claimed exactly once, which is the difference
  between one push and two;
- that a dead address turns its channel off instead of retrying forever,
  which is how a delivery table stays readable a month in.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.config import settings
from app.database_async import make_async_sessionmaker
from app.models import (
    AttentionChannel,
    AttentionLevel,
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    UserChannel,
)
from app.services.delivery import registry
from app.services.delivery.base import DeliveryResult
from app.services.delivery_worker import _backoff_seconds, run_sweep
from app.services.notifications import create_notification_async
from app.services.user_channels import register_channel_async
from tests.integration.isolated_user import ensure_isolated_user

TITLE_PREFIX = "[test-delivery] "


class _RecordingAdapter:
    """A Telegram-shaped adapter whose result the test dictates."""

    channel = AttentionChannel.TELEGRAM
    default_min_level = AttentionLevel.RECOMMEND
    inline = False
    requires_verification = False

    def __init__(self, result: DeliveryResult | None = None):
        self.result = result or DeliveryResult.sent()
        self.calls: list = []

    async def send(self, payload, user_channel):
        self.calls.append((payload, user_channel))
        return self.result


@pytest_asyncio.fixture
async def user_id():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
    await engine.dispose()
    return uid


@pytest_asyncio.fixture
async def async_db(user_id):
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        # notification_deliveries cascades from notifications, but the
        # user_channels rows do not — and a leftover enabled channel would
        # silently join the next test's fan-out.
        await db.execute(delete(Notification).where(Notification.user_id == user_id))
        await db.execute(delete(UserChannel).where(UserChannel.user_id == user_id))
        await db.commit()
    await engine.dispose()


@pytest.fixture
def telegram_adapter():
    adapter = _RecordingAdapter()
    original = dict(registry._ADAPTERS)
    registry.register(adapter)
    yield adapter
    registry._ADAPTERS.clear()
    registry._ADAPTERS.update(original)


async def _deliveries(db, notification_id) -> list[NotificationDelivery]:
    stmt = select(NotificationDelivery).where(NotificationDelivery.notification_id == notification_id)
    return list((await db.execute(stmt)).scalars().all())


async def _notify(db, user_id, *, level=AttentionLevel.ASK, suffix="one") -> Notification:
    return await create_notification_async(
        db, user_id=user_id, type="system", title=f"{TITLE_PREFIX}{suffix}",
        body="body", reason_key="task.overdue", attention_level=level,
    )


@pytest.mark.asyncio
async def test_creating_a_notification_writes_an_in_app_delivery(async_db, user_id):
    """The baseline that must not regress: with no registered channels the
    behaviour is exactly what it was before the layer existed, plus a row
    saying so."""
    notification = await _notify(async_db, user_id)

    rows = await _deliveries(async_db, notification.id)

    assert len(rows) == 1
    assert rows[0].channel is AttentionChannel.IN_APP
    assert rows[0].status is DeliveryStatus.SENT
    assert rows[0].delivered_at is not None


@pytest.mark.asyncio
async def test_registered_channel_gets_a_pending_row_not_an_inline_send(
    async_db, user_id, telegram_adapter
):
    """External channels must not be sent from the creating call — that is
    what keeps a slow third party out of the State Evaluator's loop."""
    await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-1",
        min_level=AttentionLevel.INFORM,
    )

    notification = await _notify(async_db, user_id)
    rows = {r.channel: r for r in await _deliveries(async_db, notification.id)}

    assert rows[AttentionChannel.IN_APP].status is DeliveryStatus.SENT
    assert rows[AttentionChannel.TELEGRAM].status is DeliveryStatus.PENDING
    assert telegram_adapter.calls == []


@pytest.mark.asyncio
async def test_worker_sweep_delivers_the_pending_row(async_db, user_id, telegram_adapter):
    channel = await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-2",
        min_level=AttentionLevel.INFORM,
    )
    notification = await _notify(async_db, user_id, suffix="sweep")

    sent = await run_sweep(async_db)

    assert sent >= 1
    rows = {r.channel: r for r in await _deliveries(async_db, notification.id)}
    telegram = rows[AttentionChannel.TELEGRAM]
    assert telegram.status is DeliveryStatus.SENT
    assert telegram.delivered_at is not None
    assert telegram.attempts == 1
    assert len(telegram_adapter.calls) == 1
    # The payload the adapter saw is the notification, not a stub.
    payload, seen_channel = telegram_adapter.calls[0]
    assert payload.title == notification.title
    assert seen_channel.id == channel.id

    await async_db.refresh(channel)
    assert channel.last_used_at is not None


@pytest.mark.asyncio
async def test_a_second_sweep_does_not_resend(async_db, user_id, telegram_adapter):
    """Claiming moves the row out of `pending`; without that, every sweep
    re-sends every delivery ever made."""
    await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-3",
        min_level=AttentionLevel.INFORM,
    )
    await _notify(async_db, user_id, suffix="once")

    await run_sweep(async_db)
    await run_sweep(async_db)

    assert len(telegram_adapter.calls) == 1


@pytest.mark.asyncio
async def test_retryable_failure_backs_off_instead_of_failing(
    async_db, user_id, telegram_adapter
):
    telegram_adapter.result = DeliveryResult.retry("503 from upstream")
    await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-4",
        min_level=AttentionLevel.INFORM,
    )
    notification = await _notify(async_db, user_id, suffix="retry")

    await run_sweep(async_db)

    rows = {r.channel: r for r in await _deliveries(async_db, notification.id)}
    telegram = rows[AttentionChannel.TELEGRAM]
    assert telegram.status is DeliveryStatus.PENDING
    assert telegram.attempts == 1
    assert telegram.last_error == "503 from upstream"
    assert telegram.next_attempt_at is not None
    # And it is not due yet, so the very next sweep leaves it alone.
    await run_sweep(async_db)
    assert len(telegram_adapter.calls) == 1


@pytest.mark.asyncio
async def test_dead_address_disables_the_channel(async_db, user_id, telegram_adapter):
    """A revoked subscription will be revoked forever. Retrying it is how a
    user ends up with a settings page full of devices that never ring."""
    telegram_adapter.result = DeliveryResult.dead_address("bot was blocked by the user")
    channel = await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-5",
        min_level=AttentionLevel.INFORM,
    )
    notification = await _notify(async_db, user_id, suffix="dead")

    await run_sweep(async_db)

    rows = {r.channel: r for r in await _deliveries(async_db, notification.id)}
    assert rows[AttentionChannel.TELEGRAM].status is DeliveryStatus.FAILED

    await async_db.refresh(channel)
    assert channel.enabled is False

    # And a later notification no longer plans a delivery for it at all.
    later = await _notify(async_db, user_id, suffix="after-dead")
    later_rows = await _deliveries(async_db, later.id)
    assert [r.channel for r in later_rows] == [AttentionChannel.IN_APP]


@pytest.mark.asyncio
async def test_below_min_level_never_reaches_the_worker(async_db, user_id, telegram_adapter):
    """The floor is applied at planning time, so a skipped delivery costs
    nothing per sweep forever after."""
    await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-6",
        min_level=AttentionLevel.ASK,
    )
    notification = await _notify(async_db, user_id, level=AttentionLevel.INFORM, suffix="quiet")

    await run_sweep(async_db)

    rows = {r.channel: r for r in await _deliveries(async_db, notification.id)}
    assert rows[AttentionChannel.TELEGRAM].status is DeliveryStatus.SKIPPED
    assert telegram_adapter.calls == []


@pytest.mark.asyncio
async def test_disabled_channel_is_not_planned(async_db, user_id, telegram_adapter):
    from app.services.user_channels import update_channel_async

    channel = await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-7",
        min_level=AttentionLevel.INFORM,
    )
    await update_channel_async(async_db, user_id, channel.id, enabled=False)

    notification = await _notify(async_db, user_id, suffix="off")
    rows = await _deliveries(async_db, notification.id)

    assert [r.channel for r in rows] == [AttentionChannel.IN_APP]


@pytest.mark.asyncio
async def test_reregistering_the_same_address_does_not_duplicate_deliveries(
    async_db, user_id, telegram_adapter
):
    """Browsers re-send their push subscription on every load. One row per
    re-registration would mean one duplicate notification per row."""
    first = await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-8",
        min_level=AttentionLevel.INFORM,
    )
    second = await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-8", label="renamed",
    )

    assert first.id == second.id
    assert second.label == "renamed"
    # ...and the user's own floor survived a re-registration that didn't
    # mention it.
    assert second.min_level is AttentionLevel.INFORM

    notification = await _notify(async_db, user_id, suffix="dedup")
    rows = await _deliveries(async_db, notification.id)
    assert sorted(r.channel.value for r in rows) == ["in_app", "telegram"]


@pytest.mark.asyncio
async def test_stale_sending_row_is_reclaimed(async_db, user_id, telegram_adapter):
    """A worker that dies mid-send leaves a row in `sending`. Without
    reclaim it is stuck there forever and the user simply never hears."""
    await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-9",
        min_level=AttentionLevel.INFORM,
    )
    notification = await _notify(async_db, user_id, suffix="stale")

    rows = await _deliveries(async_db, notification.id)
    telegram = next(r for r in rows if r.channel is AttentionChannel.TELEGRAM)
    telegram.status = DeliveryStatus.SENDING
    telegram.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=settings.DELIVERY_STALE_SENDING_SECONDS + 60
    )
    await async_db.commit()

    await run_sweep(async_db)

    await async_db.refresh(telegram)
    assert telegram.status is DeliveryStatus.SENT
    assert len(telegram_adapter.calls) == 1


def test_backoff_grows_and_is_capped():
    base = settings.DELIVERY_RETRY_BASE_SECONDS
    assert _backoff_seconds(1) == base
    assert _backoff_seconds(2) == base * 2
    assert _backoff_seconds(3) == base * 4
    assert _backoff_seconds(50) == 3600


class _UnavailableAdapter(_RecordingAdapter):
    """Stands in for a bot process that is simply not running."""

    def __init__(self):
        super().__init__(DeliveryResult.unavailable("bot unreachable: connection refused"))


@pytest.mark.asyncio
async def test_unreachable_transport_does_not_burn_attempts(async_db, user_id, telegram_adapter):
    """A bot that is down says nothing about this notification.

    Without this, a deploy lasting longer than the retry window silently
    loses every notification created during it — the failure mode that
    makes "the bot restarted" turn into data loss.
    """
    telegram_adapter.result = DeliveryResult.unavailable("bot unreachable")
    await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-unavail",
        min_level=AttentionLevel.INFORM,
    )
    notification = await _notify(async_db, user_id, suffix="unavail")

    # Far more sweeps than DELIVERY_MAX_ATTEMPTS. If the outage counted as
    # attempts, the row would be FAILED well before this loop ends.
    for _ in range(settings.DELIVERY_MAX_ATTEMPTS + 3):
        rows = await _deliveries(async_db, notification.id)
        row = next(r for r in rows if r.channel is AttentionChannel.TELEGRAM)
        row.next_attempt_at = None  # make it immediately due again
        await async_db.commit()
        await run_sweep(async_db)

    rows = {r.channel: r for r in await _deliveries(async_db, notification.id)}
    telegram = rows[AttentionChannel.TELEGRAM]
    assert telegram.status is DeliveryStatus.PENDING, "must stay queued through an outage"
    assert telegram.attempts == 0, "an unreached channel must not consume the budget"


@pytest.mark.asyncio
async def test_delivery_resumes_once_the_transport_returns(async_db, user_id, telegram_adapter):
    """The point of not failing: the queued nudge still arrives."""
    telegram_adapter.result = DeliveryResult.unavailable("bot unreachable")
    await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-back",
        min_level=AttentionLevel.INFORM,
    )
    notification = await _notify(async_db, user_id, suffix="comeback")

    await run_sweep(async_db)
    rows = await _deliveries(async_db, notification.id)
    row = next(r for r in rows if r.channel is AttentionChannel.TELEGRAM)
    assert row.status is DeliveryStatus.PENDING

    # Bot comes back.
    telegram_adapter.result = DeliveryResult.sent()
    row.next_attempt_at = None
    await async_db.commit()
    await run_sweep(async_db)

    await async_db.refresh(row)
    assert row.status is DeliveryStatus.SENT
    assert len(telegram_adapter.calls) == 2


@pytest.mark.asyncio
async def test_a_stale_delivery_expires_instead_of_retrying_forever(
    async_db, user_id, telegram_adapter
):
    """Age, not attempts, is what finally stops an outage retry.

    Otherwise a bot down overnight comes back and floods the user with
    yesterday's reminders — the reason unbounded retry needs a stop
    condition at all.
    """
    telegram_adapter.result = DeliveryResult.unavailable("bot unreachable")
    await register_channel_async(
        async_db, user_id, channel=AttentionChannel.TELEGRAM, address="chat-stale",
        min_level=AttentionLevel.INFORM,
    )
    notification = await _notify(async_db, user_id, suffix="stale-age")

    rows = await _deliveries(async_db, notification.id)
    row = next(r for r in rows if r.channel is AttentionChannel.TELEGRAM)
    row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=settings.DELIVERY_MAX_AGE_HOURS + 1
    )
    await async_db.commit()

    await run_sweep(async_db)

    await async_db.refresh(row)
    assert row.status is DeliveryStatus.FAILED
