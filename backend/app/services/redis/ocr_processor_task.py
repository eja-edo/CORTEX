"""
OCR/Video Processing Task for Redis Stream

Defines task model and producer for video frame OCR processing pipeline.
Standardized to support both ProducerTaskProtocol and StreamTaskProtocol.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional, Dict
from uuid import UUID

from app.services.redis.base_producer import RedisStreamProducerBase
from app.services.redis.stream_base import BaseStreamTask, BaseProducerTask, TaskPriority
from app.services.redis.redis_producer_service import create_producer_service


# Task stream configuration
OCR_PROCESSOR_STREAM_KEY = "ocr:processor:stream"
OCR_CONSUMER_GROUP = "ocr-processor-workers"


@dataclass
class OCRProcessorTask(BaseProducerTask):
    """
    Task for video OCR and layout processing.
    
    Extends BaseProducerTask for producing and implements StreamTaskProtocol
    for consuming (via from_stream_message classmethod).
    """

    # Video processing fields
    video_id: Optional[str] = None
    video_path: str = ""
    output_dir: str = ""
    user_id: Optional[str] = None

    # Processing configuration
    ocr_engine: str = "easyocr"  # paddle, easyocr, tesseract
    target_fps: float = 1.0
    enable_ui_detect: bool = True
    enable_ocr: bool = True

    # OCR-specific params
    easyocr_langs: str = "en,vi"  # comma-separated
    easyocr_confidence: float = 0.3
    use_gpu: bool = True

    # UI detection params
    ui_canny_low: int = 30
    ui_canny_high: int = 100

    # Processing flags
    debug_mode: bool = False
    save_masks: bool = False

    # Context data (job metadata)
    job_context: Optional[Dict[str, Any]] = None
    
    # For consumer side (StreamTaskProtocol) - not set by producer
    message_id: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serialize task to dict for Redis XADD."""
        import json

        base_dict = super().to_dict()
        base_dict.update({
            "video_id": self.video_id or "",
            "video_path": self.video_path,
            "output_dir": self.output_dir,
            "user_id": self.user_id or "",
            "ocr_engine": self.ocr_engine,
            "target_fps": str(self.target_fps),
            "enable_ui_detect": str(self.enable_ui_detect),
            "enable_ocr": str(self.enable_ocr),
            "easyocr_langs": self.easyocr_langs,
            "easyocr_confidence": str(self.easyocr_confidence),
            "use_gpu": str(self.use_gpu),
            "ui_canny_low": str(self.ui_canny_low),
            "ui_canny_high": str(self.ui_canny_high),
            "debug_mode": str(self.debug_mode),
            "save_masks": str(self.save_masks),
            "job_context": json.dumps(self.job_context or {}),
        })
        return base_dict
    
    @classmethod
    def from_stream_message(cls, message_id: str, data: Dict[bytes, bytes]) -> 'OCRProcessorTask':
        """
        Create task instance from Redis stream message.
        
        Required by StreamTaskProtocol for consumer compatibility.
        """
        import json
        
        def decode_bytes(val):
            """Decode bytes to string."""
            if isinstance(val, bytes):
                return val.decode('utf-8')
            return val
        
        def decode_key(key):
            """Decode bytes key to string."""
            if isinstance(key, bytes):
                return key.decode('utf-8')
            return key
        
        # Decode all keys and values
        decoded_data = {decode_key(k): decode_bytes(v) for k, v in data.items()}
        
        # Parse job_context if present
        job_context = None
        if decoded_data.get('job_context'):
            try:
                job_context = json.loads(decoded_data['job_context'])
            except (json.JSONDecodeError, TypeError):
                job_context = {}
        
        # Parse priority
        try:
            priority = int(decoded_data.get('priority', '5'))
        except ValueError:
            priority = 5
        
        # Parse retry count
        try:
            retry_count = int(decoded_data.get('retry_count', '0'))
        except ValueError:
            retry_count = 0
        
        return cls(
            task_id=decoded_data.get('task_id', ''),
            message_id=message_id,
            retry_count=retry_count,
            priority=priority,
            created_at=float(decoded_data.get('created_at', time.time())),
            video_id=decoded_data.get('video_id') or None,
            video_path=decoded_data.get('video_path', ''),
            output_dir=decoded_data.get('output_dir', ''),
            user_id=decoded_data.get('user_id') or None,
            ocr_engine=decoded_data.get('ocr_engine', 'easyocr'),
            target_fps=float(decoded_data.get('target_fps', '1.0')),
            enable_ui_detect=decoded_data.get('enable_ui_detect', 'True').lower() == 'true',
            enable_ocr=decoded_data.get('enable_ocr', 'True').lower() == 'true',
            easyocr_langs=decoded_data.get('easyocr_langs', 'en,vi'),
            easyocr_confidence=float(decoded_data.get('easyocr_confidence', '0.3')),
            use_gpu=decoded_data.get('use_gpu', 'True').lower() == 'true',
            ui_canny_low=int(decoded_data.get('ui_canny_low', '30')),
            ui_canny_high=int(decoded_data.get('ui_canny_high', '100')),
            debug_mode=decoded_data.get('debug_mode', 'False').lower() == 'true',
            save_masks=decoded_data.get('save_masks', 'False').lower() == 'true',
            job_context=job_context,
        )


