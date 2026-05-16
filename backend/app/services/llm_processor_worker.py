"""
LLM Processor Worker

Consumes LLM tasks from Redis → retrieves OCR frames AND transcript segments
from MongoDB → calls Gemini → saves timeline-based results to MongoDB.

Supports three asset types:
  1. Video with OCR only
  2. Video with OCR + transcript (audio narration)
  3. Audio only (transcript only, no OCR frames)

Changes vs previous version:
  - `decisions` is now handled as a first-class knowledge unit type in
    _extract_and_save_knowledge_units.
  - `key_quotes` from session synthesis is persisted as knowledge units.
  - Audio-only path still works correctly even when ocr_frames is empty.
  - MIN_KNOWLEDGE_VALUE threshold applies to knowledge *unit* extraction
    but NOT to timeline events in the synthesis (we keep all events).
"""

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Optional

from app.config import settings
from app.services.mongo_service import MongoOCRService
from app.services.llm_processing import gemini_service
from app.services.redis.llm_processor_task import (
    LLM_PROCESSOR_STREAM_KEY,
    LLM_CONSUMER_GROUP,
    LLMProcessorTask,
)
from app.services.redis.redis_stream_service import RedisStreamService
from app.utils.decorator import singleton
from app.utils.logger import get_logger
from app.models import AssetStatus, Asset
from app.database import get_db

logger = get_logger(__name__)

WINDOW_SECONDS = settings.LLM_WINDOW_SECONDS            # default 30s per batch
MIN_KNOWLEDGE_VALUE = settings.LLM_MIN_KNOWLEDGE_VALUE  # default 0.3


# ── Transcript windowing helpers ──────────────────────────────────────────────

def _get_transcript_for_window(
    transcript_segments: list[dict],
    window_start: float,
    window_end: float,
) -> str:
    lines = []
    for seg in transcript_segments:
        seg_start = float(seg.get("start_time_sec", 0))
        seg_end = float(seg.get("end_time_sec", seg_start + 1))
        if seg_end < window_start or seg_start > window_end:
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = (seg.get("speaker_label") or "").strip()
        if speaker and speaker.lower() not in ("unknown", ""):
            lines.append(f"[{speaker}] {text}")
        else:
            lines.append(text)
    return " ".join(lines)


def _build_transcript_only_windows(
    transcript_segments: list[dict],
    window_seconds: float,
) -> list[dict]:
    if not transcript_segments:
        return []

    windows = []
    current_segs: list[dict] = []
    window_start = float(transcript_segments[0].get("start_time_sec", 0))

    for seg in transcript_segments:
        seg_start = float(seg.get("start_time_sec", 0))
        if seg_start - window_start <= window_seconds:
            current_segs.append(seg)
        else:
            if current_segs:
                windows.append(_make_transcript_window(current_segs))
            current_segs = [seg]
            window_start = seg_start

    if current_segs:
        windows.append(_make_transcript_window(current_segs))

    return windows


