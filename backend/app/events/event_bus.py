"""
EventBus: Unified event publishing and routing infrastructure.

Built directly on `redis.asyncio` (NOT on `app.services.redis.redis_stream_service
.RedisStreamService` — that class is a single-consumer-group task queue, Generic[T]
over a `StreamTaskProtocol` task class, and does not support the multi-subscriber
fan-out this EventBus needs. See tasks/phase1/02_EVENT_BUS.md for the full
rationale).

Three layers:
  1. Persistence / cross-process fan-out: XADD into Redis Stream `events:{type}`.
     Other processes (e.g. `workflow_service`) can open their own consumer group
     against these streams and replay/consume independently.
  2. In-process fast path: right after XADD, `publish()` calls `route_event()`
     directly so subscribers registered in the same process via `subscribe()`
     get the event immediately, without waiting on a stream-reading loop.
  3. Durable cross-process consumer (Milestone 1.10, `start_consumer()`):
     `subscribe()` on its own only ever fires via layer 2 — same-process,
     same EventBus instance. Before this, nothing in the backend ever read
     the streams back with XREADGROUP, so an event published from another
     process (workflow_service, a future worker) or even from a *different*
     EventBus instance in this same process would XADD successfully and
     then go nowhere: no error, no delivery, just silence. `start_consumer()`
     runs a durable XREADGROUP loop (consumer group `CONSUMER_GROUP`) over
     every event type in the shared vocabulary (app.events.vocabulary,
     Milestone 1.9) and calls the same `route_event()` used by the fast
     path. To avoid double-delivery when the fast path already routed a
     just-published event in the same instance, `publish()` records each
     message_id it fast-routes in `_own_published_ids`; the durable loop
     skips (acks without routing) anything it finds there. Unacked
     messages left behind by a crashed consumer are reclaimed via
     XAUTOCLAIM, both on startup and periodically.
"""

import asyncio
import json
import socket
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable, Optional

import redis.asyncio as aioredis

from app.config import settings
from app.events.schemas import EventEnvelope
from app.utils.logger import get_logger

logger = get_logger(__name__)


