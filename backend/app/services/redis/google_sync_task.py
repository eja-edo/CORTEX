"""
Google Calendar Sync Task — Redis Stream Task Definition

Represents a task for syncing a Schedule to/from Google Calendar.
Follows the same BaseProducerTask / StreamTaskProtocol pattern as
OCRProcessorTask and LLMProcessorTask.

Stream key  : google:sync:stream
Consumer grp: google-sync-workers
"""

import time
from dataclasses import dataclass, field
from typing import ClassVar, Dict, Optional

from app.services.redis.stream_base import BaseProducerTask
from app.services.redis.redis_producer_service import create_producer_service

GOOGLE_SYNC_STREAM_KEY = "google:sync:stream"
GOOGLE_SYNC_CONSUMER_GROUP = "google-sync-workers"


@dataclass
class GoogleSyncTask(BaseProducerTask):
    """
    Task for syncing a single Schedule to Google Calendar.

    Fields
    ------
    schedule_id : UUID str of the Schedule to sync.
    user_id     : UUID str of the owning user (used to look up CalendarConnection).
    operation   : "UPSERT" | "DELETE"  — mirrors SyncOperation enum values.
    """

    schedule_id: str = ""
    user_id: str = ""
    operation: str = "UPSERT"
    # Set bởi RedisStreamService.read_tasks() / from_stream_message() — không set khi enqueue
    message_id: str = ""

    def to_dict(self) -> Dict[str, str]:
        base = super().to_dict()
        base.update(
            {
                "schedule_id": self.schedule_id,
                "user_id": self.user_id,
                "operation": self.operation,
            }
        )
        return base

    @classmethod
    def from_stream_message(
        cls, message_id: str, data: Dict[bytes, bytes]
    ) -> "GoogleSyncTask":
        """Parse a Redis stream message back into a GoogleSyncTask instance."""

        def _d(val) -> str:
            return val.decode("utf-8") if isinstance(val, bytes) else str(val)

        decoded = {
            (_d(k) if isinstance(k, bytes) else k): _d(v) for k, v in data.items()
        }

        try:
            priority = int(decoded.get("priority", "5"))
        except ValueError:
            priority = 5

        try:
            retry_count = int(decoded.get("retry_count", "0"))
        except ValueError:
            retry_count = 0

        return cls(
            task_id=decoded.get("task_id", ""),
            message_id=message_id,
            priority=priority,
            retry_count=retry_count,
            created_at=float(decoded.get("created_at", time.time())),
            schedule_id=decoded.get("schedule_id", ""),
            user_id=decoded.get("user_id", ""),
            operation=decoded.get("operation", "UPSERT"),
        )


# ---------------------------------------------------------------------------
# Convenience producer singleton + enqueue helper
# ---------------------------------------------------------------------------

class _GoogleSyncProducer:
    """Thin singleton wrapper — keeps one RedisProducerService alive."""

    _instance: ClassVar[Optional["_GoogleSyncProducer"]] = None

    def __init__(self) -> None:
        self._producer = create_producer_service(GoogleSyncTask, GOOGLE_SYNC_STREAM_KEY)

    @classmethod
    def get_instance(cls) -> "_GoogleSyncProducer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def ensure_connected(self) -> None:
        if not self._producer.is_connected:
            await self._producer.connect()

    async def enqueue(self, task: GoogleSyncTask) -> str:
        await self.ensure_connected()
        return await self._producer.enqueue(task)


async def enqueue_google_sync(
    schedule_id: str,
    user_id: str,
    operation: str = "UPSERT",
    priority: int = 5,
) -> str:
    """
    Enqueue a Google Calendar sync task.

    Parameters
    ----------
    schedule_id : UUID str of the Schedule to sync.
    user_id     : UUID str of the owning user.
    operation   : "UPSERT" or "DELETE".
    priority    : Lower = higher priority (default 5 = NORMAL).

    Returns
    -------
    task_id: str  — unique task identifier.
    """
    producer = _GoogleSyncProducer.get_instance()
    task = GoogleSyncTask(
        schedule_id=schedule_id,
        user_id=user_id,
        operation=operation,
        priority=priority,
    )
    return await producer.enqueue(task)