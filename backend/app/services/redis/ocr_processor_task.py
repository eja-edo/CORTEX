"""
OCR/Video Processing Task for Redis Stream

Defines task model and producer for video frame OCR processing pipeline.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional, Dict
from uuid import UUID

from app.services.redis.base_producer import RedisStreamProducerBase


# Task stream configuration
OCR_PROCESSOR_STREAM_KEY = "ocr:processor:stream"


@dataclass
class OCRProcessorTask:
    """Task for video OCR and layout processing."""

    # Common task fields
    priority: int = 5
    retry_count: int = 0
    task_id: str = field(default_factory=lambda: f"ocr_task_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}")
    created_at: float = field(default_factory=time.time)

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

    def to_dict(self) -> dict[str, str]:
        """Serialize task to dict for Redis XADD."""
        import json

        return {
            "task_id": self.task_id,
            "priority": str(self.priority),
            "retry_count": str(self.retry_count),
            "created_at": str(self.created_at),
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
        }


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
