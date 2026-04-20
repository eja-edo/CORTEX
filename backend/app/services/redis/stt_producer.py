"""
Redis STT producer built on top of the generic Redis stream producer base.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional
from uuid import UUID

from app.services.redis.base_producer import RedisStreamProducerBase

# Must match stt_service.service.redis.redis_transcription_queue_service stream key.
STT_STREAM_KEY = "transcription:stream"


@dataclass
class STTJobTask:
    """Backend-native STT payload sent to the transcription stream."""

    priority: int = 5
    retry_count: int = 0
    task_id: str = field(default_factory=lambda: f"task_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}")
    created_at: float = field(default_factory=time.time)

    asset_id: Optional[str] = None
    egress_id: Optional[str] = None
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    source_upload_id: Optional[str] = None
    source_object_key: str = ""
    media_type: str = "video"
    source_type: str = "uploaded_video"
    filename: str = ""
    content_type: Optional[str] = None
    job_context: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "priority": str(self.priority),
            "retry_count": str(self.retry_count),
            "created_at": str(self.created_at),
            "asset_id": self.asset_id or "",
            "egress_id": self.egress_id or "",
            "workspace_id": self.workspace_id or "",
            "user_id": self.user_id or "",
            "source_upload_id": self.source_upload_id or "",
            "source_object_key": self.source_object_key,
            "media_type": self.media_type,
            "source_type": self.source_type,
            "filename": self.filename,
            "content_type": self.content_type or "",
            "job_context": json.dumps(self.job_context or {}),
        }


class RedisSTTProducer(RedisStreamProducerBase[STTJobTask]):
    """Redis producer for STT transcription jobs."""

    _instance: ClassVar[Optional["RedisSTTProducer"]] = None

    def __init__(self, stream_key: str = STT_STREAM_KEY):
        super().__init__(stream_key=stream_key)

    @classmethod
    def get_instance(cls) -> "RedisSTTProducer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def enqueue_transcription_job(
        self,
        asset_id: Optional[UUID],
        egress_id: Optional[UUID],
        workspace_id: Optional[UUID],
        user_id: Optional[UUID],
        source_object_key: str,
        media_type: str,
        source_type: str,
        filename: str,
        source_upload_id: Optional[UUID] = None,
        content_type: Optional[str] = None,
        job_context: Optional[dict[str, Any]] = None,
        priority: int = 5,
    ) -> str:
        task = STTJobTask(
            asset_id=str(asset_id) if asset_id else None,
            egress_id=str(egress_id) if egress_id else None,
            workspace_id=str(workspace_id) if workspace_id else None,
            user_id=str(user_id) if user_id else None,
            source_upload_id=str(source_upload_id) if source_upload_id else None,
            source_object_key=source_object_key,
            media_type=media_type,
            source_type=source_type,
            filename=filename,
            content_type=content_type,
            job_context=job_context,
            priority=priority,
        )
        return await self.enqueue(task)


async def enqueue_transcription_job(
    asset_id: Optional[UUID],
    egress_id: Optional[UUID],
    workspace_id: Optional[UUID],
    user_id: Optional[UUID],
    source_object_key: str,
    media_type: str = "video",
    source_type: str = "uploaded_video",
    filename: str = "",
    source_upload_id: Optional[UUID] = None,
    content_type: Optional[str] = None,
    job_context: Optional[dict[str, Any]] = None,
    priority: int = 5,
) -> str:
    producer = RedisSTTProducer.get_instance()
    return await producer.enqueue_transcription_job(
        asset_id=asset_id,
        egress_id=egress_id,
        workspace_id=workspace_id,
        user_id=user_id,
        source_object_key=source_object_key,
        media_type=media_type,
        source_type=source_type,
        filename=filename,
        source_upload_id=source_upload_id,
        content_type=content_type,
        job_context=job_context,
        priority=priority,
    )
