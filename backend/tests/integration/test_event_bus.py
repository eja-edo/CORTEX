"""
Integration tests for Milestone 1.2 — EventBus.

Runs against a real Redis instance (app.config.settings.REDIS_URL, the same
`cortex-redis` docker container used by the running app). Every test uses
event types under the `test.` domain and cleans up its own stream keys +
the shared DLQ stream afterwards, so this never touches real `note.*`/
`schedule.*` streams.
"""

import asyncio
import threading
from uuid import uuid4

import pytest
import pytest_asyncio

from app.events.event_bus import EventBus, get_event_bus, reset_event_bus
from app.events.schemas import EventEnvelope


@pytest_asyncio.fixture
async def event_bus():
    """Fresh EventBus per test, connected to the real Redis instance."""
    reset_event_bus()
    bus = EventBus()
    await bus.connect()
    yield bus

    # Cleanup: only ever touches test.* streams + the shared DLQ stream.
    async for key in bus._redis.scan_iter(f"{EventBus.STREAM_PREFIX}test.*"):
        await bus._redis.delete(key)
    await bus._redis.delete(EventBus.DLQ_STREAM)
    await bus.disconnect()


@pytest.mark.asyncio
async def test_connect_pings_real_redis(event_bus):
    assert await event_bus._redis.ping() is True


@pytest.mark.asyncio
async def test_publish_event_writes_to_stream(event_bus):
    event = EventEnvelope(type="test.created", source="test", payload={"foo": "bar"})

    event_id = await event_bus.publish(event)
    assert event_id == event.event_id

    entries = await event_bus._redis.xrange("events:test.created")
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_publish_routes_to_in_process_subscriber_immediately(event_bus):
    """publish() must fan out to same-process subscribers without a separate
    consumer loop (the in-process fast path)."""
    received = []

    async def handler(event: EventEnvelope):
        received.append(event.type)

    event_bus.subscribe("test.created", handler)

    await event_bus.publish(EventEnvelope(type="test.created", source="test", payload={}))

    assert received == ["test.created"]


@pytest.mark.asyncio
async def test_subscribe_wildcard(event_bus):
    received = []

    async def handler(event: EventEnvelope):
        received.append(event.type)

    event_bus.subscribe("test.*", handler)

    for event_type in ["test.created", "test.updated", "test.deleted"]:
        await event_bus.publish(EventEnvelope(type=event_type, source="test", payload={}))

    assert received == ["test.created", "test.updated", "test.deleted"]


@pytest.mark.asyncio
async def test_multi_level_wildcard(event_bus):
    received = []

    async def handler(event: EventEnvelope):
        received.append(event.type)

    event_bus.subscribe("*.created", handler)

    await event_bus.publish(EventEnvelope(type="test.created", source="test", payload={}))
    await event_bus.publish(EventEnvelope(type="test.updated", source="test", payload={}))

    assert received == ["test.created"]


@pytest.mark.asyncio
async def test_multiple_subscribers_same_pattern(event_bus):
    received_1, received_2 = [], []

    async def handler_1(event: EventEnvelope):
        received_1.append(event.event_id)

    async def handler_2(event: EventEnvelope):
        received_2.append(event.event_id)

    event_bus.subscribe("test.created", handler_1)
    event_bus.subscribe("test.created", handler_2)

    event = EventEnvelope(type="test.created", source="test", payload={})
    await event_bus.publish(event)

    assert received_1 == [event.event_id]
    assert received_2 == [event.event_id]


@pytest.mark.asyncio
async def test_handler_error_isolation(event_bus):
    """One failing handler must not block others, and must not raise out of publish()."""
    received_good = []

    async def failing_handler(event: EventEnvelope):
        raise ValueError("Intentional failure")

    async def good_handler(event: EventEnvelope):
        received_good.append(event.event_id)

    event_bus.subscribe("test.created", failing_handler)
    event_bus.subscribe("test.created", good_handler)

    # Shrink retry delays so the test doesn't take (1+5+15)s.
    event_bus.RETRY_DELAYS = [0, 0, 0]

    event = EventEnvelope(type="test.created", source="test", payload={})
    await event_bus.publish(event)

    assert received_good == [event.event_id]


@pytest.mark.asyncio
async def test_failed_handler_lands_in_dlq(event_bus):
    async def always_fails(event: EventEnvelope):
        raise RuntimeError("boom")

    event_bus.subscribe("test.created", always_fails)
    event_bus.RETRY_DELAYS = [0, 0, 0]

    event = EventEnvelope(type="test.created", source="test", payload={})
    await event_bus.publish(event)

    dlq_entries = await event_bus._redis.xrange(EventBus.DLQ_STREAM)
    assert len(dlq_entries) == 1

    import json
    dlq_payload = json.loads(dlq_entries[0][1]["data"])
    assert dlq_payload["event_id"] == event.event_id
    assert dlq_payload["dlq_metadata"]["error"] == "boom"
    assert dlq_payload["dlq_metadata"]["retry_count"] == EventBus.MAX_RETRIES


