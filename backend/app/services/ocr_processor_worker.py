"""
OCR Processor Worker - Consumer for Video Processing Tasks

Consumes OCR/video processing tasks from Redis Stream and executes them.
Integrates with video_pipeline_v6 and process_ocr_layout logic.

Fix:
  1. After OCR finishes, wait for transcript to be ready (with timeout)
     before enqueueing LLM — avoids race condition where OCR finishes
     first and LLM runs without transcript data.
  2. For audio-only assets (no OCR frames), still enqueue LLM if a
     transcript exists or becomes available.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import redis.asyncio as redis
from redis.exceptions import ConnectionError

from app.config import settings
from app.services.ocr.layout_processor import process_metadata_file
from app.services.ocr.video_pipeline_service import Config as OCRPipelineConfig, run_pipeline
from app.services.multipart_upload import MinIOMultipartService
from app.services.mongo_service import mongo_ocr_service
from app.services.redis.llm_processor_task import enqueue_llm_processing
from app.utils.decorator import singleton
from app.utils.logger import get_logger
from app.services.redis.ocr_processor_task import (
    OCRProcessorTask,
    OCR_PROCESSOR_STREAM_KEY,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Tuning knobs for transcript-readiness polling
# ---------------------------------------------------------------------------
# How many seconds to wait for transcript before giving up and running LLM
# with OCR-only data. Set to 0 to disable waiting entirely.
TRANSCRIPT_WAIT_TIMEOUT_SECONDS: float = float(
    getattr(settings, "TRANSCRIPT_WAIT_TIMEOUT_SECONDS", 300)   # 5 minutes
)
# How often to poll MongoDB for the transcript job
TRANSCRIPT_POLL_INTERVAL_SECONDS: float = 5.0


async def _wait_for_transcript(
    asset_id: str,
    *,
    timeout: float = TRANSCRIPT_WAIT_TIMEOUT_SECONDS,
    poll_interval: float = TRANSCRIPT_POLL_INTERVAL_SECONDS,
) -> bool:
    """
    Poll MongoDB until a transcript job exists for *asset_id* or timeout.

    Returns True  → transcript is available (may still be processing, but
                     at least one segment exists so LLM can use it).
    Returns False → timed out, proceed without transcript.
    """
    if timeout <= 0:
        return await mongo_ocr_service.has_transcript(asset_id)

    elapsed = 0.0
    while elapsed < timeout:
        if await mongo_ocr_service.has_transcript(asset_id):
            logger.info(
                f"[OCR Worker] Transcript ready for asset={asset_id} "
                f"(waited {elapsed:.0f}s)"
            )
            return True

        logger.debug(
            f"[OCR Worker] Transcript not yet available for asset={asset_id}, "
            f"retrying in {poll_interval}s (elapsed={elapsed:.0f}s / {timeout:.0f}s)"
        )
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    logger.warning(
        f"[OCR Worker] Transcript wait timed out for asset={asset_id} "
        f"after {timeout:.0f}s — proceeding with OCR-only LLM pass."
    )
    return False


@singleton
class OCRProcessorWorker:
    """Worker that consumes OCR processing tasks from Redis and executes them."""

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._consumer_id = f"ocr-worker-{__name__}"
        self._group_name = "ocr-processor-workers"
        self._stream_key = OCR_PROCESSOR_STREAM_KEY
        self._running = False
        self._storage = MinIOMultipartService()
        self._temp_dir = Path(__file__).resolve().parents[2] / "logs" / "ocr_temp"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    async def connect(self) -> None:
        """Connect to Redis."""
        if self._redis is not None:
            return

        try:
            redis_url = settings.REDIS_URL
            self._redis = redis.from_url(redis_url, decode_responses=False)
            await self._redis.ping()
            logger.info(f"✅ Connected to Redis OCR worker at {redis_url}")

            try:
                await self._redis.xgroup_create(
                    self._stream_key,
                    self._group_name,
                    id="0",
                    mkstream=True,
                )
                logger.info(f"Created consumer group '{self._group_name}'")
            except redis.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    logger.debug("Consumer group already exists")
                else:
                    raise

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise ConnectionError(f"Redis connection failed: {e}")

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("Redis connection closed")

    async def start(self) -> None:
        if self._running:
            return

        await self.connect()
        self._running = True

        logger.info(
            f"🔄 OCR Processor Worker started\n"
            f"   Stream: {self._stream_key}\n"
            f"   Group: {self._group_name}"
        )

        try:
            await self._consume_loop()
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
        finally:
            await self.disconnect()

    async def stop(self) -> None:
        self._running = False
        await self.disconnect()

    async def _consume_loop(self) -> None:
        logger.info("Starting consumer loop...")
        retry_count = 0
        max_retries = 10
        base_backoff = 1

        while self._running:
            try:
                result = await self._redis.xreadgroup(
                    groupname=self._group_name,
                    consumername=self._consumer_id,
                    streams={self._stream_key: ">"},
                    count=1,
                    block=5000,
                )

                if not result:
                    retry_count = 0
                    continue

                retry_count = 0
                for stream_name, messages in result:
                    for message_id, data in messages:
                        message_id_str = (
                            message_id.decode()
                            if isinstance(message_id, bytes)
                            else str(message_id)
                        )

                        try:
                            task = self._parse_task(message_id_str, data)
                            logger.info(f"📥 Received task: {task.task_id}")
                            await self._process_task(task)
                            await self._redis.xack(
                                self._stream_key, self._group_name, message_id
                            )
                            logger.info(f"✅ Task {task.task_id} acknowledged")

                        except Exception as e:
                            logger.error(
                                f"❌ Failed to process task: {e}", exc_info=True
                            )
                            try:
                                await self._redis.xack(
                                    self._stream_key, self._group_name, message_id
                                )
                            except Exception:
                                pass

            except ConnectionError as e:
                retry_count += 1
                backoff = min(base_backoff * (2 ** retry_count), 60)
                logger.warning(
                    f"Redis connection error (attempt {retry_count}/{max_retries}): {e}. "
                    f"Reconnecting in {backoff}s..."
                )

                if retry_count >= max_retries:
                    logger.error(
                        f"Max reconnection attempts ({max_retries}) exceeded. Stopping worker."
                    )
                    self._running = False
                    break

                await self.disconnect()
                await asyncio.sleep(backoff)

                try:
                    await self.connect()
                    logger.info("✅ Reconnected to Redis")
                    retry_count = 0
                except Exception as e:
                    logger.error(f"Failed to reconnect: {e}")

            except Exception as e:
                logger.error(f"Consumer loop error: {e}", exc_info=True)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Task parsing
    # ------------------------------------------------------------------

    def _parse_task(self, message_id: str, data: dict[bytes, bytes]) -> OCRProcessorTask:
        decoded = {k.decode(): v.decode() for k, v in data.items()}

        job_context_raw = decoded.get("job_context", "{}")
        try:
            job_context = json.loads(job_context_raw) if job_context_raw else {}
        except json.JSONDecodeError:
            job_context = {}

        return OCRProcessorTask(
            task_id=decoded.get("task_id", ""),
            priority=int(decoded.get("priority", 5)),
            retry_count=int(decoded.get("retry_count", 0)),
            created_at=float(decoded.get("created_at", 0)),
            video_id=decoded.get("video_id") or None,
            video_path=decoded.get("video_path", ""),
            output_dir=decoded.get("output_dir", ""),
            user_id=decoded.get("user_id") or None,
            ocr_engine=decoded.get("ocr_engine", "easyocr"),
            target_fps=float(decoded.get("target_fps", 1.0)),
            enable_ui_detect=decoded.get("enable_ui_detect", "True").lower() == "true",
            enable_ocr=decoded.get("enable_ocr", "True").lower() == "true",
            easyocr_langs=decoded.get("easyocr_langs", "en,vi"),
            easyocr_confidence=float(decoded.get("easyocr_confidence", 0.3)),
            use_gpu=decoded.get("use_gpu", "True").lower() == "true",
            ui_canny_low=int(decoded.get("ui_canny_low", 30)),
            ui_canny_high=int(decoded.get("ui_canny_high", 100)),
            debug_mode=decoded.get("debug_mode", "False").lower() == "true",
            save_masks=decoded.get("save_masks", "False").lower() == "true",
            job_context=job_context,
        )

    # ------------------------------------------------------------------
    # Pipeline config / path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_pipeline_config(task: OCRProcessorTask):
        cfg = OCRPipelineConfig()
        cfg.target_fps = task.target_fps
        cfg.ui_detect_enabled = task.enable_ui_detect
        cfg.ocr_engine = "easyocr"
        cfg.ocr_use_gpu = task.use_gpu
        cfg.easyocr_languages = tuple(
            lang.strip() for lang in task.easyocr_langs.split(",") if lang.strip()
        ) or ("en",)
        cfg.easyocr_confidence_threshold = task.easyocr_confidence
        cfg.ui_canny_low = task.ui_canny_low
        cfg.ui_canny_high = task.ui_canny_high
        cfg.save_mask = task.save_masks
        cfg.debug = task.debug_mode
        return cfg

    @staticmethod
    def _resolve_output_dir(task: OCRProcessorTask) -> Path:
        backend_root = Path(__file__).resolve().parents[2]
        default_base = backend_root / "logs" / "ocr_processing"

        if not task.output_dir:
            return default_base / task.task_id

        raw_output_dir = task.output_dir.strip()
        if raw_output_dir.startswith(("/", "\\")):
            return backend_root / raw_output_dir.lstrip("/\\")

        output_path = Path(raw_output_dir)
        if output_path.is_absolute():
            return output_path

        return backend_root / output_path

    @staticmethod
    def _resolve_video_path(task: OCRProcessorTask) -> Path:
        return Path(task.video_path)

    def _download_from_minio(self, object_key: str, task_id: str) -> Path:
        if not object_key or object_key.strip() == "":
            raise ValueError("video_path/object_key cannot be empty")

        suffix = Path(object_key).suffix or ".webm"
        local_path = self._temp_dir / f"{task_id}_{uuid4().hex[:8]}{suffix}"

        logger.info(
            f"⬇️ Downloading from MinIO: bucket={self._storage.bucket}, key={object_key}"
        )
        self._storage.client.download_file(
            self._storage.bucket,
            object_key,
            str(local_path),
        )

        if not local_path.exists():
            raise FileNotFoundError(f"Downloaded file missing: {local_path}")

        size_mb = local_path.stat().st_size / (1024 * 1024)
        logger.info(f"✅ Downloaded {size_mb:.2f} MB to {local_path}")
        return local_path

    @staticmethod
    def _cleanup_temp_file(local_path: Optional[Path]) -> None:
        if not local_path:
            return
        try:
            if local_path.exists():
                local_path.unlink()
                logger.debug(f"Removed temp file: {local_path}")
        except Exception as exc:
            logger.warning(f"Failed to remove temp file {local_path}: {exc}")

    def _run_pipeline_and_layout(self, task: OCRProcessorTask) -> dict[str, Any]:
        video_path = self._resolve_video_path(task)
        local_video_path: Optional[Path] = None
        downloaded_from_minio = False

        if video_path.exists():
            local_video_path = video_path
            logger.info(f"Using local video path: {local_video_path}")
        else:
            local_video_path = self._download_from_minio(task.video_path, task.task_id)
            downloaded_from_minio = True

        output_dir = self._resolve_output_dir(task)
        output_dir.mkdir(parents=True, exist_ok=True)

        cfg = self._build_pipeline_config(task)

        try:
            run_pipeline(str(local_video_path), str(output_dir), cfg)

            metadata_path = output_dir / "metadata.json"
            if not metadata_path.exists():
                raise FileNotFoundError(f"Pipeline metadata not found: {metadata_path}")

            cleaned_metadata_path = output_dir / "cleaned_metadata.json"
            processed_data = process_metadata_file(
                input_path=metadata_path,
                output_path=cleaned_metadata_path,
                verbose=True,
            )
            non_empty_count = sum(
                1
                for item in processed_data
                if (item.get("processed_text") or "").strip()
            )

            return {
                "output_dir": str(output_dir),
                "metadata_frames": len(processed_data),
                "layout_frames": len(processed_data),
                "non_empty_layout_frames": non_empty_count,
                "cleaned_metadata_path": str(cleaned_metadata_path),
            }
        finally:
            if downloaded_from_minio:
                self._cleanup_temp_file(local_video_path)

    # ------------------------------------------------------------------
    # Main task processing
    # ------------------------------------------------------------------

    async def _process_task(self, task: OCRProcessorTask) -> None:
        """
        Process a single OCR/video task.

        Processing order:
          1. Run video_pipeline + layout (OCR)
          2. Persist OCR frames to MongoDB
          3. Wait for transcript to be ready (with timeout)
          4. Enqueue LLM processing
             - If there are OCR frames → normal video path
             - If no OCR frames but transcript exists → audio-only path
             - If neither → skip LLM
        """
        logger.info(
            f"🎬 Processing video task:\n"
            f"   video_id:   {task.video_id}\n"
            f"   video_path: {task.video_path}\n"
            f"   output_dir: {task.output_dir}\n"
            f"   ocr_engine: {task.ocr_engine}\n"
            f"   target_fps: {task.target_fps}\n"
            f"   ui_detect:  {task.enable_ui_detect}\n"
            f"   ocr:        {task.enable_ocr}\n"
            f"   debug:      {task.debug_mode}"
        )

        if not mongo_ocr_service.is_connected:
            await mongo_ocr_service.connect()

        asset_id = str(task.video_id) if task.video_id else task.task_id

        # ── Determine if this is an audio-only asset ──────────────────────────
        # An audio-only asset has enable_ocr=False or the job_context marks it.
        is_audio_only = (not task.enable_ocr) or (
            (task.job_context or {}).get("asset_type") in {"live_session"}
            and not task.enable_ocr
        )

        # ── Path A: Audio-only (no video pipeline needed) ─────────────────────
        if is_audio_only:
            await self._handle_audio_only(task, asset_id)
            return

        # ── Path B: Video (OCR pipeline) ───────────────────────────────────────
        await self._handle_video(task, asset_id)

    # ------------------------------------------------------------------
    # Audio-only path
    # ------------------------------------------------------------------

    async def _handle_audio_only(self, task: OCRProcessorTask, asset_id: str) -> None:
        """
        For audio-only assets: create a minimal OCR job record, wait for
        transcript, then enqueue LLM so it can produce knowledge from speech.
        """
        logger.info(
            f"🔊 Audio-only asset detected: {asset_id}. "
            "Skipping OCR pipeline, waiting for transcript…"
        )

        # Create OCR job record so LLM worker can reference it
        ocr_job_id = await mongo_ocr_service.upsert_ocr_job(
            asset_id=asset_id,
            user_id=task.user_id or "",
            task_id=task.task_id,
            status="completed",   # no OCR work to do
        )

        # Mark 0 frames so stats are accurate
        await mongo_ocr_service.update_ocr_job_stats(
            job_id=ocr_job_id,
            total_frames=0,
            non_empty_frames=0,
            status="completed",
        )

        # Wait for transcript
        transcript_ready = await _wait_for_transcript(asset_id)

        if transcript_ready:
            logger.info(
                f"📤 Enqueueing LLM (audio-only, transcript ready) for asset={asset_id}"
            )
            await enqueue_llm_processing(
                asset_id=asset_id,
                user_id=task.user_id or "",
                ocr_job_id=ocr_job_id,
                job_context=task.job_context or {},
            )
        else:
            logger.warning(
                f"⚠️ No transcript found for audio-only asset={asset_id} "
                "after timeout — skipping LLM."
            )

    # ------------------------------------------------------------------
    # Video path
    # ------------------------------------------------------------------

    async def _handle_video(self, task: OCRProcessorTask, asset_id: str) -> None:
        """
        Full video processing: OCR pipeline → persist frames → wait for
        transcript → enqueue LLM.
        """
        # ── Step 1: Create OCR job record ─────────────────────────────────────
        ocr_job_id = await mongo_ocr_service.upsert_ocr_job(
            asset_id=asset_id,
            user_id=task.user_id or "",
            task_id=task.task_id,
            status="processing",
        )
        logger.info(f"📝 Created OCR job: {ocr_job_id}")

        # ── Step 2: Run OCR pipeline in thread pool ───────────────────────────
        try:
            summary = await asyncio.to_thread(self._run_pipeline_and_layout, task)
        except Exception as exc:
            await mongo_ocr_service.update_ocr_job_stats(
                job_id=ocr_job_id,
                total_frames=0,
                non_empty_frames=0,
                status="failed",
            )
            logger.exception(f"Pipeline failed for task {task.task_id}: {exc}")
            return

        # ── Step 3: Persist OCR frames to MongoDB ─────────────────────────────
        non_empty = 0
        try:
            cleaned_path = Path(summary["cleaned_metadata_path"])
            with open(cleaned_path, "r", encoding="utf-8") as f:
                cleaned_frames: list[dict] = json.load(f)

            metadata_path = Path(summary["output_dir"]) / "metadata.json"
            with open(metadata_path, "r", encoding="utf-8") as f:
                raw_metadata: list[dict] = json.load(f)

            raw_by_frame_id = {item["frame_id"]: item for item in raw_metadata}

            merged_frames = []
            for item in cleaned_frames:
                raw = raw_by_frame_id.get(item["frame_id"], {})
                merged_frames.append(
                    {
                        "frame_id": item["frame_id"],
                        "timestamp": item["timestamp"],
                        "processed_text": item.get("processed_text", ""),
                        "ssim_score": raw.get("ssim_score"),
                        "changed": raw.get("changed", True),
                        "theme": raw.get("theme"),
                        "regions": raw.get("regions", []),
                        "ui_regions": raw.get("ui_regions", []),
                    }
                )

            saved_count = await mongo_ocr_service.save_ocr_frames(
                asset_id=asset_id,
                user_id=task.user_id or "",
                frames=merged_frames,
            )

            non_empty = sum(
                1 for f in merged_frames if (f.get("processed_text") or "").strip()
            )

            await mongo_ocr_service.update_ocr_job_stats(
                job_id=ocr_job_id,
                total_frames=len(merged_frames),
                non_empty_frames=non_empty,
                status="completed",
                output_dir=summary["output_dir"],
            )

            logger.info(
                f"✅ OCR frames persisted: task={task.task_id}, "
                f"total={len(merged_frames)}, non_empty={non_empty}, saved={saved_count}"
            )

        except Exception as exc:
            await mongo_ocr_service.update_ocr_job_stats(
                job_id=ocr_job_id,
                total_frames=0,
                non_empty_frames=0,
                status="failed",
            )
            logger.exception(f"Frame persistence failed for task {task.task_id}: {exc}")
            return

        # ── Step 4: Wait for transcript before enqueueing LLM ────────────────
        # Even if there are no OCR frames (e.g. blank-screen recording), we
        # still try to enqueue LLM if transcript is available.
        has_ocr_content = non_empty > 0

        if has_ocr_content:
            # Video has real screen content → wait for transcript to enrich LLM
            logger.info(
                f"[OCR Worker] OCR done ({non_empty} frames). "
                f"Waiting for transcript (up to {TRANSCRIPT_WAIT_TIMEOUT_SECONDS:.0f}s)…"
            )
            await _wait_for_transcript(asset_id)
            # Enqueue regardless — LLM worker handles missing transcript gracefully
            logger.info(
                f"📤 Enqueueing LLM (video + OCR) for asset={asset_id}"
            )
            await enqueue_llm_processing(
                asset_id=asset_id,
                user_id=task.user_id or "",
                ocr_job_id=ocr_job_id,
                job_context=task.job_context or {},
            )
        else:
            # No OCR content — check for transcript
            logger.info(
                f"[OCR Worker] No OCR frames for asset={asset_id}. "
                "Checking for transcript…"
            )
            transcript_ready = await _wait_for_transcript(asset_id)
            if transcript_ready:
                logger.info(
                    f"📤 Enqueueing LLM (video, OCR empty, transcript exists) "
                    f"for asset={asset_id}"
                )
                await enqueue_llm_processing(
                    asset_id=asset_id,
                    user_id=task.user_id or "",
                    ocr_job_id=ocr_job_id,
                    job_context=task.job_context or {},
                )
            else:
                logger.warning(
                    f"⚠️ No OCR frames and no transcript for asset={asset_id} — "
                    "skipping LLM."
                )


def get_ocr_processor_worker() -> OCRProcessorWorker:
    return OCRProcessorWorker()


async def start_ocr_processor_worker() -> None:
    worker = get_ocr_processor_worker()
    await worker.start()


async def stop_ocr_processor_worker() -> None:
    worker = get_ocr_processor_worker()
    await worker.stop()