def _make_transcript_window(segs: list[dict]) -> dict:
    start = float(segs[0].get("start_time_sec", 0))
    end = float(segs[-1].get("end_time_sec", start + 1))
    lines = []
    for s in segs:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        speaker = (s.get("speaker_label") or "").strip()
        if speaker and speaker.lower() not in ("unknown", ""):
            lines.append(f"[{speaker}] {text}")
        else:
            lines.append(text)
    return {
        "start_timestamp_sec": start,
        "end_timestamp_sec": end,
        "frame_ids": [],
        "combined_text": "",
        "transcript_text": " ".join(lines),
        "has_ocr": False,
        "has_transcript": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Worker
# ─────────────────────────────────────────────────────────────────────────────

@singleton
class LLMProcessorWorker:
    """
    LLM Processor Worker - Consumes tasks from Redis Stream using standardized service.
    
    Uses RedisStreamService for:
    - Connection pooling
    - Worker heartbeat
    - Task recovery (orphaned tasks)
    - Graceful shutdown
    """
    
    def __init__(self):
        self._running = False
        self._redis_service: Optional[RedisStreamService] = None
        self._mongo_ocr_service = MongoOCRService()

    async def start(self) -> None:
        """Start the LLM worker with standardized Redis service."""
        if self._running:
            return

        # Initialize standardized Redis stream service
        self._redis_service = RedisStreamService.get_instance(
            task_class=LLMProcessorTask,
            stream_key=LLM_PROCESSOR_STREAM_KEY,
            group_name=LLM_CONSUMER_GROUP,
        )
        
        await self._redis_service.connect()
        await self._redis_service.start_background_tasks()
        
        self._running = True
        logger.info("🤖 LLM Processor Worker started (with standardized Redis service)")
        await self._consume_loop()

    async def stop(self) -> None:
        """Stop the LLM worker gracefully."""
        self._running = False
        
        if self._redis_service:
            # Stop background tasks (heartbeat, recovery)
            await self._redis_service.stop_background_tasks()
            # Disconnect and release pending tasks
            await self._redis_service.disconnect(release_pending=True)
            self._redis_service = None
        
        logger.info("🛑 LLM Processor Worker stopped")

    async def _consume_loop(self) -> None:
        """
        Consume tasks from Redis Stream using standardized service.
        
        Features:
        - Automatic connection pooling
        - Worker heartbeat (running in background)
        - Task acknowledgment/rejection
        - Graceful error handling
        """
        while self._running:
            try:
                # Read tasks from stream (blocks for 5 seconds if no tasks)
                tasks = await self._redis_service.read_tasks(count=1, block_ms=5000)
                
                if not tasks:
                    # No tasks available, loop will retry
                    continue
                
                # Process each task
                for task in tasks:
                    try:
                        logger.info(f"🔍 Processing LLM task: {task.task_id} (asset={task.asset_id})")
                        await self._process_task(task)
                        
                        # Acknowledge successful completion
                        await self._redis_service.acknowledge(task)
                        logger.info(f"✅ LLM task completed: {task.task_id}")
                        
                    except Exception as exc:
                        logger.exception(f"❌ LLM task failed: {task.task_id}: {exc}")
                        
                        # Reject task (will retry up to max_retries, then move to DLQ)
                        try:
                            await self._redis_service.reject(
                                task, 
                                error=str(exc)[:500],  # Truncate long errors
                                retry=True
                            )
                        except Exception as reject_error:
                            logger.error(f"Failed to reject task {task.task_id}: {reject_error}")
                
            except ConnectionError as exc:
                logger.error(f"LLM consumer Redis connection error: {exc}")
                # RedisStreamService will handle reconnection automatically
                await asyncio.sleep(5)
                
            except Exception as exc:
                logger.error(f"LLM consumer loop error: {exc}")
                await asyncio.sleep(2)

    # ── Task processing ───────────────────────────────────────────────────────

    async def _process_task(self, task: LLMProcessorTask) -> None:
        """
        Main processing flow:
          1. Fetch OCR frames (may be empty for audio-only)
          2. Fetch transcript segments (may be empty for video-only)
          3. Build time windows
          4. Call Gemini per window → save OCRProcessedDocument
          5. Extract knowledge units
          6. Session synthesis → AssetKnowledgeSummary
        """
        if not self._mongo_ocr_service.is_connected:
            await self._mongo_ocr_service.connect()

        await self._mongo_ocr_service.update_ocr_job_stats(
            job_id=task.ocr_job_id,
            total_frames=0,  # Không thay đổi số frame ở đây
            non_empty_frames=0,
            status="processing",
        )

        # ── Fetch source data ─────────────────────────────────────────────────
        ocr_frames = await self._mongo_ocr_service.get_ocr_frames(
            task.asset_id, skip_empty=True
        )
        transcript_segments = await self._mongo_ocr_service.get_transcript_segments_for_asset(
            task.asset_id
        )

        has_ocr = len(ocr_frames) > 0
        has_transcript = len(transcript_segments) > 0

        logger.info(
            f"Asset {task.asset_id}: ocr_frames={len(ocr_frames)}, "
            f"transcript_segs={len(transcript_segments)}, "
            f"has_ocr={has_ocr}, has_transcript={has_transcript}"
        )

        if not has_ocr and not has_transcript:
            logger.info(f"No content to process for asset {task.asset_id}")
            await self._mongo_ocr_service.update_ocr_job_stats(
                job_id=task.ocr_job_id,
                total_frames=0,
                non_empty_frames=0,
                status="skipped",
            )
            return

        # ── Build windows ─────────────────────────────────────────────────────
        if has_ocr:
            windows = self._build_ocr_windows_with_transcript(
                ocr_frames, transcript_segments
            )
        else:
            # Audio-only: derive windows from transcript
            windows = _build_transcript_only_windows(transcript_segments, WINDOW_SECONDS)

        logger.info(
            f"Processing {len(windows)} windows for asset={task.asset_id} "
            f"(ocr={has_ocr}, transcript={has_transcript})"
        )

        # ── Process each window ───────────────────────────────────────────────
        processed_summaries: list[dict] = []
        total_tokens = 0
        total_cost = 0.0

        for window in windows:
            w_start = window["start_timestamp_sec"]
            w_end = window["end_timestamp_sec"]
            ocr_text = window.get("combined_text", "")
            transcript_text = window.get("transcript_text", "")

            result = await gemini_service.process_window(
                start_sec=w_start,
                end_sec=w_end,
                ocr_text=ocr_text,
                transcript_text=transcript_text,
                asset_context=f"asset_{task.asset_id}",
            )

            total_tokens += result.tokens_used
            total_cost += result.cost_usd

            window_doc: dict = {
                "start_timestamp_sec": w_start,
                "end_timestamp_sec": w_end,
                "frame_ids": window.get("frame_ids", []),
                "combined_text": ocr_text,
                "transcript_text": transcript_text,
                "status": "completed" if result.success else "failed",
                "error_message": result.error_message,
                "llm_model": result.model_used,
                "tokens_used": result.tokens_used,
                "cost_usd": result.cost_usd,
            }

            if result.success and result.parsed_data:
                window_doc["analysis"] = result.parsed_data

                summary_entry = {
                    "start_sec": w_start,
                    "end_sec": w_end,
                    "start_ms": int(w_start * 1000),
                    "end_ms": int(w_end * 1000),
                    "summary": result.parsed_data.get("summary"),
                    "screen_type": result.parsed_data.get("screen_type"),
                    "user_intent": result.parsed_data.get("user_intent"),
                    "topics": result.parsed_data.get("topics", []),
                    "knowledge_value": float(result.parsed_data.get("knowledge_value", 0)),
                    "timeline_events": result.parsed_data.get("timeline_events", []),
                    "has_ocr": has_ocr and bool(ocr_text.strip()),
                    "has_transcript": has_transcript and bool(transcript_text.strip()),
                }
                processed_summaries.append(summary_entry)

                # Knowledge unit extraction for high-value windows
                kv = float(result.parsed_data.get("knowledge_value", 0))
                if kv >= MIN_KNOWLEDGE_VALUE:
                    await self._extract_and_save_knowledge_units(
                        ocr_text=ocr_text,
                        transcript_text=transcript_text,
                        context=result.parsed_data.get("summary", ""),
                        asset_id=task.asset_id,
                        user_id=task.user_id,
                        start_sec=w_start,
                        end_sec=w_end,
                        has_ocr=has_ocr and bool(ocr_text.strip()),
                        has_transcript=has_transcript and bool(transcript_text.strip()),
                    )

                # Persist timeline events as knowledge units (all events, no threshold)
                for event in result.parsed_data.get("timeline_events", []):
                    evt_kv = float(event.get("knowledge_value", 0))
                    if evt_kv >= MIN_KNOWLEDGE_VALUE:
                        await self._save_timeline_event_as_unit(
                            event=event,
                            asset_id=task.asset_id,
                            user_id=task.user_id,
                            ocr_processed_id="pending",
                            has_ocr=has_ocr and bool(ocr_text.strip()),
                            has_transcript=has_transcript and bool(transcript_text.strip()),
                        )

            # ĐÃ XOÁ: Không lưu ocr_processed nữa

        # ── Session synthesis ─────────────────────────────────────────────────
        if processed_summaries:
            await self._synthesize_and_save(
                task=task,
                summaries=processed_summaries,
                total_tokens=total_tokens,
                total_cost=total_cost,
                has_video=has_ocr,
                has_audio=has_transcript,
            )

        await self._mongo_ocr_service.update_ocr_job_stats(
            job_id=task.ocr_job_id,
            total_frames=0,
            non_empty_frames=0,
            status="completed",
        )
        # Update status in assets table (PostgreSQL)
        db_gen = get_db()
        db = next(db_gen)
        try:
            asset = db.query(Asset).filter(Asset.id == task.asset_id).first()
            if asset:
                # Nếu AssetStatus có COMPLETED thì dùng, không thì fallback READY
                asset.status = AssetStatus.COMPLETED
                asset.updated_at = datetime.utcnow()
                db.add(asset)
                db.commit()
        finally:
            db.close()
        logger.info(
            f"✅ LLM processing done: asset={task.asset_id}, "
            f"windows={len(windows)}, tokens={total_tokens}, cost=${total_cost:.4f}"
        )

    # ── Window building ───────────────────────────────────────────────────────

    def _build_ocr_windows_with_transcript(
        self,
        ocr_frames: list[dict],
        transcript_segments: list[dict],
    ) -> list[dict]:
        if not ocr_frames:
            return []

        raw_windows = self._group_frames_into_windows(ocr_frames)

        for w in raw_windows:
            w["transcript_text"] = _get_transcript_for_window(
                transcript_segments,
                w["start_timestamp_sec"],
                w["end_timestamp_sec"],
            )
            w["has_ocr"] = True
            w["has_transcript"] = bool(w["transcript_text"].strip())

        return raw_windows

    def _group_frames_into_windows(self, frames: list[dict]) -> list[dict]:
        if not frames:
            return []

        windows = []
        current_frames = [frames[0]]
        window_start = frames[0]["timestamp_sec"]

        for frame in frames[1:]:
            if frame["timestamp_sec"] - window_start <= WINDOW_SECONDS:
                current_frames.append(frame)
            else:
                windows.append(self._make_ocr_window(current_frames))
                current_frames = [frame]
                window_start = frame["timestamp_sec"]

        windows.append(self._make_ocr_window(current_frames))
        return windows

    @staticmethod
    def _make_ocr_window(frames: list[dict]) -> dict:
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
            "transcript_text": "",
        }

    # ── Knowledge unit extraction ─────────────────────────────────────────────

    async def _extract_and_save_knowledge_units(
        self,
        ocr_text: str,
        transcript_text: str,
        context: str,
        asset_id: str,
        user_id: str,
        start_sec: float,
        end_sec: float,
        has_ocr: bool,
        has_transcript: bool,
    ) -> int:
        result = await gemini_service.extract_knowledge(
            text=ocr_text,
            context=context,
            start_sec=start_sec,
            end_sec=end_sec,
            transcript_text=transcript_text,
        )
        if not result.success:
            return 0

        count = 0
        data = result.parsed_data or {}

        # Each tuple: (key, unit_type, content_getter, extra_fields_getter)
        type_map = [
            ("facts", "fact",
             lambda x: x.get("content", ""),
             lambda x: {}),
            ("errors", "error",
             lambda x: x.get("message", ""),
             lambda x: {}),
            ("code_patterns", "code_pattern",
             lambda x: x.get("snippet", ""),
             lambda x: {"language": x.get("language")}),
            ("commands", "command",
             lambda x: x.get("command", ""),
             lambda x: {"platform": x.get("platform")}),
            ("explanations", "explanation",
             lambda x: x.get("explanation", ""),
             lambda x: {}),
            # NEW: decisions
            ("decisions", "decision",
             lambda x: x.get("decision", ""),
             lambda x: {"rationale": x.get("rationale", "")}),
        ]

        for key, unit_type, get_content, get_extra in type_map:
            for item in data.get(key, []):
                content = get_content(item)
                if not content or len(content.strip()) < 5:
                    continue

                item_start = float(item.get("start_sec", start_sec))
                item_end = float(item.get("end_sec", end_sec))

                content_hash = hashlib.sha256(
                    f"{user_id}:{content.strip().lower()}".encode()
                ).hexdigest()

                unit: dict = {
                    "asset_id": asset_id,
                    "unit_type": unit_type,
                    "content": content.strip(),
                    "confidence": item.get("confidence", 1.0),
                    "start_sec": item_start,
                    "end_sec": item_end,
                    "content_hash": content_hash,
                    "deleted_at": None,
                    "language": item.get("language"),
                    **get_extra(item),
                }

                inserted = await self._mongo_ocr_service.save_knowledge_unit(unit)
                if inserted:
                    count += 1

        return count

    async def _save_timeline_event_as_unit(
        self,
        event: dict,
        asset_id: str,
        user_id: str,
        ocr_processed_id: str,
        has_ocr: bool,
        has_transcript: bool,
    ) -> bool:
        summary = (event.get("activity_summary") or "").strip()
        if not summary or len(summary) < 10:
            return False

        event_type = event.get("event_type", "activity")
        type_map = {
            "error": "error",
            "solution": "fact",
            "explanation": "explanation",
            "decision": "decision",
            "activity": "fact",
        }
        unit_type = type_map.get(event_type, "fact")

        content_hash = hashlib.sha256(
            f"{user_id}:{summary.lower()}".encode()
        ).hexdigest()

        unit: dict = {
            "asset_id": asset_id,
            "unit_type": unit_type,
            "content": summary,
            "confidence": float(event.get("knowledge_value", 0.5)),
            "start_sec": float(event.get("start_sec", 0)),
            "end_sec": float(event.get("end_sec", 0)),
            "content_hash": content_hash,
            "deleted_at": None,
            "language": None,
        }

        # Attach spoken/screen content as metadata if present
        if event.get("spoken_content"):
            unit["spoken_content"] = event["spoken_content"]
        if event.get("screen_content"):
            unit["screen_content"] = event["screen_content"]

        return await self._mongo_ocr_service.save_knowledge_unit(unit)

    # ── Session synthesis ─────────────────────────────────────────────────────

    async def _synthesize_and_save(
        self,
        task: LLMProcessorTask,
        summaries: list[dict],
        total_tokens: int,
        total_cost: float,
        has_video: bool,
        has_audio: bool,
    ) -> None:
        duration_ms = (
            int(summaries[-1]["end_sec"] * 1000) - int(summaries[0]["start_sec"] * 1000)
            if summaries
            else 0
        )

        result = await gemini_service.synthesize_session(
            processed_segments=summaries[:50],
            asset_title=f"asset_{task.asset_id}",
            duration_ms=duration_ms,
            has_video=has_video,
            has_audio=has_audio,
        )

        summary_doc: dict = {
            "asset_id": task.asset_id,
            "user_id": task.user_id,
            "ocr_job_id": task.ocr_job_id,
            "has_video": has_video,
            "has_audio": has_audio,
            "status": "completed" if result.success else "failed",
            "llm_model": result.model_used,
            "tokens_used": result.tokens_used + total_tokens,
            "cost_usd": result.cost_usd + total_cost,
            "synthesized_at": datetime.utcnow().isoformat(),
        }

        if result.success and result.parsed_data:
            summary_doc.update(result.parsed_data)
            if "knowledge_timeline" not in summary_doc:
                summary_doc["knowledge_timeline"] = []

            # Persist key_quotes as knowledge units so they are searchable
            for quote_item in result.parsed_data.get("key_quotes", []):
                quote_text = (quote_item.get("quote") or "").strip()
                if not quote_text:
                    continue
                content_hash = hashlib.sha256(
                    f"{task.user_id}:quote:{quote_text.lower()}".encode()
                ).hexdigest()
                await self._mongo_ocr_service.save_knowledge_unit(
                    {
                        "asset_id": task.asset_id,
                        "unit_type": "fact",
                        "content": quote_text,
                        "confidence": 0.9,
                        "start_sec": float(quote_item.get("start_sec", 0)),
                        "end_sec": float(quote_item.get("start_sec", 0)) + 5,
                        "content_hash": content_hash,
                        "deleted_at": None,
                        "language": None,
                        "is_key_quote": True,
                        "quote_context": quote_item.get("context", ""),
                    }
                )

        await self._mongo_ocr_service.upsert_asset_knowledge(
            asset_id=task.asset_id,
            summary=summary_doc,
        )
        logger.info(
            f"📚 Session knowledge saved for asset={task.asset_id}, "
            f"timeline_events={len(summary_doc.get('knowledge_timeline', []))}"
        )


def get_llm_processor_worker() -> LLMProcessorWorker:
    return LLMProcessorWorker()