class EventBus:
    """
    Unified Event Bus using Redis Streams as the persistence backend.

    Features:
    - Publish events with envelope validation
    - Subscribe to event patterns (e.g., "schedule.*")
    - Multiple subscribers per event type
    - Dead-letter queue for failed events
    - Retry with exponential backoff
    - Error isolation (one failing subscriber never blocks the others)

    Architecture:
      Publisher → EventBus.publish()
                    ├─ XADD events:{type}  (persistence + cross-process fan-out)
                    └─ route_event()        (in-process fast path)
                                              ↓ (on error, after retries)
                                         Dead Letter Queue
    """

    STREAM_PREFIX = "events:"
    DLQ_STREAM = "events:dead-letter"
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 5, 15]  # seconds

    CONSUMER_GROUP = "backend-eventbus"
    OWN_PUBLISHED_IDS_MAXSIZE = 10_000
    RECLAIM_INTERVAL_SECONDS = 60.0
    RECLAIM_MIN_IDLE_MS = 60_000

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        """
        Args:
            redis_client: Optional redis.asyncio.Redis instance (for DI/testing)
        """
        self._redis = redis_client
        self._subscribers: dict[str, list[Callable]] = {}

        # Durable consumer state (Milestone 1.10) — see module docstring.
        self._own_published_ids: "OrderedDict[str, None]" = OrderedDict()
        self._consumer_task: Optional[asyncio.Task] = None
        self._consumer_name: Optional[str] = None
        self._consumer_running = False

    async def connect(self):
        """Initialize Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await self._redis.ping()
        logger.info("EventBus connected to Redis")

    async def disconnect(self):
        """Stop the durable consumer (if running) and close the Redis connection."""
        await self.stop_consumer()
        if self._redis:
            await self._redis.aclose()
        logger.info("EventBus disconnected")

    async def publish(self, event: EventEnvelope) -> str:
        """
        Publish event to the bus: XADD to its stream (persistence + cross-
        process fan-out), then route immediately to in-process subscribers.

        Args:
            event: EventEnvelope with type, source, payload, etc.

        Returns:
            event_id for tracking

        Raises:
            ValueError: If event validation/serialization fails
        """
        if self._redis is None:
            raise RuntimeError("EventBus.connect() must be called before publish()")

        try:
            event_dict = event.to_dict()
        except Exception as exc:
            logger.error(f"Event serialization failed: {exc}", exc_info=True)
            raise ValueError(f"Invalid event: {exc}")

        stream_key = f"{self.STREAM_PREFIX}{event.type}"

        try:
            message_id = await self._redis.xadd(
                stream_key,
                {"data": json.dumps(event_dict)},
                maxlen=100_000,
                approximate=True,
            )
            # Recorded synchronously (no `await` between xadd returning and
            # here) so the durable consumer loop — even running in this same
            # process/instance — can never observe this message_id before
            # it's in the dedup set. See module docstring, layer 3.
            self._remember_own_publish(message_id)

            logger.info(
                f"Event published: {event.type}",
                extra={
                    "event_id": event.event_id,
                    "type": event.type,
                    "source": event.source,
                    "user_id": str(event.user_id) if event.user_id else None,
                    "stream_key": stream_key,
                    "message_id": message_id,
                },
            )
        except Exception:
            logger.error(
                f"Failed to publish event: {event.type}",
                exc_info=True,
                extra={"event_id": event.event_id},
            )
            raise

        # In-process fast path. Cross-process subscribers (e.g. workflow_service)
        # read stream_key independently via their own consumer group.
        await self.route_event(event)

        return event.event_id

    def subscribe(self, pattern: str, handler: Callable):
        """
        Subscribe to an event pattern.

        Args:
            pattern: Event type pattern (exact or wildcard)
                - Exact: "note.created"
                - Wildcard: "note.*" (all note events)
                - Multi-level: "*.created" (all created events)
            handler: async function(event: EventEnvelope) -> None
        """
        self._subscribers.setdefault(pattern, []).append(handler)

        logger.info(
            "Subscriber registered",
            extra={
                "pattern": pattern,
                "handler": getattr(handler, "__name__", repr(handler)),
                "total_subscribers": len(self._subscribers[pattern]),
            },
        )

    def unsubscribe(self, pattern: str, handler: Optional[Callable] = None):
        """
        Unsubscribe from a pattern.

        Args:
            pattern: Event pattern
            handler: Specific handler to remove (if None, remove all for pattern)
        """
        if pattern not in self._subscribers:
            return

        if handler is None:
            del self._subscribers[pattern]
            logger.info(f"All subscribers removed for pattern: {pattern}")
        else:
            try:
                self._subscribers[pattern].remove(handler)
                if not self._subscribers[pattern]:
                    del self._subscribers[pattern]
                logger.info(
                    f"Subscriber removed: {pattern} - "
                    f"{getattr(handler, '__name__', repr(handler))}"
                )
            except ValueError:
                pass

    async def route_event(self, event: EventEnvelope):
        """Route event to all matching subscribers. Handles pattern matching
        and error isolation (each handler retried/DLQ'd independently)."""
        matched_patterns = [
            pattern for pattern in self._subscribers if self._matches_pattern(pattern, event.type)
        ]

        if not matched_patterns:
            logger.debug(f"No subscribers for event: {event.type}")
            return

        logger.debug(
            f"Routing event to {len(matched_patterns)} pattern(s)",
            extra={"event_type": event.type, "patterns": matched_patterns},
        )

        tasks = [
            self._invoke_handler_with_retry(event, handler, pattern)
            for pattern in matched_patterns
            for handler in self._subscribers[pattern]
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _invoke_handler_with_retry(self, event: EventEnvelope, handler: Callable, pattern: str):
        """Invoke handler with retry + exponential backoff. On final failure,
        send the event to the dead-letter queue instead of raising."""
        handler_name = getattr(handler, "__name__", repr(handler))

        for attempt in range(self.MAX_RETRIES):
            try:
                await handler(event)

                if attempt > 0:
                    logger.info(
                        f"Handler succeeded on retry {attempt}",
                        extra={"event_type": event.type, "handler": handler_name, "attempt": attempt},
                    )
                return

            except Exception as exc:
                logger.error(
                    f"Handler failed (attempt {attempt + 1}/{self.MAX_RETRIES})",
                    exc_info=True,
                    extra={
                        "event_type": event.type,
                        "event_id": event.event_id,
                        "handler": handler_name,
                        "pattern": pattern,
                        "error": str(exc),
                    },
                )

                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                else:
                    await self._send_to_dlq(event, handler, exc)

    async def _send_to_dlq(self, event: EventEnvelope, handler: Callable, error: Exception):
        """Send a failed event to the dead-letter queue for later inspection/replay."""
        handler_name = getattr(handler, "__name__", repr(handler))
        dlq_data = {
            **event.to_dict(),
            "dlq_metadata": {
                "failed_handler": handler_name,
                "error": str(error),
                "error_type": type(error).__name__,
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "original_event_id": event.event_id,
                "retry_count": self.MAX_RETRIES,
            },
        }

        try:
            await self._redis.xadd(self.DLQ_STREAM, {"data": json.dumps(dlq_data)})
            logger.warning(
                "Event sent to DLQ",
                extra={
                    "event_type": event.type,
                    "event_id": event.event_id,
                    "handler": handler_name,
                    "error": str(error),
                },
            )
        except Exception as dlq_exc:
            logger.critical(
                "Failed to send event to DLQ!",
                exc_info=True,
                extra={
                    "event_id": event.event_id,
                    "original_error": str(error),
                    "dlq_error": str(dlq_exc),
                },
            )

    @staticmethod
    def _matches_pattern(pattern: str, event_type: str) -> bool:
        """
        Check if event_type matches pattern.

        Supports:
        - Exact: "note.created" matches "note.created"
        - Wildcard: "note.*" matches "note.created", "note.updated"
        - Multi-level: "*.created" matches "note.created", "schedule.created"
        """
        if pattern == event_type:
            return True

        if "*" not in pattern:
            return False

        pattern_parts = pattern.split(".")
        type_parts = event_type.split(".")

        if len(pattern_parts) != len(type_parts):
            return False

        return all(p == "*" or p == t for p, t in zip(pattern_parts, type_parts))

    async def replay_from_dlq(self, event_id: str) -> bool:
        """
        Replay a failed event from the DLQ.

        Not implemented in Phase 1 (out of scope for Milestone 1.2's DoD) —
        DLQ entries can be inspected manually via `XRANGE events:dead-letter`.
        """
        raise NotImplementedError("DLQ replay not yet implemented")

    def list_subscribers(self) -> dict[str, list[str]]:
        """List all registered subscribers, keyed by pattern."""
        return {
            pattern: [getattr(h, "__name__", repr(h)) for h in handlers]
            for pattern, handlers in self._subscribers.items()
        }

    # ------------------------------------------------------------------
    # Durable cross-process consumer (Milestone 1.10)
    # ------------------------------------------------------------------

    def _remember_own_publish(self, message_id: str) -> None:
        """Bounded LRU of message_ids this instance just fast-routed via
        publish(), so the durable consumer loop doesn't route them again."""
        self._own_published_ids[message_id] = None
        if len(self._own_published_ids) > self.OWN_PUBLISHED_IDS_MAXSIZE:
            self._own_published_ids.popitem(last=False)

    async def start_consumer(self, consumer_name: Optional[str] = None) -> None:
        """
        Start the durable XREADGROUP consumer loop as a background task.

        Idempotent — calling this twice on an already-running instance is a
        no-op. Safe to call even if nothing has subscribed yet; subscribers
        registered later still take effect since route_event() reads
        self._subscribers fresh on every call.
        """
        if self._redis is None:
            raise RuntimeError("EventBus.connect() must be called before start_consumer()")
        if self._consumer_task is not None:
            return

        self._consumer_name = consumer_name or f"backend-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        await self._ensure_consumer_groups()
        # Pick up anything a previous (crashed) consumer left pending before
        # we start reading new (">") entries.
        await self._reclaim_stale_entries()

        self._consumer_running = True
        self._consumer_task = asyncio.create_task(self._consume_loop(), name="eventbus-durable-consumer")
        logger.info(f"EventBus durable consumer started: {self._consumer_name}")

    async def stop_consumer(self) -> None:
        """Stop the durable consumer loop. Any message it was mid-processing
        when cancelled stays unacked in the group's pending list, to be
        picked up by _reclaim_stale_entries() on the next start_consumer()."""
        self._consumer_running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
            logger.info("EventBus durable consumer stopped")

    async def _ensure_consumer_groups(self) -> None:
        from app.events.vocabulary import all_event_types

        for event_type in all_event_types():
            stream_key = f"{self.STREAM_PREFIX}{event_type}"
            try:
                await self._redis.xgroup_create(stream_key, self.CONSUMER_GROUP, id="0", mkstream=True)
            except Exception as e:
                if "BUSYGROUP" not in str(e):
                    raise

    async def _consume_loop(self) -> None:
        from app.events.vocabulary import all_event_types

        streams = {f"{self.STREAM_PREFIX}{t}": ">" for t in all_event_types()}
        last_reclaim = asyncio.get_event_loop().time()

        while self._consumer_running:
            now = asyncio.get_event_loop().time()
            if now - last_reclaim >= self.RECLAIM_INTERVAL_SECONDS:
                await self._reclaim_stale_entries()
                last_reclaim = now

            try:
                result = await self._redis.xreadgroup(
                    groupname=self.CONSUMER_GROUP,
                    consumername=self._consumer_name,
                    streams=streams,
                    count=10,
                    block=5000,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"Durable consumer xreadgroup error: {exc}", exc_info=True)
                await asyncio.sleep(1)
                continue

            for stream_key, messages in result or []:
                for message_id, fields in messages:
                    await self._handle_durable_message(stream_key, message_id, fields)

    async def _handle_durable_message(self, stream_key: str, message_id: str, fields: dict) -> None:
        """Route (or skip, if already fast-routed) one message, then ack —
        except on cancellation, where we deliberately leave it unacked so a
        future reclaim pass picks it up (see stop_consumer())."""
        try:
            if message_id in self._own_published_ids:
                self._own_published_ids.pop(message_id, None)
            else:
                event = EventEnvelope.from_dict(json.loads(fields["data"]))
                await self.route_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A poison message (bad JSON, schema mismatch) would otherwise
            # block this stream forever — log and ack past it. Handler-level
            # failures never reach here: route_event() already isolates and
            # retries/DLQs them per-handler.
            logger.error(
                f"Durable consumer failed handling {message_id} from {stream_key}: {exc}",
                exc_info=True,
            )

        try:
            await self._redis.xack(stream_key, self.CONSUMER_GROUP, message_id)
        except Exception:
            logger.error(f"Failed to XACK {message_id} on {stream_key}", exc_info=True)

    async def _reclaim_stale_entries(self) -> None:
        """Claim + reprocess entries left pending by a consumer that died
        mid-processing (this instance on a previous run, or a differently-
        named consumer in the same group) — XAUTOCLAIM, not tied to any
        specific consumer identity, so it works across restarts."""
        from app.events.vocabulary import all_event_types

        for event_type in all_event_types():
            stream_key = f"{self.STREAM_PREFIX}{event_type}"
            cursor = "0-0"
            try:
                while True:
                    claim_result = await self._redis.xautoclaim(
                        stream_key,
                        self.CONSUMER_GROUP,
                        self._consumer_name,
                        min_idle_time=self.RECLAIM_MIN_IDLE_MS,
                        start_id=cursor,
                        count=50,
                    )
                    cursor, claimed = claim_result[0], claim_result[1]
                    for message_id, fields in claimed:
                        logger.warning(
                            f"Reclaimed stale pending message {message_id} on {stream_key}"
                        )
                        await self._handle_durable_message(stream_key, message_id, fields)
                    if not claimed or cursor in ("0-0", 0):
                        break
            except Exception as exc:
                logger.error(f"Reclaim failed for {stream_key}: {exc}", exc_info=True)


# Global EventBus instance
_event_bus: Optional[EventBus] = None


async def get_event_bus() -> EventBus:
    """Get or create the global EventBus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
        await _event_bus.connect()
    return _event_bus


def reset_event_bus():
    """Reset the global EventBus (for testing). Caller is responsible for
    disconnecting the previous instance beforehand if needed."""
    global _event_bus
    _event_bus = None