class OCRProcessorProducer(RedisStreamProducerBase[OCRProcessorTask]):
    """Redis producer for OCR processing tasks."""

    _instance: ClassVar[Optional["OCRProcessorProducer"]] = None

    def __init__(self, stream_key: str = OCR_PROCESSOR_STREAM_KEY):
        super().__init__(stream_key=stream_key)

    @classmethod
    def get_instance(cls) -> "OCRProcessorProducer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def enqueue_video_processing(
        self,
        video_path: str,
        output_dir: str,
        video_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        ocr_engine: str = "easyocr",
        target_fps: float = 1.0,
        enable_ui_detect: bool = True,
        enable_ocr: bool = True,
        easyocr_langs: str = "en,vi",
        easyocr_confidence: float = 0.3,
        use_gpu: bool = True,
        ui_canny_low: int = 30,
        ui_canny_high: int = 100,
        debug_mode: bool = False,
        save_masks: bool = False,
        job_context: Optional[dict] = None,
        priority: int = 5,
    ) -> str:
        """Enqueue a video for OCR processing."""

        task = OCRProcessorTask(
            video_id=str(video_id) if video_id else None,
            video_path=video_path,
            output_dir=output_dir,
            user_id=str(user_id) if user_id else None,
            ocr_engine=ocr_engine,
            target_fps=target_fps,
            enable_ui_detect=enable_ui_detect,
            enable_ocr=enable_ocr,
            easyocr_langs=easyocr_langs,
            easyocr_confidence=easyocr_confidence,
            use_gpu=use_gpu,
            ui_canny_low=ui_canny_low,
            ui_canny_high=ui_canny_high,
            debug_mode=debug_mode,
            save_masks=save_masks,
            job_context=job_context,
            priority=priority,
        )

        return await self.enqueue(task)


# Convenience function for enqueueing
async def enqueue_video_processing(
    video_path: str,
    output_dir: str,
    video_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    ocr_engine: str = "easyocr",
    target_fps: float = 1.0,
    enable_ui_detect: bool = True,
    enable_ocr: bool = True,
    easyocr_langs: str = "en,vi",
    easyocr_confidence: float = 0.3,
    use_gpu: bool = True,
    ui_canny_low: int = 30,
    ui_canny_high: int = 100,
    debug_mode: bool = False,
    save_masks: bool = False,
    job_context: Optional[dict] = None,
    priority: int = 5,
) -> str:
    """Convenience function to enqueue video processing task."""
    producer = OCRProcessorProducer.get_instance()
    return await producer.enqueue_video_processing(
        video_path=video_path,
        output_dir=output_dir,
        video_id=video_id,
        user_id=user_id,
        ocr_engine=ocr_engine,
        target_fps=target_fps,
        enable_ui_detect=enable_ui_detect,
        enable_ocr=enable_ocr,
        easyocr_langs=easyocr_langs,
        easyocr_confidence=easyocr_confidence,
        use_gpu=use_gpu,
        ui_canny_low=ui_canny_low,
        ui_canny_high=ui_canny_high,
        debug_mode=debug_mode,
        save_masks=save_masks,
        job_context=job_context,
        priority=priority,
    )
