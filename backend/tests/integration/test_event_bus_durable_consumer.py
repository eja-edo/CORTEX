"""
Integration tests for Milestone 1.10 — EventBus durable consumer.

Runs against the real Redis instance. `EventBus._ensure_consumer_groups()` /
`_consume_loop()` / `_reclaim_stale_entries()` all iterate
`app.events.vocabulary.all_event_types()` — the real production event type
list — so every test here monkeypatches that to a single `test.*` type,
same isolation reasoning as workflow_service's
test_listener_picks_up_new_event_type_without_restart: a fresh consumer
group reading from id="0" against a *real* stream (events:note.created,
etc.) would drain whatever backlog the rest of the test suite left there.
"""

import asyncio
import json

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

import app.events.vocabulary as vocabulary_module
from app.config import settings
from app.events.event_bus import EventBus, reset_event_bus
from app.events.schemas import EventEnvelope


def _patch_vocabulary(monkeypatch, event_type: str):
    monkeypatch.setattr(vocabulary_module, "all_event_types", lambda: [event_type])


@pytest_asyncio.fixture
async def two_buses(monkeypatch, request):
    """Two independent EventBus instances simulating two separate
    processes — neither shares the other's in-memory _subscribers or
    _own_published_ids. Both use a unique event type per test run so
    consumer-group backlog from the rest of the suite never interferes."""
    event_type = f"test.durable.{request.node.name}"
    _patch_vocabulary(monkeypatch, event_type)

    bus_a = EventBus()
    await bus_a.connect()
    bus_b = EventBus()
    await bus_b.connect()

    yield bus_a, bus_b, event_type

    await bus_a.stop_consumer()
    await bus_b.stop_consumer()
    async for key in bus_a._redis.scan_iter(f"{EventBus.STREAM_PREFIX}test.durable.*"):
        await bus_a._redis.delete(key)
    await bus_a.disconnect()
    await bus_b.disconnect()
    reset_event_bus()


@pytest.mark.asyncio
async def test_durable_consumer_delivers_event_published_by_another_process(two_buses):
    """Milestone 1.10 M4, case 1: publish from process A (raw XADD, no
    EventBus.publish() involved — mimics a genuinely separate process like
    workflow_service) → a handler subscribed only in process B's EventBus
    instance actually runs, via B's durable consumer."""
    bus_a, bus_b, event_type = two_buses

    received = []

    async def handler(event: EventEnvelope):
        received.append(event.event_id)

    bus_b.subscribe(event_type, handler)
    await bus_b.start_consumer()

    # Simulate process A: a bare XADD with no shared EventBus instance at all.
    event = EventEnvelope(type=event_type, source="process-a", payload={"x": 1})
    await bus_a._redis.xadd(f"events:{event_type}", {"data": json.dumps(event.to_dict())})

    deadline = asyncio.get_event_loop().time() + 5
    while asyncio.get_event_loop().time() < deadline and not received:
        await asyncio.sleep(0.1)

    assert received == [event.event_id]


@pytest.mark.asyncio
async def test_fast_path_and_durable_consumer_dont_double_deliver(two_buses):
    """Milestone 1.10 M1/M2: when the *same* instance both publishes (fast
    path) and runs the durable consumer, a self-published event must only
    be routed once, not twice."""
    bus_a, _bus_b, event_type = two_buses

    received = []

    async def handler(event: EventEnvelope):
        received.append(event.event_id)

    bus_a.subscribe(event_type, handler)
    await bus_a.start_consumer()

    event = EventEnvelope(type=event_type, source="test", payload={})
    await bus_a.publish(event)

    # Fast path already delivered synchronously inside publish(). Give the
    # durable loop a couple of read cycles to (wrongly, if buggy) redeliver.
    await asyncio.sleep(1.5)

    assert received == [event.event_id]


@pytest.mark.asyncio
async def test_reclaims_message_left_pending_by_crashed_consumer(two_buses):
    """Milestone 1.10 M3/M4, case 2: a consumer that dies mid-handler
    (simulated via cancelling its task while the handler is in-flight)
    leaves its message unacked. A fresh EventBus instance's start_consumer()
    must reclaim and reprocess it — no restart-time data loss."""
    bus_a, bus_b, event_type = two_buses

    entered_handler = asyncio.Event()
    release_handler = asyncio.Event()

    async def hanging_handler(event: EventEnvelope):
        entered_handler.set()
        await release_handler.wait()

    bus_a.subscribe(event_type, hanging_handler)
    await bus_a.start_consumer()

    # Raw XADD, not bus_a.publish() — publish()'s fast path would call
    # hanging_handler synchronously inline and hang right here, before the
    # durable-consumer scenario this test targets even begins.
    event = EventEnvelope(type=event_type, source="test", payload={})
    await bus_a._redis.xadd(f"events:{event_type}", {"data": json.dumps(event.to_dict())})

    await asyncio.wait_for(entered_handler.wait(), timeout=5)

    # Kill process A mid-processing: cancel while the handler is still
    # awaiting release_handler, so the message is never acked.
    await bus_a.stop_consumer()

    # Reclaim only kicks in past min_idle_time — 60s in production, far too
    # slow for a test, so shrink it on this instance only.
    bus_b.RECLAIM_MIN_IDLE_MS = 0

    reclaimed = []

    async def recovery_handler(event: EventEnvelope):
        reclaimed.append(event.event_id)

    bus_b.subscribe(event_type, recovery_handler)
    await bus_b.start_consumer()  # runs _reclaim_stale_entries() on startup

    deadline = asyncio.get_event_loop().time() + 5
    while asyncio.get_event_loop().time() < deadline and not reclaimed:
        await asyncio.sleep(0.1)

    assert reclaimed == [event.event_id]
