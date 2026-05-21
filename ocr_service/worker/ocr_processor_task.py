"""
OCR/Video Processing Task for OCR service Redis consumer.

This is a local copy of the stream task model so the OCR service does not
need to import the backend's `app` package, which has startup side effects.
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from lib.stream_base import BaseProducerTask


OCR_PROCESSOR_STREAM_KEY = "ocr:processor:stream"
OCR_CONSUMER_GROUP = "ocr-external-workers"


@dataclass
class OCRProcessorTask(BaseProducerTask):
    """Task model for OCR video processing consumed by OCR service."""

    video_id: Optional[str] = None
    video_path: str = ""
    output_dir: str = ""
    user_id: Optional[str] = None

    ocr_engine: str = "easyocr"
    target_fps: float = 1.0
    enable_ui_detect: bool = True
    enable_ocr: bool = True

    easyocr_langs: str = "en,vi"
    easyocr_confidence: float = 0.3
    use_gpu: bool = True

    ui_canny_low: int = 30
    ui_canny_high: int = 100

    debug_mode: bool = False
    save_masks: bool = False

    job_context: Optional[Dict[str, Any]] = None

    message_id: str = ""

    def to_dict(self) -> dict[str, str]:
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
    def from_stream_message(cls, message_id: str, data: Dict[bytes, bytes]) -> "OCRProcessorTask":
        def decode_bytes(val):
            if isinstance(val, bytes):
                return val.decode("utf-8")
            return val

        def decode_key(key):
            if isinstance(key, bytes):
                return key.decode("utf-8")
            return key

        decoded_data = {decode_key(k): decode_bytes(v) for k, v in data.items()}

        job_context = None
        if decoded_data.get("job_context"):
            try:
                job_context = json.loads(decoded_data["job_context"])
            except (json.JSONDecodeError, TypeError):
                job_context = {}

        try:
            priority = int(decoded_data.get("priority", "5"))
        except ValueError:
            priority = 5

        try:
            retry_count = int(decoded_data.get("retry_count", "0"))
        except ValueError:
            retry_count = 0

        return cls(
            task_id=decoded_data.get("task_id", ""),
            message_id=message_id,
            retry_count=retry_count,
            priority=priority,
            created_at=float(decoded_data.get("created_at", time.time())),
            video_id=decoded_data.get("video_id") or None,
            video_path=decoded_data.get("video_path", ""),
            output_dir=decoded_data.get("output_dir", ""),
            user_id=decoded_data.get("user_id") or None,
            ocr_engine=decoded_data.get("ocr_engine", "easyocr"),
            target_fps=float(decoded_data.get("target_fps", "1.0")),
            enable_ui_detect=decoded_data.get("enable_ui_detect", "True").lower() == "true",
            enable_ocr=decoded_data.get("enable_ocr", "True").lower() == "true",
            easyocr_langs=decoded_data.get("easyocr_langs", "en,vi"),
            easyocr_confidence=float(decoded_data.get("easyocr_confidence", "0.3")),
            use_gpu=decoded_data.get("use_gpu", "True").lower() == "true",
            ui_canny_low=int(decoded_data.get("ui_canny_low", "30")),
            ui_canny_high=int(decoded_data.get("ui_canny_high", "100")),
            debug_mode=decoded_data.get("debug_mode", "False").lower() == "true",
            save_masks=decoded_data.get("save_masks", "False").lower() == "true",
            job_context=job_context,
        )