@pytest.mark.asyncio
async def test_unsubscribe(event_bus):
    received = []

    async def handler(event: EventEnvelope):
        received.append(event)

    event_bus.subscribe("test.created", handler)
    await event_bus.publish(EventEnvelope(type="test.created", source="test", payload={}))
    assert len(received) == 1

    event_bus.unsubscribe("test.created", handler)
    await event_bus.publish(EventEnvelope(type="test.created", source="test", payload={}))
    assert len(received) == 1  # unchanged


@pytest.mark.asyncio
async def test_list_subscribers(event_bus):
    async def handler_1(event):
        pass

    async def handler_2(event):
        pass

    event_bus.subscribe("test.*", handler_1)
    event_bus.subscribe("test.created", handler_2)

    subscribers = event_bus.list_subscribers()

    assert subscribers["test.*"] == ["handler_1"]
    assert subscribers["test.created"] == ["handler_2"]


def test_pattern_matching():
    assert EventBus._matches_pattern("test.created", "test.created") is True
    assert EventBus._matches_pattern("test.created", "test.updated") is False

    assert EventBus._matches_pattern("test.*", "test.created") is True
    assert EventBus._matches_pattern("test.*", "test.updated") is True
    assert EventBus._matches_pattern("test.*", "other.created") is False

    assert EventBus._matches_pattern("*.created", "test.created") is True
    assert EventBus._matches_pattern("*.created", "other.created") is True
    assert EventBus._matches_pattern("*.created", "test.updated") is False

    assert EventBus._matches_pattern("*.*", "test.created") is True
    assert EventBus._matches_pattern("*.*.*", "test.created") is False


@pytest.mark.asyncio
async def test_publish_without_connect_raises():
    bus = EventBus()
    with pytest.raises(RuntimeError):
        await bus.publish(EventEnvelope(type="test.created", source="test", payload={}))


@pytest.mark.asyncio
async def test_replay_from_dlq_not_implemented(event_bus):
    with pytest.raises(NotImplementedError):
        await event_bus.replay_from_dlq(str(uuid4()))


# ============================================================================
# get_event_bus() loop affinity
#
# Regression coverage for two related bugs:
#   1. CommitmentFlushWorker (its own thread + event loop, same pattern as
#      ReminderWorker) publishing commitment.created via the plain
#      single-instance singleton silently failed with "attached to a
#      different loop" — the singleton always handed back the *first*
#      loop's Redis connection. get_event_bus() is now loop-aware: a call
#      from a genuinely different running loop gets its own instance.
#   2. Fixing #1 by comparing against a tracked "owner loop" broke every
#      test using the `event_subscriber`-style fixture pattern (assign
#      `event_bus_module._event_bus = bus` directly, bypassing
#      get_event_bus() entirely) — the owner-loop tracker was left unset,
#      so the very next same-loop get_event_bus() call treated "unset" as
#      "some other loop" and silently handed back an unsubscribed bus
#      instead. get_event_bus() now adopts the current loop lazily the
#      first time it's asked, rather than requiring it to have been the
#      one that created _event_bus.
# ============================================================================

@pytest.mark.asyncio
async def test_get_event_bus_returns_directly_assigned_instance_from_same_loop():
    """The exact pattern test fixtures use elsewhere: assign _event_bus
    directly (never via get_event_bus()), then call get_event_bus() from
    the same running loop and expect the same, already-subscribed instance
    back — not a fresh, unsubscribed one."""
    reset_event_bus()
    import app.events.event_bus as event_bus_module

    bus = EventBus()
    await bus.connect()
    event_bus_module._event_bus = bus
    try:
        result = await get_event_bus()
        assert result is bus

        # And a second call from the same loop still returns it too.
        result_again = await get_event_bus()
        assert result_again is bus
    finally:
        event_bus_module._event_bus = None
        await bus.disconnect()
        reset_event_bus()


@pytest.mark.asyncio
async def test_get_event_bus_gives_a_different_loop_its_own_instance():
    """A call from a genuinely different loop (a real OS thread with its own
    asyncio loop, the TaskFlushWorker/ReminderWorker pattern) must not
    reuse the main loop's EventBus — that bus's Redis connection is bound to
    the main loop and using it from another raises "attached to a different
    loop"."""
    reset_event_bus()
    import app.events.event_bus as event_bus_module
    try:
        main_bus = await get_event_bus()

        other_loop_bus: list[EventBus] = []
        other_loop_error: list[BaseException] = []

        def run_in_other_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                bus = loop.run_until_complete(get_event_bus())
                other_loop_bus.append(bus)
                loop.run_until_complete(bus.disconnect())
            except BaseException as exc:  # noqa: BLE001 - surfaced via assertion below
                other_loop_error.append(exc)
            finally:
                loop.close()

        thread = threading.Thread(target=run_in_other_thread)
        thread.start()
        thread.join(timeout=10)

        assert not other_loop_error, f"get_event_bus() failed on other loop: {other_loop_error}"
        assert len(other_loop_bus) == 1
        assert other_loop_bus[0] is not main_bus
    finally:
        for bus in event_bus_module._event_bus_by_loop.values():
            try:
                await bus.disconnect()
            except Exception:
                pass
        if event_bus_module._event_bus is not None:
            await event_bus_module._event_bus.disconnect()
        reset_event_bus()
