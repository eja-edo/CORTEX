"""Backward-compatible exports for legacy imports.

Use app.services.redis.stt_producer for new code.
"""

from app.services.redis.stt_producer import (  # noqa: F401
    STT_STREAM_KEY,
    STTJobTask,
    RedisSTTProducer,
    enqueue_transcription_job,
)

__all__ = [
    "STT_STREAM_KEY",
    "STTJobTask",
    "RedisSTTProducer",
    "enqueue_transcription_job",
]
