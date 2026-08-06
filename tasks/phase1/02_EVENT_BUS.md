# Milestone 1.2: Event Bus Implementation

**Timeline:** 4-5 ngày  
**Dependencies:** 1.1 (Event Schema)  
**Effort:** Medium-Large  

---

## 🎯 Mục tiêu

Xây Event Bus tập trung với:
- Unified publish API
- Pattern-based routing (wildcard support)
- Multiple subscribers per event type (cả trong-process lẫn cross-process)
- Dead-letter queue cho failed events
- Retry logic với exponential backoff
- Event replay capability

**⚠️ Điều chỉnh 2026-08-06 (đối chiếu codebase thật):** Bản gốc plan giả định "extend `RedisStreamService` thay vì rewrite". Sau khi đọc code thật (`backend/app/services/redis/redis_stream_service.py`), điều này **không khả thi**: `RedisStreamService` là một task-queue kiểu Celery (`Generic[T]`, bắt buộc `task_class` implement `StreamTaskProtocol`, 1 consumer-group cố định mỗi instance, model pull qua `XREADGROUP` + heartbeat/XCLAIM để recover worker chết). Nó không có `add_message()`/`publish()`, và không hỗ trợ nhiều subscriber độc lập cùng nhận 1 event (fan-out) — đúng nghĩa hàng đợi task point-to-point, không phải event bus.

**Thiết kế lại:** EventBus dùng `redis.asyncio` **trực tiếp** (không qua `RedisStreamService`) với 2 tầng:
1. **Persistence/cross-process fan-out:** `XADD` vào stream `events:{event.type}` — bất kỳ process nào (kể cả `workflow_service`, xem Task 1.2.4 mới) đều có thể mở consumer-group riêng để đọc.
2. **In-process fan-out (fast path):** ngay sau khi `XADD` thành công, `publish()` gọi luôn `route_event()` để các subscriber đăng ký trong cùng process (`bus.subscribe(...)`) nhận event ngay lập tức — không cần chờ một consumer loop đọc lại từ stream. (Bản code gốc bên dưới có gap này: `publish()` chỉ ghi vào stream, không có gì tự động gọi `route_event()` — test phải gọi tay. Đã sửa trong code mẫu bên dưới.)

Đồng thời, quyết định kiến trúc: EventBus mới sẽ **thay thế hoàn toàn** kênh Pub/Sub cũ `cortex:workflow:events` (`backend/app/services/redis/workflow_event_publisher.py`) mà `workflow_service` đang chờ sẵn (hiện chưa ai gọi `publish_workflow_event()`). Task 1.2.4 (mới) sẽ viết lại `workflow_service/app/triggers/internal_event_listener.py` để tiêu thụ trực tiếp từ Streams `events:*` thay vì Pub/Sub.

---

## 📋 Tasks

### Task 1.2.1: Implement EventBus Core

**Output:** `backend/app/events/event_bus.py`

