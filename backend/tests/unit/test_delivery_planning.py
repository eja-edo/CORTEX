"""Unit tests for the delivery fan-out decision (bước 0).

`_plan_rows` is the whole product-relevant part of the layer and it is
pure: given a notification and a user's registered channels, which rows get
written and with what status. No DB, no network, no adapters actually
sending anything — the integration test covers the wiring, this covers the
rule.

The rule that matters most is `min_level`. A delivery layer without an
importance floor would push every INFORM ("bạn có 4 tiếng trống chiều nay")
to a phone, undoing the Attention Gate's five steps at the last inch — so
"INFORM does not reach an ASK-floored channel" is the load-bearing test
here, not the plumbing ones around it.
"""

import pytest

from app.ids import uuid7
from app.models import (
    AttentionChannel,
    AttentionLevel,
    DeliveryStatus,
    Notification,
    UserChannel,
)
from app.services.delivery import registry
from app.services.delivery.base import DeliveryResult
from app.services.delivery.dispatcher import (
    SKIP_BELOW_MIN_LEVEL,
    SKIP_NO_ADAPTER,
    SKIP_UNVERIFIED,
    _plan_rows,
)


class _FakeAdapter:
    """Stand-in for a real external channel — never actually sends."""

    def __init__(self, channel, *, min_level=AttentionLevel.ASK, requires_verification=False):
        self.channel = channel
        self.default_min_level = min_level
        self.inline = False
        self.requires_verification = requires_verification
        self.sent: list = []

    async def send(self, payload, user_channel):
        self.sent.append((payload, user_channel))
        return DeliveryResult.sent()


@pytest.fixture
def fake_telegram():
    """Registers a Telegram adapter for the duration of one test.

    The registry is module-level state by design (it is a build-time fact,
    not per-request), so a test that adds to it must put it back.
    """
    adapter = _FakeAdapter(AttentionChannel.TELEGRAM)
    original = dict(registry._ADAPTERS)
    registry.register(adapter)
    yield adapter
    registry._ADAPTERS.clear()
    registry._ADAPTERS.update(original)


def _notification(level: AttentionLevel | None) -> Notification:
    return Notification(
        id=uuid7(),
        user_id=uuid7(),
        type="system",
        title="test",
        body="test body",
        content=[],
        actions=[],
        payload={},
        attention_level=level,
    )


def _channel(
    user_id,
    channel=AttentionChannel.TELEGRAM,
    *,
    min_level=AttentionLevel.ASK,
    verified=True,
) -> UserChannel:
    return UserChannel(
        id=uuid7(),
        user_id=user_id,
        channel=channel,
        address="chat-123",
        min_level=min_level,
        enabled=True,
        verified_at="2026-08-17T00:00:00" if verified else None,
    )


def test_in_app_is_always_planned_even_with_no_registered_channels():
    """The Notification row *is* the in-app delivery — there is no state in
    which it should be withheld, and no row for a user to revoke."""
    notification = _notification(AttentionLevel.INFORM)

    rows, planned = _plan_rows(notification, [])

    assert len(rows) == 1
    assert planned[0].channel is AttentionChannel.IN_APP
    assert planned[0].user_channel_id is None
    assert planned[0].status is DeliveryStatus.PENDING
    assert planned[0].inline is True


def test_inform_does_not_reach_an_ask_floored_channel(fake_telegram):
    notification = _notification(AttentionLevel.INFORM)
    channel = _channel(notification.user_id, min_level=AttentionLevel.ASK)

    rows, planned = _plan_rows(notification, [channel])

    telegram = next(r for r in rows if r.channel is AttentionChannel.TELEGRAM)
    assert telegram.status is DeliveryStatus.SKIPPED
    assert telegram.skip_reason == SKIP_BELOW_MIN_LEVEL
    # ...and in-app still got it. A floor silences one route, not the item.
    in_app = next(r for r in rows if r.channel is AttentionChannel.IN_APP)
    assert in_app.status is DeliveryStatus.PENDING


