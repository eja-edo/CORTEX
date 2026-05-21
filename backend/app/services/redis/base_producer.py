"""
Generic Redis stream producer base.

Provides shared Redis connection and XADD enqueue behavior for producer tasks.
"""

from typing import Generic, Optional, Protocol, TypeVar

import redis.asyncio as redis

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ProducerTaskProtocol(Protocol):
    """Protocol for tasks that can be produced to a Redis stream."""

    task_id: str

    def to_dict(self) -> dict[str, str]:
        """Serialize task payload for Redis stream fields."""


TTask = TypeVar("TTask", bound=ProducerTaskProtocol)


class RedisStreamProducerBase(Generic[TTask]):
    """Generic base producer for writing tasks to a Redis Stream via XADD."""

    def __init__(self, stream_key: str):
        self._redis: Optional[redis.Redis] = None
        self._stream_key = stream_key

    async def connect(self) -> None:
        """Connect to Redis using backend settings."""
        if self._redis is not None:
            return

        try:
            redis_url = settings.REDIS_URL
            self._redis = redis.from_url(redis_url, decode_responses=False)
            await self._redis.ping()
            logger.info(f"Connected Redis producer at {redis_url} for stream={self._stream_key}")
        except Exception as exc:
            logger.error(f"Failed to connect Redis producer: {exc}")
            raise ConnectionError(f"Redis connection failed: {exc}")

    async def close(self) -> None:
        """Close Redis connection if active."""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
            logger.info(f"Redis producer connection closed for stream={self._stream_key}")

    async def enqueue(self, task: TTask, *, maxlen: int = 100000) -> str:
        """Enqueue a generic task into the configured Redis stream."""
        if self._redis is None:
            await self.connect()

        if self._redis is None:
            raise ConnectionError("Redis connection not available")

        try:
            message_id = await self._redis.xadd(
                self._stream_key,
                task.to_dict(),
                maxlen=maxlen,
                approximate=True,
            )
            message_id_str = message_id.decode() if isinstance(message_id, bytes) else str(message_id)
            logger.info(f"Enqueued task_id={task.task_id} stream={self._stream_key} message_id={message_id_str}")
            return task.task_id
        except Exception as exc:
            logger.error(f"Failed to enqueue task_id={task.task_id}: {exc}")
            raise

    @property
    def stream_key(self) -> str:
        return self._stream_key