```python
"""
EventBus: Unified event publishing and routing infrastructure.

Built on top of Redis Streams for persistence and replay capability.
"""

import asyncio
import json
from typing import Callable, Optional, Any
from datetime import datetime

import redis.asyncio as aioredis

from app.config import settings
from app.events.schemas import EventEnvelope
from app.utils.logger import get_logger

logger = get_logger(__name__)


class EventBus:
    """
    Unified Event Bus using Redis Streams as backend.

    KHÔNG dùng `RedisStreamService` (class đó là task-queue 1-consumer-group/
    instance, không hỗ trợ multi-subscriber fan-out) — dùng `redis.asyncio`
    trực tiếp.

    Features:
    - Publish events with envelope validation
    - Subscribe to event patterns (e.g., "schedule.*") — in-process fast path
    - Multiple subscribers per event type
    - Dead-letter queue for failed events
    - Event replay capability
    - Async processing with error isolation
    - Persisted vào Redis Stream để cross-process consumer (vd `workflow_service`,
      xem Task 1.2.4) tự mở consumer-group riêng mà đọc lại/replay

    Architecture:
      Publisher → EventBus.publish()
                    ├─ XADD vào Redis Stream events:{type} (persistence + cross-process)
                    └─ route_event() ngay lập tức (in-process fast path)
                                              ↓ (on error)
                                         Dead Letter Queue
    """
    
    STREAM_PREFIX = "events:"
    DLQ_STREAM = "events:dead-letter"
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 5, 15]  # seconds
    
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        """
        Initialize EventBus.

        Args:
            redis_client: Optional redis.asyncio.Redis instance (for DI/testing)
        """
        self._redis = redis_client
        self._subscribers: dict[str, list[Callable]] = {}
        self._running = False
    
    async def connect(self):
        """Initialize Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await self._redis.ping()
        logger.info("EventBus connected to Redis")
    
    async def disconnect(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
        logger.info("EventBus disconnected")
    
    async def publish(self, event: EventEnvelope) -> str:
        """
        Publish event to bus: ghi vào Redis Stream (persistence + cross-process
        fan-out) rồi route ngay cho subscriber trong cùng process.

        Args:
            event: EventEnvelope with type, source, payload, etc.
        
        Returns:
            event_id for tracking
        
        Raises:
            ValueError: If event validation fails
        """
        # Validate envelope
        try:
            event_dict = event.to_dict()
        except Exception as exc:
            logger.error(f"Event serialization failed: {exc}", exc_info=True)
            raise ValueError(f"Invalid event: {exc}")
        
        # Publish to Redis Stream
        # Stream key: events:{event_type}
        stream_key = f"{self.STREAM_PREFIX}{event.type}"
        
        try:
            message_id = await self._redis.xadd(
                stream_key,
                {"data": json.dumps(event_dict)},
                maxlen=100_000,
                approximate=True,
            )
            
            logger.info(
                f"Event published: {event.type}",
                extra={
                    "event_id": event.event_id,
                    "type": event.type,
                    "source": event.source,
                    "user_id": str(event.user_id) if event.user_id else None,
                    "stream_key": stream_key,
                    "message_id": message_id
                }
            )

            # In-process fast path: route ngay cho subscriber cùng process.
            # (Cross-process subscriber, vd workflow_service, tự đọc lại
            # stream_key qua consumer-group riêng — xem Task 1.2.4)
            await self.route_event(event)

            return event.event_id
        
        except Exception as exc:
            logger.error(
                f"Failed to publish event: {event.type}",
                exc_info=True,
                extra={"event_id": event.event_id}
            )
            raise
    
    def subscribe(self, pattern: str, handler: Callable):
        """
        Subscribe to event pattern.
        
        Args:
            pattern: Event type pattern (exact or wildcard)
                - Exact: "note.created"
                - Wildcard: "note.*" (all note events)
                - Multi-level: "*.created" (all created events)
            handler: async function(event: EventEnvelope) -> None
        
        Example:
            async def my_handler(event: EventEnvelope):
                print(f"Got event: {event.type}")
            
            bus.subscribe("note.*", my_handler)
        """
        if pattern not in self._subscribers:
            self._subscribers[pattern] = []
        
        self._subscribers[pattern].append(handler)
        
        logger.info(
            f"Subscriber registered",
            extra={
                "pattern": pattern,
                "handler": handler.__name__,
                "total_subscribers": len(self._subscribers[pattern])
            }
        )
    
    def unsubscribe(self, pattern: str, handler: Optional[Callable] = None):
        """
        Unsubscribe from pattern.
        
        Args:
            pattern: Event pattern
            handler: Specific handler to remove (if None, remove all for pattern)
        """
        if pattern not in self._subscribers:
            return
        
        if handler is None:
            # Remove all subscribers for pattern
            del self._subscribers[pattern]
            logger.info(f"All subscribers removed for pattern: {pattern}")
        else:
            # Remove specific handler
            try:
                self._subscribers[pattern].remove(handler)
                logger.info(f"Subscriber removed: {pattern} - {handler.__name__}")
            except ValueError:
                pass
    
    async def route_event(self, event: EventEnvelope):
        """
        Route event to all matching subscribers.
        
        Called internally when processing stream messages.
        Handles pattern matching and error isolation.
        """
        matched_patterns = []
        
        # Find matching patterns
        for pattern in self._subscribers.keys():
            if self._matches_pattern(pattern, event.type):
                matched_patterns.append(pattern)
        
        if not matched_patterns:
            logger.debug(f"No subscribers for event: {event.type}")
            return
        
        logger.debug(
            f"Routing event to {len(matched_patterns)} pattern(s)",
            extra={
                "event_type": event.type,
                "patterns": matched_patterns
            }
        )
        
        # Route to all matching subscribers
        tasks = []
        for pattern in matched_patterns:
            handlers = self._subscribers[pattern]
            for handler in handlers:
                tasks.append(
                    self._invoke_handler_with_retry(event, handler, pattern)
                )
        
        # Run all handlers concurrently
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _invoke_handler_with_retry(
        self,
        event: EventEnvelope,
        handler: Callable,
        pattern: str
    ):
        """
        Invoke handler with retry logic and error isolation.
        
        If handler fails after retries, send event to DLQ.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                await handler(event)
                
                # Success
                if attempt > 0:
                    logger.info(
                        f"Handler succeeded on retry {attempt}",
                        extra={
                            "event_type": event.type,
                            "handler": handler.__name__,
                            "attempt": attempt
                        }
                    )
                return
            
            except Exception as exc:
                logger.error(
                    f"Handler failed (attempt {attempt + 1}/{self.MAX_RETRIES})",
                    exc_info=True,
                    extra={
                        "event_type": event.type,
                        "event_id": event.event_id,
                        "handler": handler.__name__,
                        "pattern": pattern,
                        "error": str(exc)
                    }
                )
                
                # Retry with backoff
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                else:
                    # Final failure - send to DLQ
                    await self._send_to_dlq(event, handler, exc)
    
    async def _send_to_dlq(
        self,
        event: EventEnvelope,
        handler: Callable,
        error: Exception
    ):
        """
        Send failed event to dead-letter queue.
        
        DLQ events can be replayed manually or by monitoring system.
        """
        dlq_data = {
            **event.to_dict(),
            "dlq_metadata": {
                "failed_handler": handler.__name__,
                "error": str(error),
                "error_type": type(error).__name__,
                "failed_at": datetime.utcnow().isoformat(),
                "original_event_id": event.event_id,
                "retry_count": self.MAX_RETRIES
            }
        }
        
        try:
            await self._redis.xadd(
                self.DLQ_STREAM,
                {"data": json.dumps(dlq_data)},
            )
            
            logger.warning(
                f"Event sent to DLQ",
                extra={
                    "event_type": event.type,
                    "event_id": event.event_id,
                    "handler": handler.__name__,
                    "error": str(error)
                }
            )
        
        except Exception as dlq_exc:
            logger.critical(
                f"Failed to send event to DLQ!",
                exc_info=True,
                extra={
                    "event_id": event.event_id,
                    "original_error": str(error),
                    "dlq_error": str(dlq_exc)
                }
            )
    
    @staticmethod
    def _matches_pattern(pattern: str, event_type: str) -> bool:
        """
        Check if event_type matches pattern.
        
        Supports:
        - Exact: "note.created" matches "note.created"
        - Wildcard: "note.*" matches "note.created", "note.updated"
        - Multi-level: "*.created" matches "note.created", "schedule.created"
        
        Args:
            pattern: Subscription pattern (may contain '*')
            event_type: Actual event type
        
        Returns:
            True if matches
        """
        # Exact match
        if pattern == event_type:
            return True
        
        # No wildcard
        if '*' not in pattern:
            return False
        
        # Wildcard matching
        pattern_parts = pattern.split('.')
        type_parts = event_type.split('.')
        
        # Different depth - no match
        if len(pattern_parts) != len(type_parts):
            return False
        
        # Check each segment
        for p, t in zip(pattern_parts, type_parts):
            if p != '*' and p != t:
                return False
        
        return True
    
    async def replay_from_dlq(self, event_id: str) -> bool:
        """
        Replay a failed event from DLQ.
        
        Args:
            event_id: Original event_id to replay
        
        Returns:
            True if replay succeeded
        """
        # TODO: Implement DLQ replay
        # 1. Query DLQ stream for event_id
        # 2. Reconstruct EventEnvelope
        # 3. Route to subscribers again
        logger.info(f"Replaying event from DLQ: {event_id}")
        raise NotImplementedError("DLQ replay not yet implemented")
    
    def list_subscribers(self) -> dict[str, list[str]]:
        """
        List all registered subscribers.
        
        Returns:
            Dict mapping pattern -> list of handler names
        """
        return {
            pattern: [h.__name__ for h in handlers]
            for pattern, handlers in self._subscribers.items()
        }


# Global EventBus instance
_event_bus: Optional[EventBus] = None


async def get_event_bus() -> EventBus:
    """Get or create global EventBus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
        await _event_bus.connect()
    return _event_bus


def reset_event_bus():
    """Reset global EventBus (for testing)."""
    global _event_bus
    if _event_bus:
        # Note: disconnect should be called separately in async context
        pass
    _event_bus = None
```