def test_ask_clears_an_ask_floored_channel(fake_telegram):
    notification = _notification(AttentionLevel.ASK)
    channel = _channel(notification.user_id, min_level=AttentionLevel.ASK)

    rows, _ = _plan_rows(notification, [channel])

    telegram = next(r for r in rows if r.channel is AttentionChannel.TELEGRAM)
    assert telegram.status is DeliveryStatus.PENDING
    assert telegram.skip_reason is None


def test_act_outranks_an_ask_floor(fake_telegram):
    """The floor is a minimum, not an equality check — the bug this guards
    against silences exactly the most urgent level."""
    notification = _notification(AttentionLevel.ACT)
    channel = _channel(notification.user_id, min_level=AttentionLevel.ASK)

    rows, _ = _plan_rows(notification, [channel])

    telegram = next(r for r in rows if r.channel is AttentionChannel.TELEGRAM)
    assert telegram.status is DeliveryStatus.PENDING


def test_ungated_notification_is_treated_as_inform(fake_telegram):
    """A pass-through notification (no Gate decision, so no level) must not
    be able to reach a phone by *omitting* an importance judgement."""
    notification = _notification(None)
    channel = _channel(notification.user_id, min_level=AttentionLevel.RECOMMEND)

    rows, _ = _plan_rows(notification, [channel])

    telegram = next(r for r in rows if r.channel is AttentionChannel.TELEGRAM)
    assert telegram.status is DeliveryStatus.SKIPPED
    assert telegram.skip_reason == SKIP_BELOW_MIN_LEVEL


def test_channel_with_no_adapter_is_skipped_not_failed():
    """`AttentionChannel` declares channels ahead of their adapters on
    purpose; a row naming one must be a recorded decision, not an error.

    Uses SLACK because it is still adapter-less. This test previously used
    MEZON and started failing the moment that adapter shipped — which is
    the assertion working, not breaking: it pins "declared but not
    implemented", so it has to name a channel that is currently in that
    state."""
    notification = _notification(AttentionLevel.ACT)
    channel = _channel(notification.user_id, channel=AttentionChannel.SLACK, min_level=AttentionLevel.INFORM)

    rows, _ = _plan_rows(notification, [channel])

    slack = next(r for r in rows if r.channel is AttentionChannel.SLACK)
    assert slack.status is DeliveryStatus.SKIPPED
    assert slack.skip_reason == SKIP_NO_ADAPTER


def test_unverified_address_is_skipped_when_the_adapter_requires_proof():
    adapter = _FakeAdapter(
        AttentionChannel.EMAIL, min_level=AttentionLevel.INFORM, requires_verification=True
    )
    original = dict(registry._ADAPTERS)
    registry.register(adapter)
    try:
        notification = _notification(AttentionLevel.ACT)
        channel = _channel(
            notification.user_id, channel=AttentionChannel.EMAIL,
            min_level=AttentionLevel.INFORM, verified=False,
        )

        rows, _ = _plan_rows(notification, [channel])

        email = next(r for r in rows if r.channel is AttentionChannel.EMAIL)
        assert email.status is DeliveryStatus.SKIPPED
        assert email.skip_reason == SKIP_UNVERIFIED
    finally:
        registry._ADAPTERS.clear()
        registry._ADAPTERS.update(original)


def test_external_channels_are_not_inline(fake_telegram):
    """Only in-app runs in the request path; everything that talks to a
    third party waits for the worker, or a slow endpoint stalls the caller."""
    notification = _notification(AttentionLevel.ACT)
    channel = _channel(notification.user_id, min_level=AttentionLevel.INFORM)

    _, planned = _plan_rows(notification, [channel])

    by_channel = {p.channel: p for p in planned}
    assert by_channel[AttentionChannel.IN_APP].inline is True
    assert by_channel[AttentionChannel.TELEGRAM].inline is False


def test_in_app_is_not_registerable():
    """Nothing to register and nothing to revoke — and a `user_channels`
    row for it would produce a duplicate delivery beside the implicit one."""
    assert registry.is_registerable(AttentionChannel.IN_APP) is False
