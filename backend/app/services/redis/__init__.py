# Standardized Redis services (from stt_service pattern)
from app.services.redis.stream_base import (
    ProducerTaskProtocol,
    StreamTaskProtocol,
    StreamTaskStatus,
    TaskPriority,
    BaseStreamTask,
    BaseProducerTask,
)
from app.services.redis.redis_config import RedisConfig, create_redis_config_from_env
from app.services.redis.redis_stream_service import RedisStreamService, create_stream_service, WorkerInfo
from app.services.redis.redis_producer_service import RedisProducerService, create_producer_service

# Legacy imports (for backward compatibility)
from app.services.redis.base_producer import RedisStreamProducerBase
from app.services.redis.stt_producer import STTJobTask, STT_STREAM_KEY, RedisSTTProducer, enqueue_transcription_job
from app.services.redis.ocr_processor_task import (
    OCRProcessorTask,
    OCR_PROCESSOR_STREAM_KEY,
    OCR_CONSUMER_GROUP,
    OCRProcessorProducer,
    enqueue_video_processing,
)
from app.services.redis.google_sync_task import (
    GoogleSyncTask,
    GOOGLE_SYNC_STREAM_KEY,
    GOOGLE_SYNC_CONSUMER_GROUP,
    enqueue_google_sync,
)

__all__ = [
    # Standardized services
    "ProducerTaskProtocol",
    "StreamTaskProtocol",
    "StreamTaskStatus",
    "TaskPriority",
    "BaseStreamTask",
    "BaseProducerTask",
    "RedisConfig",
    "create_redis_config_from_env",
    "RedisStreamService",
    "create_stream_service",
    "RedisProducerService",
    "create_producer_service",
    "WorkerInfo",
    # Legacy (backward compat)
    "RedisStreamProducerBase",
    "STTJobTask",
    "STT_STREAM_KEY",
    "RedisSTTProducer",
    "enqueue_transcription_job",
    "OCRProcessorTask",
    "OCR_PROCESSOR_STREAM_KEY",
    "OCR_CONSUMER_GROUP",
    "OCRProcessorProducer",
    "enqueue_video_processing",
    # Google Calendar sync
    "GoogleSyncTask",
    "GOOGLE_SYNC_STREAM_KEY",
    "GOOGLE_SYNC_CONSUMER_GROUP",
    "enqueue_google_sync",
]