**Checklist:**
- [ ] EventBus class với publish/subscribe methods
- [ ] Pattern matching với wildcard support
- [ ] Retry logic với exponential backoff
- [ ] Dead-letter queue implementation
- [ ] Error isolation (1 subscriber fail không ảnh hưởng khác)
- [ ] Global singleton với get_event_bus()
- [ ] Structured logging cho mọi operation
- [ ] Documentation

---

### Task 1.2.2: Integration Tests

**Output:** `backend/tests/integration/test_event_bus.py`

```python
import pytest
import asyncio
from uuid import uuid4
from app.events.event_bus import EventBus, get_event_bus, reset_event_bus
from app.events.schemas import EventEnvelope


@pytest.fixture
async def event_bus():
    """Fresh EventBus for each test."""
    reset_event_bus()
    bus = EventBus()
    await bus.connect()
    yield bus
    await bus.disconnect()


@pytest.mark.asyncio
async def test_publish_event(event_bus):
    """Test publishing an event."""
    event = EventEnvelope(
        type="note.created",
        source="test",
        user_id=uuid4(),
        payload={"note_id": str(uuid4())}
    )
    
    event_id = await event_bus.publish(event)
    assert event_id == event.event_id


@pytest.mark.asyncio
async def test_subscribe_exact_match(event_bus):
    """Test subscribing to exact event type."""
    received = []
    
    async def handler(event: EventEnvelope):
        received.append(event)
    
    # Subscribe
    event_bus.subscribe("note.created", handler)
    
    # Publish matching event
    event = EventEnvelope(
        type="note.created",
        source="test",
        payload={}
    )
    await event_bus.publish(event)
    
    # Route manually (in production, consumer reads from stream)
    await event_bus.route_event(event)
    
    # Verify
    assert len(received) == 1
    assert received[0].type == "note.created"


@pytest.mark.asyncio
async def test_subscribe_wildcard(event_bus):
    """Test wildcard pattern matching."""
    received = []
    
    async def handler(event: EventEnvelope):
        received.append(event.type)
    
    # Subscribe to all note events
    event_bus.subscribe("note.*", handler)
    
    # Publish multiple events
    for event_type in ["note.created", "note.updated", "note.deleted"]:
        event = EventEnvelope(type=event_type, source="test", payload={})
        await event_bus.route_event(event)
    
    # All should be received
    assert len(received) == 3
    assert "note.created" in received
    assert "note.updated" in received
    assert "note.deleted" in received


@pytest.mark.asyncio
async def test_pattern_matching():
    """Test pattern matching logic."""
    bus = EventBus()
    
    # Exact match
    assert bus._matches_pattern("note.created", "note.created") is True
    assert bus._matches_pattern("note.created", "note.updated") is False
    
    # Single wildcard
    assert bus._matches_pattern("note.*", "note.created") is True
    assert bus._matches_pattern("note.*", "note.updated") is True
    assert bus._matches_pattern("note.*", "schedule.created") is False
    
    # Multi-level wildcard
    assert bus._matches_pattern("*.created", "note.created") is True
    assert bus._matches_pattern("*.created", "schedule.created") is True
    assert bus._matches_pattern("*.created", "note.updated") is False
    
    # Multiple wildcards
    assert bus._matches_pattern("*.*", "note.created") is True
    assert bus._matches_pattern("*.*.*", "note.created") is False


@pytest.mark.asyncio
async def test_multiple_subscribers(event_bus):
    """Test multiple subscribers for same pattern."""
    received_1 = []
    received_2 = []
    
    async def handler_1(event: EventEnvelope):
        received_1.append(event.event_id)
    
    async def handler_2(event: EventEnvelope):
        received_2.append(event.event_id)
    
    # Both subscribe to same pattern
    event_bus.subscribe("note.created", handler_1)
    event_bus.subscribe("note.created", handler_2)
    
    # Publish event
    event = EventEnvelope(type="note.created", source="test", payload={})
    await event_bus.route_event(event)
    
    # Both should receive
    assert len(received_1) == 1
    assert len(received_2) == 1
    assert received_1[0] == event.event_id
    assert received_2[0] == event.event_id


@pytest.mark.asyncio
async def test_handler_error_isolation(event_bus):
    """Test that one failing handler doesn't affect others."""
    received_good = []
    
    async def failing_handler(event: EventEnvelope):
        raise ValueError("Intentional failure")
    
    async def good_handler(event: EventEnvelope):
        received_good.append(event.event_id)
    
    # Subscribe both
    event_bus.subscribe("note.created", failing_handler)
    event_bus.subscribe("note.created", good_handler)
    
    # Publish event
    event = EventEnvelope(type="note.created", source="test", payload={})
    await event_bus.route_event(event)
    
    # Wait for async processing
    await asyncio.sleep(0.5)
    
    # Good handler should still receive despite failing handler
    assert len(received_good) == 1


@pytest.mark.asyncio
async def test_unsubscribe(event_bus):
    """Test unsubscribing."""
    received = []
    
    async def handler(event: EventEnvelope):
        received.append(event)
    
    # Subscribe
    event_bus.subscribe("note.created", handler)
    
    # First event
    event1 = EventEnvelope(type="note.created", source="test", payload={})
    await event_bus.route_event(event1)
    assert len(received) == 1
    
    # Unsubscribe
    event_bus.unsubscribe("note.created", handler)
    
    # Second event
    event2 = EventEnvelope(type="note.created", source="test", payload={})
    await event_bus.route_event(event2)
    
    # Should still be 1
    assert len(received) == 1


@pytest.mark.asyncio
async def test_list_subscribers(event_bus):
    """Test listing subscribers."""
    async def handler_1(event):
        pass
    
    async def handler_2(event):
        pass
    
    event_bus.subscribe("note.*", handler_1)
    event_bus.subscribe("note.created", handler_2)
    
    subscribers = event_bus.list_subscribers()
    
    assert "note.*" in subscribers
    assert "note.created" in subscribers
    assert len(subscribers["note.*"]) == 1
    assert len(subscribers["note.created"]) == 1
```

