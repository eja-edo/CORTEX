"""
LLM Processor Worker

Consumes LLM tasks from Redis → retrieves OCR frames from MongoDB →
calls Gemini → saves results to MongoDB.
"""

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Optional

import redis.asyncio as redis
from redis.exceptions import ConnectionError, ResponseError

from app.config import settings
from app.services.mongo_service import MongoOCRService
from app.services.llm_processing import gemini_service
from app.services.redis.llm_processor_task import LLM_PROCESSOR_STREAM_KEY, LLMProcessorTask
from app.utils.decorator import singleton
from app.utils.logger import get_logger

logger = get_logger(__name__)

WINDOW_SECONDS = settings.LLM_WINDOW_SECONDS  # 30s per batch
MIN_KNOWLEDGE_VALUE = settings.LLM_MIN_KNOWLEDGE_VALUE


@singleton
class LLMProcessorWorker:
    """Worker that consumes LLM processing tasks from Redis."""

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._stream_key = LLM_PROCESSOR_STREAM_KEY
        self._group_name = "llm-processor-workers"
        self._consumer_id = "llm-worker-main"
        self._running = False
        # Each worker/thread gets its own MongoOCRService instance
        self._mongo_ocr_service = MongoOCRService()

    async def start(self) -> None:
        """Start consuming LLM processing tasks with connection retry logic."""
        if self._running:
            return

        try:
            self._redis = redis.from_url(settings.REDIS_URL, decode_responses=False)
            await self._redis.ping()
            logger.info(f"✅ Connected to Redis at {settings.REDIS_URL}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise ConnectionError(f"Redis connection failed: {e}")

        # Create consumer group
        try:
            await self._redis.xgroup_create(
                self._stream_key, self._group_name, id="0", mkstream=True
            )
            logger.info(f"Created consumer group '{self._group_name}'")
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            logger.debug(f"Consumer group already exists")

        self._running = True
        logger.info("🤖 LLM Processor Worker started")
        await self._consume_loop()

    async def stop(self) -> None:
        """Stop consuming tasks."""
        self._running = False
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def _consume_loop(self) -> None:
        """Main consumer loop with reconnection logic."""
        retry_count = 0
        max_retries = 10
        base_backoff = 1  # seconds

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
                    retry_count = 0  # Reset on successful read
                    continue

                retry_count = 0  # Reset on successful read
                for _, messages in result:
                    for msg_id, data in messages:
                        decoded = {k.decode(): v.decode() for k, v in data.items()}
                        task = LLMProcessorTask(
                            task_id=decoded.get("task_id", ""),
                            asset_id=decoded.get("asset_id", ""),
                            user_id=decoded.get("user_id", ""),
                            ocr_job_id=decoded.get("ocr_job_id", ""),
                            job_context=json.loads(decoded.get("job_context", "{}")),
                        )
                        try:
                            await self._process_task(task)
                        except Exception as exc:
                            logger.exception(f"LLM task failed: {task.task_id}: {exc}")
                        finally:
                            try:
                                await self._redis.xack(self._stream_key, self._group_name, msg_id)
                            except Exception:
                                pass
                                
            except ConnectionError as exc:
                retry_count += 1
                backoff = min(base_backoff * (2 ** retry_count), 60)  # Exponential backoff, max 60s
                logger.error(
                    f"LLM consumer Redis connection error (attempt {retry_count}/{max_retries}): {exc}. "
                    f"Reconnecting in {backoff}s..."
                )
                
                if retry_count >= max_retries:
                    logger.error(f"Max reconnection attempts ({max_retries}) exceeded. Stopping worker.")
                    self._running = False
                    break
                
                if self._redis:
                    try:
                        await self._redis.close()
                    except Exception:
                        pass
                self._redis = None
                
                await asyncio.sleep(backoff)
                
                try:
                    self._redis = redis.from_url(settings.REDIS_URL, decode_responses=False)
                    await self._redis.ping()
                    logger.info("✅ LLM worker reconnected to Redis")
                    retry_count = 0
                except Exception as e:
                    logger.error(f"LLM worker failed to reconnect: {e}")
                    
            except Exception as exc:
                logger.error(f"LLM consumer loop error: {exc}")
                await asyncio.sleep(2)

    async def _process_task(self, task: LLMProcessorTask) -> None:
        """
        Process LLM task:
          1. Get OCR frames from MongoDB
          2. Group into windows 30s
          3. Call Gemini for each window
          4. Save OCRProcessedDocument
          5. Extract KnowledgeUnits
          6. Session synthesis → AssetKnowledgeSummary
        """
        if not self._mongo_ocr_service.is_connected:
            await self._mongo_ocr_service.connect()

        # Mark job as LLM processing
        await self._mongo_ocr_service.set_llm_status(task.ocr_job_id, "processing")

        frames = await self._mongo_ocr_service.get_ocr_frames(
            task.asset_id, skip_empty=True
        )
        if not frames:
            logger.info(f"No frames to process for asset {task.asset_id}")
            await self._mongo_ocr_service.set_llm_status(task.ocr_job_id, "skipped")
            return

        # ── Group frames into windows ──────────────────────────────────────
        windows = self._group_frames_into_windows(frames)
        logger.info(
            f"Processing {len(frames)} frames → {len(windows)} windows for asset={task.asset_id}"
        )

        processed_summaries = []
        total_tokens = 0
        total_cost = 0.0

        for window in windows:
            result = await gemini_service.process_screen_segments(
                raw_text=window["combined_text"],
                start_ms=int(window["start_timestamp_sec"] * 1000),
                end_ms=int(window["end_timestamp_sec"] * 1000),
                asset_context=f"asset_{task.asset_id}",
            )

            total_tokens += result.tokens_used
            total_cost += result.cost_usd

            window_doc = {
                "start_timestamp_sec": window["start_timestamp_sec"],
                "end_timestamp_sec": window["end_timestamp_sec"],
                "frame_ids": window["frame_ids"],
                "combined_text": window["combined_text"],
                "status": "completed" if result.success else "failed",
                "error_message": result.error_message,
                "llm_model": gemini_service.DEFAULT_MODEL,
                "tokens_used": result.tokens_used,
                "cost_usd": result.cost_usd,
            }

            if result.success and result.parsed_data:
                window_doc["analysis"] = result.parsed_data
                processed_summaries.append(
                    {
                        "start_ms": int(window["start_timestamp_sec"] * 1000),
                        "end_ms": int(window["end_timestamp_sec"] * 1000),
                        "summary": result.parsed_data.get("summary"),
                        "screen_type": result.parsed_data.get("screen_type"),
                        "user_intent": result.parsed_data.get("user_intent"),
                        "topics": result.parsed_data.get("topics", []),
                        "knowledge_value": float(
                            result.parsed_data.get("knowledge_value", 0)
                        ),
                    }
                )

                # Extract knowledge units if high enough value
                kv = float(result.parsed_data.get("knowledge_value", 0))
                if kv >= MIN_KNOWLEDGE_VALUE:
                    await self._extract_and_save_knowledge_units(
                        window["combined_text"],
                        result.parsed_data.get("summary", ""),
                        task.asset_id,
                        task.user_id,
                    )

            # Persist window
            await self._mongo_ocr_service.save_ocr_processed(
                asset_id=task.asset_id,
                user_id=task.user_id,
                ocr_job_id=task.ocr_job_id,
                window=window_doc,
            )

        # ── Session synthesis ─────────────────────────────────────────────
        if len(processed_summaries) >= 1:
            await self._synthesize_and_save(
                task, processed_summaries, total_tokens, total_cost
            )

        await self._mongo_ocr_service.set_llm_status(task.ocr_job_id, "completed")
        logger.info(
            f"✅ LLM processing done: asset={task.asset_id}, "
            f"windows={len(windows)}, tokens={total_tokens}, cost=${total_cost:.4f}"
        )

    def _group_frames_into_windows(self, frames: list[dict]) -> list[dict]:
        """Group consecutive frames into WINDOW_SECONDS windows."""
        if not frames:
            return []

        windows = []
        current_frames = [frames[0]]
        window_start = frames[0]["timestamp_sec"]

        for frame in frames[1:]:
            if frame["timestamp_sec"] - window_start <= WINDOW_SECONDS:
                current_frames.append(frame)
            else:
                windows.append(self._make_window(current_frames))
                current_frames = [frame]
                window_start = frame["timestamp_sec"]

        windows.append(self._make_window(current_frames))
        return windows

    @staticmethod
    def _make_window(frames: list[dict]) -> dict:
        """Create a window dict from frames."""
        combined = "\n\n---\n\n".join(
            f.get("processed_text", "").strip()
            for f in frames
            if (f.get("processed_text") or "").strip()
        )
        return {
            "start_timestamp_sec": frames[0]["timestamp_sec"],
            "end_timestamp_sec": frames[-1]["timestamp_sec"],
            "frame_ids": [f["frame_id"] for f in frames],
            "combined_text": combined,
        }

    async def _extract_and_save_knowledge_units(
        self,
        text: str,
        context: str,
        asset_id: str,
        user_id: str,
    ) -> int:
        """Extract and save knowledge units from text."""
        result = await gemini_service.extract_knowledge(text, context)
        if not result.success:
            return 0

        count = 0
        data = result.parsed_data or {}

        type_map = [
            ("facts", "fact", lambda x: x.get("content", "")),
            ("errors", "error", lambda x: x.get("message", "")),
            ("code_patterns", "code_pattern", lambda x: x.get("snippet", "")),
            ("commands", "command", lambda x: x.get("command", "")),
        ]

        for key, unit_type, get_content in type_map:
            for item in data.get(key, []):
                content = get_content(item)
                if not content or len(content.strip()) < 5:
                    continue

                content_hash = hashlib.sha256(
                    f"{user_id}:{content.strip().lower()}".encode()
                ).hexdigest()

                unit = {
                    "asset_id": asset_id,
                    "user_id": user_id,
                    "unit_type": unit_type,
                    "content": content.strip(),
                    "context": item.get("context") or item.get("purpose"),
                    "confidence": item.get("confidence", 1.0),
                    "content_hash": content_hash,
                    "deleted_at": None,
                    # type-specific
                    "error_type": item.get("error_type"),
                    "resolution": item.get("resolution"),
                    "language": item.get("language"),
                    "reusability": item.get("reusability", 0.5),
                }

                inserted = await self._mongo_ocr_service.save_knowledge_unit(unit)
                if inserted:
                    count += 1

        return count

    async def _synthesize_and_save(
        self,
        task: LLMProcessorTask,
        summaries: list[dict],
        total_tokens: int,
        total_cost: float,
    ) -> None:
        """Synthesize session and save AssetKnowledgeSummary."""
        duration_ms = (
            summaries[-1]["end_ms"] - summaries[0]["start_ms"] if summaries else 0
        )
        result = await gemini_service.synthesize_session(
            processed_segments=summaries[:50],
            asset_title=f"asset_{task.asset_id}",
            duration_ms=duration_ms
        )

        summary_doc = {
            "asset_id": task.asset_id,
            "user_id": task.user_id,
            "ocr_job_id": task.ocr_job_id,
            "status": "completed" if result.success else "failed",
            "llm_model": gemini_service.SYNTHESIS_MODEL,
            "tokens_used": result.tokens_used + total_tokens,
            "cost_usd": result.cost_usd + total_cost,
            "synthesized_at": datetime.utcnow().isoformat(),
        }

        if result.success and result.parsed_data:
            summary_doc.update(result.parsed_data)

        await self._mongo_ocr_service.upsert_asset_knowledge(
            asset_id=task.asset_id,
            summary=summary_doc,
        )


def get_llm_processor_worker() -> LLMProcessorWorker:
    """Get singleton LLM processor worker."""
    return LLMProcessorWorker()

