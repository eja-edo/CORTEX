"""
LLM Processor Task — Redis Stream Task Definition

Represents a task for LLM (Gemini) processing of OCR frames.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional

import redis.asyncio as redis

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

LLM_PROCESSOR_STREAM_KEY = "llm:processor:stream"


@dataclass
class LLMProcessorTask:
    """Task definition for LLM processing."""

    priority: int = 5
    retry_count: int = 0
    task_id: str = field(
        default_factory=lambda: f"llm_task_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"
    )
    created_at: float = field(default_factory=time.time)

    asset_id: str = ""
    user_id: str = ""
    ocr_job_id: str = ""
    job_context: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "priority": str(self.priority),
            "retry_count": str(self.retry_count),
            "created_at": str(self.created_at),
            "asset_id": self.asset_id,
            "user_id": self.user_id,
            "ocr_job_id": self.ocr_job_id,
            "job_context": json.dumps(self.job_context or {}),
        }


class LLMProcessorProducer:
    """Producer for LLM processor tasks."""

    _instance: ClassVar[Optional["LLMProcessorProducer"]] = None

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._stream_key = LLM_PROCESSOR_STREAM_KEY

    async def connect(self) -> None:
        """Connect to Redis."""
        if self._redis is not None:
            return
        self._redis = redis.from_url(settings.REDIS_URL, decode_responses=False)
        await self._redis.ping()
        logger.info("✅ LLMProcessorProducer connected to Redis")

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def enqueue(self, task: LLMProcessorTask) -> str:
        """
        Enqueue a task to the LLM processor stream.

        Returns:
            Message ID from Redis stream
        """
        if self._redis is None:
            await self.connect()

        task_dict = task.to_dict()
        message_id = await self._redis.xadd(self._stream_key, task_dict)
        logger.info(f"📤 LLM task enqueued: {task.task_id} (msg_id: {message_id})")
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)

    @classmethod
    def get_instance(cls) -> "LLMProcessorProducer":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


async def enqueue_llm_processing(
    asset_id: str,
    user_id: str,
    ocr_job_id: str,
    job_context: Optional[dict] = None,
) -> str:
    """
    Enqueue an LLM processing task.

    Args:
        asset_id: Asset/video ID
        user_id: User ID
        ocr_job_id: OCR job ID from MongoDB
        job_context: Optional context dict

    Returns:
        Redis message ID
    """
    producer = LLMProcessorProducer.get_instance()
    task = LLMProcessorTask(
        asset_id=asset_id,
        user_id=user_id,
        ocr_job_id=ocr_job_id,
        job_context=job_context,
    )
    return await producer.enqueue(task)