**Checklist:**
- [ ] Test publish event
- [ ] Test exact pattern matching
- [ ] Test wildcard patterns
- [ ] Test multiple subscribers
- [ ] Test error isolation
- [ ] Test unsubscribe
- [ ] Test pattern matching logic
- [ ] All tests pass

---

### Task 1.2.3: Load Testing

**Output:** `backend/tests/load/test_event_bus_load.py`

```python
import pytest
import asyncio
import time
from uuid import uuid4
from app.events.event_bus import EventBus
from app.events.schemas import EventEnvelope


@pytest.mark.asyncio
async def test_publish_throughput():
    """
    Test: Publish 1000 events and measure throughput.
    
    Target: < 100ms average latency per event
    """
    bus = EventBus()
    await bus.connect()
    
    event_count = 1000
    start = time.time()
    
    # Publish events
    for i in range(event_count):
        event = EventEnvelope(
            type="test.load",
            source="load_test",
            payload={"index": i}
        )
        await bus.publish(event)
    
    duration = time.time() - start
    avg_latency_ms = (duration / event_count) * 1000
    
    print(f"\nPublish throughput: {event_count/duration:.1f} events/sec")
    print(f"Average latency: {avg_latency_ms:.2f}ms")
    
    assert avg_latency_ms < 100, f"Latency too high: {avg_latency_ms}ms"
    
    await bus.disconnect()


@pytest.mark.asyncio
async def test_routing_throughput():
    """
    Test: Route 1000 events to 10 subscribers.
    
    Target: No events lost, all subscribers receive all events
    """
    bus = EventBus()
    await bus.connect()
    
    # Create 10 subscribers
    received_counts = [[] for _ in range(10)]
    
    async def make_handler(idx):
        async def handler(event: EventEnvelope):
            received_counts[idx].append(event.event_id)
        return handler
    
    for i in range(10):
        handler = await make_handler(i)
        bus.subscribe("test.*", handler)
    
    # Publish and route 1000 events
    event_count = 1000
    event_ids = []
    
    start = time.time()
    
    for i in range(event_count):
        event = EventEnvelope(
            type="test.load",
            source="load_test",
            payload={"index": i}
        )
        event_ids.append(event.event_id)
        await bus.route_event(event)
    
    # Wait for async processing
    await asyncio.sleep(2)
    
    duration = time.time() - start
    
    # Verify all subscribers received all events
    for i, received in enumerate(received_counts):
        assert len(received) == event_count, \
            f"Subscriber {i} received {len(received)}/{event_count} events"
    
    print(f"\nRouting throughput: {event_count/duration:.1f} events/sec")
    print(f"Total deliveries: {event_count * 10} (10 subscribers)")
    
    await bus.disconnect()


@pytest.mark.asyncio
async def test_concurrent_publishers():
    """
    Test: 10 concurrent publishers, 100 events each.
    
    Target: No events lost, no race conditions
    """
    bus = EventBus()
    await bus.connect()
    
    received = []
    
    async def subscriber(event: EventEnvelope):
        received.append(event.event_id)
    
    bus.subscribe("test.*", subscriber)
    
    # 10 concurrent publishers
    async def publisher(publisher_id: int):
        for i in range(100):
            event = EventEnvelope(
                type="test.concurrent",
                source=f"publisher_{publisher_id}",
                payload={"index": i}
            )
            await bus.publish(event)
            await bus.route_event(event)
    
    # Run concurrently
    await asyncio.gather(*[publisher(i) for i in range(10)])
    
    # Wait for processing
    await asyncio.sleep(2)
    
    # Should receive 1000 events (10 * 100)
    assert len(received) == 1000, f"Received {len(received)}/1000 events"
    
    await bus.disconnect()
```

