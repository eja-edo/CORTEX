"""
STT Job Task Model

Backend-native payload for transcription jobs sent to stt_service.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class STTJobTask:
    """Speech-to-text job payload sent through Redis Stream."""

    priority: int = 5
    retry_count: int = 0
    task_id: str = field(default_factory=lambda: f"task_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}")
    created_at: float = field(default_factory=time.time)

    asset_id: Optional[str] = None
    user_id: Optional[str] = None
    source_upload_id: Optional[str] = None

    source_object_key: str = ""
    media_type: str = "video"
    source_type: str = "uploaded_video"
    filename: str = ""
    content_type: Optional[str] = None

    job_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for Redis XADD."""
        return {
            "task_id": self.task_id,
            "priority": str(self.priority),
            "retry_count": str(self.retry_count),
            "created_at": str(self.created_at),
            "asset_id": self.asset_id or "",
            "user_id": self.user_id or "",
            "source_upload_id": self.source_upload_id or "",
            "source_object_key": self.source_object_key,
            "media_type": self.media_type,
            "source_type": self.source_type,
            "filename": self.filename,
            "content_type": self.content_type or "",
            "job_context": json.dumps(self.job_context or {}),
        }
