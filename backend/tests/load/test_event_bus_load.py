"""
Load tests for Milestone 1.2 — EventBus.

Runs against the real Redis instance. Target: 1000 events, < 100ms average
publish latency (XADD + in-process route_event combined).
"""

import asyncio
import time

import pytest
import pytest_asyncio

from app.events.event_bus import EventBus, reset_event_bus
from app.events.schemas import EventEnvelope


@pytest_asyncio.fixture
async def event_bus():
    reset_event_bus()
    bus = EventBus()
    await bus.connect()
    yield bus

    async for key in bus._redis.scan_iter(f"{EventBus.STREAM_PREFIX}test.*"):
        await bus._redis.delete(key)
    await bus._redis.delete(EventBus.DLQ_STREAM)
    await bus.disconnect()


@pytest.mark.asyncio
async def test_publish_throughput(event_bus):
    """Publish 1000 events, average latency must stay under 100ms."""
    event_count = 1000
    start = time.perf_counter()

    for i in range(event_count):
        await event_bus.publish(
            EventEnvelope(type="test.load", source="load_test", payload={"index": i})
        )

    duration = time.perf_counter() - start
    avg_latency_ms = (duration / event_count) * 1000

    print(f"\nPublish throughput: {event_count / duration:.1f} events/sec")
    print(f"Average latency: {avg_latency_ms:.2f}ms")

    assert avg_latency_ms < 100, f"Latency too high: {avg_latency_ms:.2f}ms"

    entries = await event_bus._redis.xrange("events:test.load")
    assert len(entries) == event_count


@pytest.mark.asyncio
async def test_routing_throughput(event_bus):
    """Route 1000 events to 10 subscribers — no events lost."""
    received_counts = [[] for _ in range(10)]

    def make_handler(idx):
        async def handler(event: EventEnvelope):
            received_counts[idx].append(event.event_id)
        return handler

    for i in range(10):
        event_bus.subscribe("test.*", make_handler(i))

    event_count = 1000
    start = time.perf_counter()

    for i in range(event_count):
        await event_bus.publish(
            EventEnvelope(type="test.load", source="load_test", payload={"index": i})
        )

    duration = time.perf_counter() - start

    for i, received in enumerate(received_counts):
        assert len(received) == event_count, f"Subscriber {i} received {len(received)}/{event_count}"

    print(f"\nRouting throughput: {event_count / duration:.1f} events/sec")
    print(f"Total deliveries: {event_count * 10} (10 subscribers)")


@pytest.mark.asyncio
async def test_concurrent_publishers(event_bus):
    """10 concurrent publishers, 100 events each — no events lost, no races."""
    received = []

    async def subscriber(event: EventEnvelope):
        received.append(event.event_id)

    event_bus.subscribe("test.concurrent", subscriber)

    async def publisher(publisher_id: int):
        for i in range(100):
            await event_bus.publish(
                EventEnvelope(
                    type="test.concurrent",
                    source=f"publisher_{publisher_id}",
                    payload={"index": i},
                )
            )

    await asyncio.gather(*[publisher(i) for i in range(10)])

    assert len(received) == 1000, f"Received {len(received)}/1000 events"
    assert len(set(received)) == 1000, "Duplicate event_ids received"