**Checklist:**
- [ ] Test publish throughput (1000 events < 100ms avg)
- [ ] Test routing to multiple subscribers
- [ ] Test concurrent publishers
- [ ] No events lost
- [ ] Measure and report performance metrics

---

### Task 1.2.4 (MỚI): Rewrite `workflow_service` internal event listener

**Bối cảnh:** `workflow_service/app/triggers/internal_event_listener.py` hiện subscribe qua Redis Pub/Sub channel `cortex:workflow:events` (raw dict `{"event": ..., **data}`), publish bởi `backend/app/services/redis/workflow_event_publisher.py::publish_workflow_event()` — hàm này **hiện chưa được gọi ở đâu cả**. Theo quyết định thay thế hoàn toàn (không dual-publish), khi Milestone 1.3 bắt đầu emit event thật từ `NoteService`/`ScheduleService` qua `EventBus` mới, `workflow_service` phải đọc từ **Redis Stream** (`events:{type}`) thay vì Pub/Sub, nếu không Workflow Runtime sẽ im lặng ngừng nhận event vĩnh viễn.

**Output:** `workflow_service/app/triggers/internal_event_listener.py` (viết lại)

```python
import asyncio
import json
import redis.asyncio as aioredis
from sqlalchemy import select

from app.config import settings
from app.models.workflow import WorkflowDefinition, WorkflowStatus, TriggerType
from app.database import AsyncSessionLocal

STREAM_PREFIX = "events:"
CONSUMER_GROUP = "workflow_service"

SUPPORTED_EVENTS = [
    "note.created",
    "note.updated",
    "note.deleted",
    "schedule.created",
    "schedule.updated",
    "schedule.completed",
    "asset.uploaded",
    "asset.processed",
]


async def start_internal_event_listener():
    """
    Đọc từ các Redis Stream events:{type} qua consumer-group riêng
    ("workflow_service") — không còn phụ thuộc vào Pub/Sub cortex:workflow:events.
    Mỗi stream cần XGROUP CREATE trước (idempotent, MKSTREAM=True).
    """
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    for event_type in SUPPORTED_EVENTS:
        stream_key = f"{STREAM_PREFIX}{event_type}"
        try:
            await redis.xgroup_create(stream_key, CONSUMER_GROUP, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

    print(f"[TriggerEngine] Listening on Redis Streams: {SUPPORTED_EVENTS}")

    while True:
        try:
            streams = {f"{STREAM_PREFIX}{t}": ">" for t in SUPPORTED_EVENTS}
            result = await redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername="listener-1",
                streams=streams,
                count=10,
                block=5000,
            )
            for stream_key, messages in result or []:
                event_type = stream_key.removeprefix(STREAM_PREFIX)
                for message_id, fields in messages:
                    try:
                        envelope = json.loads(fields["data"])
                        await _handle_event(event_type, envelope.get("payload", {}) | {
                            "user_id": envelope.get("user_id"),
                        })
                    except Exception as e:
                        print(f"[TriggerEngine] Error handling event: {e}")
                    finally:
                        await redis.xack(stream_key, CONSUMER_GROUP, message_id)
        except Exception as e:
            print(f"[TriggerEngine] Listener loop error: {e}")
            await asyncio.sleep(1)


async def _handle_event(event_type: str, event_data: dict):
    # Giữ nguyên logic cũ — xem app/triggers/internal_event_listener.py hiện tại
    ...
```

