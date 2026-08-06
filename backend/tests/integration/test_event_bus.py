"""
Integration tests for Milestone 1.2 — EventBus.

Runs against a real Redis instance (app.config.settings.REDIS_URL, the same
`cortex-redis` docker container used by the running app). Every test uses
event types under the `test.` domain and cleans up its own stream keys +
the shared DLQ stream afterwards, so this never touches real `note.*`/
`schedule.*` streams.
"""

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio

from app.events.event_bus import EventBus, reset_event_bus
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
