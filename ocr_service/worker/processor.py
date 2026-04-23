"""
OCR Task Processor

Handles the actual OCR processing workflow:
1. Download video from MinIO
2. Run OCR pipeline
3. Process layout
4. Save frames to MongoDB
5. Wait for transcript
6. Enqueue LLM task
"""

import asyncio
import json
import logging
from pathlib import Path

from storage.minio_client import MinIOClient
from storage.mongo_client import MongoOCRWriter
from pipeline.video_pipeline import run_pipeline, Config as PipelineConfig
from pipeline.layout_processor import process_metadata_file
from worker.transcript_waiter import wait_for_transcript
from config import settings

logger = logging.getLogger(__name__)


class OCRTaskProcessor:
    """Processes individual OCR tasks."""
    
    def __init__(self):
        self._minio = MinIOClient()
        self._mongo = MongoOCRWriter()
        self._temp_dir = Path(settings.temp_dir)
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    async def process(self, task) -> None:
        """Process a single OCR video task."""
        asset_id = task.video_id or task.task_id
        
        # Skip audio-only assets (Phase 1: video path only)
        if not task.enable_ocr:
            logger.info(f"Skipping audio-only asset: {asset_id}")
            return
        
        # 1. Upsert OCR job record
        ocr_job_id = await self._mongo.upsert_ocr_job(
            asset_id=asset_id,
            user_id=task.user_id or "",
            task_id=task.task_id,
            status="processing",
        )
        logger.info(f"Created OCR job: {ocr_job_id}")
        
        # 2. Download video from MinIO
        local_path = None
        try:
            local_path = await asyncio.to_thread(
                self._minio.download, task.video_path, task.task_id
            )
            logger.info(f"Downloaded video: {local_path}")
            
            # 3. Run OCR pipeline
            output_dir = self._temp_dir / task.task_id
            output_dir.mkdir(parents=True, exist_ok=True)
            
            cfg = self._build_config(task)
            await asyncio.to_thread(run_pipeline, str(local_path), str(output_dir), cfg)
            logger.info(f"OCR pipeline completed: {output_dir}")
            
            # 4. Process layout
            metadata_path = output_dir / "metadata.json"
            if not metadata_path.exists():
                raise FileNotFoundError(f"Pipeline metadata not found: {metadata_path}")
            
            cleaned_path = output_dir / "cleaned_metadata.json"
            processed_frames = process_metadata_file(
                input_path=metadata_path,
                output_path=cleaned_path,
                verbose=True,
            )
            
            # 5. Merge & save to MongoDB
            with open(metadata_path, encoding='utf-8') as f:
                raw_meta = {item["frame_id"]: item for item in json.load(f)}
            
            merged = [
                {
                    "frame_id": f["frame_id"],
                    "timestamp": f["timestamp"],
                    "processed_text": f.get("processed_text", ""),
                    "ssim_score": raw_meta.get(f["frame_id"], {}).get("ssim_score"),
                    "changed": raw_meta.get(f["frame_id"], {}).get("changed", True),
                    "theme": raw_meta.get(f["frame_id"], {}).get("theme"),
                    "regions": raw_meta.get(f["frame_id"], {}).get("regions", []),
                    "ui_regions": raw_meta.get(f["frame_id"], {}).get("ui_regions", []),
                }
                for f in processed_frames
            ]
            
            non_empty = sum(1 for f in merged if (f.get("processed_text") or "").strip())
            
            await self._mongo.save_ocr_frames(
                asset_id=asset_id,
                user_id=task.user_id or "",
                frames=merged,
            )
            
            await self._mongo.update_ocr_job_stats(
                ocr_job_id,
                len(merged),
                non_empty,
                "completed",
            )
            
            logger.info(
                f"OCR frames saved: total={len(merged)}, non_empty={non_empty}"
            )
            
            # 6. Wait for transcript
            transcript_ready = await wait_for_transcript(
                asset_id, self._mongo, timeout=settings.transcript_wait_timeout
            )
            
            # 7. Enqueue LLM (regardless of transcript readiness)
            await self._enqueue_llm(asset_id, task.user_id or "", ocr_job_id, task.job_context)
            
        except Exception as e:
            logger.exception(f"Task {task.task_id} failed: {e}")
            try:
                await self._mongo.update_ocr_job_stats(ocr_job_id, 0, 0, "failed")
            except Exception:
                pass
            raise
        finally:
            # Cleanup temp file
            if local_path and local_path.exists():
                local_path.unlink(missing_ok=True)
                logger.debug(f"Cleaned up temp file: {local_path}")

    async def _enqueue_llm(self, asset_id, user_id, ocr_job_id, job_context):
        """Enqueue LLM processing task to Redis stream."""
        import redis.asyncio as aioredis
        
        r = aioredis.from_url(settings.redis_url, decode_responses=False)
        await r.xadd(settings.output_stream_key, {
            "task_id": f"llm_{asset_id}",
            "asset_id": asset_id,
            "user_id": user_id,
            "ocr_job_id": ocr_job_id,
            "job_context": json.dumps(job_context or {}),
        })
        await r.close()
        logger.info(f"Enqueued LLM task for asset: {asset_id}")

    @staticmethod
    def _build_config(task) -> PipelineConfig:
        """Build pipeline config from task."""
        cfg = PipelineConfig()
        cfg.target_fps = task.target_fps
        cfg.ui_detect_enabled = task.enable_ui_detect
        cfg.ocr_engine = "easyocr" if task.enable_ocr else None
        cfg.ocr_use_gpu = task.use_gpu
        cfg.easyocr_languages = tuple(
            lang.strip() for lang in task.easyocr_langs.split(",") if lang.strip()
        ) or ("en",)
        cfg.easyocr_confidence_threshold = task.easyocr_confidence
        return cfg