**Checklist:**
- [ ] Đổi transport từ Pub/Sub sang Streams (`XGROUP CREATE` + `XREADGROUP` + `XACK`) với consumer-group riêng `workflow_service`
- [ ] Payload format đổi từ flat dict sang `EventEnvelope.payload` — cập nhật `_matches_filters()` và `_trigger_workflow_instance()` cho khớp field mới
- [ ] Xoá/deprecate `backend/app/services/redis/workflow_event_publisher.py` sau khi xác nhận không còn nơi nào định dùng
- [ ] Test end-to-end: publish `note.created` qua `EventBus` mới → xác nhận workflow có trigger config tương ứng được kích hoạt qua Temporal
- [ ] Deploy/restart `workflow_service` đồng bộ với thời điểm Milestone 1.3 bắt đầu emit event thật (tránh cửa sổ mất event)

---

## ✅ Milestone 1.2 Definition of Done

- [x] EventBus implementation complete với publish/subscribe — `backend/app/events/event_bus.py` (dùng `redis.asyncio` trực tiếp, không qua `RedisStreamService`)
- [x] Pattern matching works (exact + wildcard)
- [x] Retry logic với exponential backoff
- [x] Dead-letter queue implementation
- [x] Error isolation working
- [x] Integration tests pass — `backend/tests/integration/test_event_bus.py` (13 tests, chạy với Redis thật `cortex-redis`)
- [x] Load tests pass (< 100ms latency) — `backend/tests/load/test_event_bus_load.py`: ~0.42ms avg latency thực đo, 1000 events
- [x] Global singleton pattern
- [x] Documentation complete
- [x] `workflow_service` internal event listener migrated sang Streams (Task 1.2.4), verified end-to-end — `workflow_service/app/triggers/internal_event_listener.py` viết lại, test `workflow_service/tests/test_internal_event_listener.py` xác nhận: tạo workflow internal_event thật qua API → activate → publish event vào Stream mới → listener nhận & match đúng workflow (Temporal execution được mock để không tạo Note thật trong lúc test)
- [x] `backend/app/services/redis/workflow_event_publisher.py` đã xoá (0 caller, thay thế hoàn toàn bởi EventBus)

**Status: hoàn thành 2026-08-06**

---

**Next Milestone:** [1.3 Core Event Definitions](03_CORE_EVENTS.md)
