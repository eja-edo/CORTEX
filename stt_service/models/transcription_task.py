"""
Transcription Task Model

Defines the task model specifically for transcription processing.
This implements StreamTaskProtocol and can be used with RedisStreamService.
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from models.stream_base import (
    BaseStreamTask,
    parse_priority,
    TaskPriority,
    StreamTaskStatus,
)


@dataclass
class TranscriptionStreamTask(BaseStreamTask):
    """
    Transcription task model for Redis Stream.
    
    Inherits from BaseStreamTask (has task_id, message_id, priority, retry_count).
    Implements StreamTaskProtocol for audio/video transcription processing.
    """
    
    # Backend payload fields
    asset_id: str = ""
    user_id: str = ""
    source_upload_id: str = ""
    source_object_key: str = ""
    media_type: str = "video"
    source_type: str = ""
    filename: str = ""
    content_type: str = ""
    egress_id: str = ""
    job_context: Optional[Dict[str, Any]] = None

    # Transcription-specific fields
    started_at: str = ""
    ended_at: str = ""
    duration: str = ""
    location: str = ""
    source: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    
    # Processing tracking fields
    status: str = StreamTaskStatus.PENDING.value
    started_processing_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for Redis storage."""
        # Get base fields from parent
        data = super().to_dict()
        
        # Add transcription-specific fields
        data.update({
            "asset_id": self.asset_id,
            "user_id": self.user_id,
            "source_upload_id": self.source_upload_id,
            "source_object_key": self.source_object_key,
            "media_type": self.media_type,
            "source_type": self.source_type,
            "filename": self.filename,
            "content_type": self.content_type,
            "egress_id": self.egress_id,
            "job_context": json.dumps(self.job_context or {}),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration": self.duration,
            "location": self.location,
            "source": self.source or "",
            "created_at": str(self.created_at),
            # Tracking fields
            "status": getattr(self.status, "value", self.status),
            "started_processing_at": str(self.started_processing_at) if self.started_processing_at else "",
            "completed_at": str(self.completed_at) if self.completed_at else "",
            "result": self.result or "",
            "error": self.error or "",
        })
        
        return data
    
    @classmethod
    def from_stream_message(
        cls, 
        message_id: str, 
        data: Dict[bytes, bytes]
    ) -> 'TranscriptionStreamTask':
        """Create TranscriptionStreamTask from Redis stream message."""
        # Decode bytes to strings
        decoded = {k.decode(): v.decode() for k, v in data.items()}
        
        # Parse optional float fields
        started_processing_at = decoded.get("started_processing_at")
        started_processing_at = float(started_processing_at) if started_processing_at and started_processing_at != "" else None
        
        completed_at = decoded.get("completed_at")
        completed_at = float(completed_at) if completed_at and completed_at != "" else None
        
        job_context_raw = decoded.get("job_context", "{}")
        try:
            job_context = json.loads(job_context_raw) if job_context_raw else {}
        except json.JSONDecodeError:
            job_context = {}

        return cls(
            task_id=decoded.get("task_id", ""),
            message_id=message_id,
            retry_count=int(decoded.get("retry_count", 0)),
            priority=parse_priority(decoded.get("priority", TaskPriority.NORMAL)),
            asset_id=decoded.get("asset_id", ""),
            user_id=decoded.get("user_id", ""),
            source_upload_id=decoded.get("source_upload_id", ""),
            source_object_key=decoded.get("source_object_key", ""),
            media_type=decoded.get("media_type", "video"),
            source_type=decoded.get("source_type", ""),
            filename=decoded.get("filename", "") or Path(decoded.get("source_object_key", "")).name,
            content_type=decoded.get("content_type", ""),
            egress_id=decoded.get("egress_id", ""),
            job_context=job_context,
            started_at=decoded.get("started_at", ""),
            ended_at=decoded.get("ended_at", ""),
            duration=decoded.get("duration", ""),
            location=decoded.get("location", ""),
            source=decoded.get("source") or None,
            created_at=float(decoded.get("created_at", time.time())),
            # Tracking fields
            status=decoded.get("status", StreamTaskStatus.PENDING.value),
            started_processing_at=started_processing_at,
            completed_at=completed_at,
            result=decoded.get("result") or None,
            error=decoded.get("error") or None,
        )
