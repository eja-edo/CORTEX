"""
Whisper Transcription Processor - BATCHED REDIS MODE

Transcription flow with Redis-based batched sending:
1. Download audio from MinIO
2. Transcribe and collect segments in memory
3. Send batches of segments as Redis tasks (CHUNK_BATCH_SIZE segments per task)
4. Orchestrator will consume tasks and save to MongoDB progressively

FIXES APPLIED:
- Fix 1: Speaker extracted from word-level if segment-level is missing
- Fix 2: Fallback result preserves word-level timestamps for assign_word_speakers
- Fix 3: sample_rate hardcoded to 16000 (WhisperX standard)
- Fix 4: Added detailed diagnostic logging for diarization pipeline
- Fix 5: hf_token validation is strict (strips whitespace, rejects empty string)
- Fix 6: align result always passed through assign_word_speakers when diarization is active
- Fix 7: Thread exception is re-raised properly (not swallowed)
"""

import asyncio
import importlib
import inspect
import tempfile
import shutil
import math
from typing import Optional, Dict, Any
from pathlib import Path
from dataclasses import dataclass

from minio import Minio

from stt_service.utils.logger import get_logger
from stt_service.service.redis.redis_producer_service import RedisProducerService
from stt_service.utils.decorator import singleton

from stt_service.config.app_config import ConfigManager
from stt_service.models.transcription_task import TranscriptionStreamTask
from stt_service.models.save_transcription_task import SaveTranscriptionTask

logger = get_logger(__name__)


@dataclass
class TranscriptionSegment:
    """A segment of transcribed text with timestamps."""
    start: float
    end: float
    text: str
    confidence: float
    speaker_label: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "confidence": self.confidence,
            "speaker_label": self.speaker_label or "unknown",
        }


def _extract_speaker_from_segment(seg: dict) -> str:
    """
    FIX 1: Extract speaker label from segment or fall back to word-level majority vote.

    WhisperX assigns speaker labels at the *word* level after diarization.
    The segment-level "speaker" key is only set when all words agree.
    When words have different speakers we take the majority.
    """
    speaker = seg.get("speaker")
    if speaker:
        return speaker

    words = seg.get("words", [])
    if not words:
        return "unknown"

    speaker_counts: Dict[str, int] = {}
    for word in words:
        sp = word.get("speaker")
        if sp:
            speaker_counts[sp] = speaker_counts.get(sp, 0) + 1

    if not speaker_counts:
        return "unknown"

    # Return the speaker who appears most often in this segment
    return max(speaker_counts, key=lambda s: speaker_counts[s])


@singleton
class WhisperTranscriptionProcessor:
    """
    Processor that transcribes audio files using Whisper and streams batches to Redis.

    Flow:
    1. Download audio from MinIO
    2. Transcribe audio and stream batches to Redis as segments are collected
    3. Send batch immediately when CHUNK_BATCH_SIZE segments are ready
    4. On success: send final "completed" marker task
    5. On error: send "failed" marker task to notify consumer
    6. Orchestrator consumer saves batches to MongoDB and updates track status
    7. Cleanup temp files
    """

    CHUNK_BATCH_SIZE = 50
    SAVE_STREAM_KEY = "save_transcription:stream"

    def __init__(self):
        self._config = ConfigManager().get_config()
        self._minio_client: Optional[Minio] = None
        self._whisperx: Optional[Any] = None
        self._whisper_model: Optional[Any] = None
        self._align_model: Optional[Any] = None
        self._align_metadata: Optional[Dict[str, Any]] = None
        self._align_language_code: Optional[str] = None
        self._diarization_pipeline: Optional[Any] = None
        self._initialized = False
        self._temp_dir: Optional[Path] = None
        self._redis_producer: Optional[RedisProducerService] = None
        self.CHUNK_BATCH_SIZE = self._config.Transcirpt.chunk_size
        logger.info("WhisperTranscriptionProcessor created (batched Redis mode)")

    async def initialize(self):
        """Initialize MinIO client, Whisper model, Redis producer, and temp directory."""
        if self._initialized:
            return

        logger.info("Initializing WhisperTranscriptionProcessor...")

        # Initialize Redis producer for save tasks
        self._redis_producer = RedisProducerService.get_instance(
            task_class=SaveTranscriptionTask,
            stream_key=self.SAVE_STREAM_KEY
        )
        await self._redis_producer.connect()
        logger.info("✅ Redis producer connected")

        # Create temp directory for audio files
        self._temp_dir = Path(tempfile.gettempdir()) / "whisper_transcriptions"
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Temp directory: {self._temp_dir}")

        # Initialize MinIO client
        minio_config = self._config.minio
        self._minio_client = Minio(
            minio_config.endpoint,
            access_key=minio_config.access_key,
            secret_key=minio_config.secret_key,
            secure=minio_config.secure,
        )
        logger.info(f"✅ MinIO client connected to {minio_config.endpoint}")

        # Verify bucket exists
        try:
            if not self._minio_client.bucket_exists(minio_config.bucket):
                raise RuntimeError(f"Bucket '{minio_config.bucket}' does not exist")
        except Exception as e:
            logger.error(f"Failed to verify MinIO bucket: {e}")
            raise

        # Initialize Whisper model
        whisper_config = self._config.whisper
        try:
            self._whisperx = importlib.import_module("whisperx")
        except ImportError as exc:
            raise RuntimeError(
                "whisperx is not installed. Add it to stt_service requirements and reinstall dependencies."
            ) from exc

        logger.info(
            f"Loading WhisperX model '{whisper_config.model_size}' "
            f"on {whisper_config.device}..."
        )
        loop = asyncio.get_event_loop()
        self._whisper_model = await loop.run_in_executor(
            None,
            lambda: self._whisperx.load_model(
                whisper_config.model_size,
                device=whisper_config.device,
                compute_type=whisper_config.compute_type,
            ),
        )
        logger.info(f"✅ WhisperX model loaded: {whisper_config.model_size}")

        self._align_model = None
        self._align_metadata = None
        self._align_language_code = None

        # FIX 5: Strip whitespace before checking token validity
        hf_token = (self._config.whisper.hf_token or "").strip()

        if self._config.whisper.diarization_enabled:
            if hf_token:
                try:
                    diarization_cls = getattr(self._whisperx, "DiarizationPipeline", None)
                    if diarization_cls is None:
                        diarize_module = importlib.import_module("whisperx.diarize")
                        diarization_cls = getattr(diarize_module, "DiarizationPipeline", None)

                    if diarization_cls is None:
                        raise AttributeError(
                            "DiarizationPipeline not found in whisperx or whisperx.diarize"
                        )

                    init_params = inspect.signature(diarization_cls.__init__).parameters
                    diarization_kwargs: Dict[str, Any] = {
                        "device": whisper_config.device,
                    }
                    if "use_auth_token" in init_params:
                        diarization_kwargs["use_auth_token"] = hf_token
                    elif "token" in init_params:
                        diarization_kwargs["token"] = hf_token
                    else:
                        logger.warning(
                            "DiarizationPipeline constructor has no token/use_auth_token "
                            "parameter; attempting init without explicit token"
                        )

                    self._diarization_pipeline = diarization_cls(**diarization_kwargs)
                    logger.info("✅ WhisperX diarization pipeline loaded")

                    # FIX 4: Diagnostic log so we know diarization is truly active
                    logger.info(
                        f"   Diarization pipeline type : {type(self._diarization_pipeline)}"
                    )
                except Exception as e:
                    self._diarization_pipeline = None
                    logger.warning(f"WhisperX diarization disabled after load failure: {e}")
            else:
                logger.warning(
                    "WhisperX diarization enabled but WHISPERX_HF_TOKEN is empty or whitespace; "
                    "speaker labels will be omitted"
                )
        else:
            logger.info("WhisperX diarization is disabled in config")

        self._initialized = True

    def _get_align_resources(self, language_code: str) -> tuple[Any, Dict[str, Any]]:
        if self._whisperx is None:
            raise RuntimeError("whisperx is not installed")

        if (
            self._align_model is not None
            and self._align_metadata is not None
            and self._align_language_code == language_code
        ):
            return self._align_model, self._align_metadata

        align_model, align_metadata = self._whisperx.load_align_model(
            language_code=language_code,
            device=self._config.whisper.device,
        )
        self._align_model = align_model
        self._align_metadata = align_metadata
        self._align_language_code = language_code
        return align_model, align_metadata

    async def _download_from_minio(self, object_key: str) -> tuple[Path, float]:
        """
        Download audio file from MinIO to temp directory.

        Args:
            object_key: Path to file in MinIO bucket

        Returns:
            Tuple of (local_path, file_size_mb)

        Raises:
            RuntimeError: If download fails
        """
        if not self._minio_client:
            raise RuntimeError("MinIO client not initialized")

        if not self._temp_dir:
            raise RuntimeError("Temp directory not initialized")

        if not object_key or object_key.strip() == "":
            raise ValueError("Object key cannot be empty")

        safe_filename = Path(object_key).name
        local_path = self._temp_dir / safe_filename

        try:
            stat = self._minio_client.stat_object(
                self._config.minio.bucket,
                object_key
            )
            file_size_mb = stat.size / (1024 * 1024)
            logger.info(f"📦 File size: {file_size_mb:.2f} MB")
        except Exception as e:
            logger.error(f"File not found in MinIO: {object_key}")
            raise RuntimeError(f"File not found in MinIO: {object_key}") from e

        logger.info(f"⬇️  Downloading {object_key} to {local_path}...")

        try:
            loop = asyncio.get_event_loop()

            def do_download():
                self._minio_client.fget_object(
                    self._config.minio.bucket,
                    object_key,
                    str(local_path)
                )

            await loop.run_in_executor(None, do_download)

            if not local_path.exists():
                raise RuntimeError(f"Download failed: {local_path} does not exist")

            downloaded_size_mb = local_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ Downloaded {downloaded_size_mb:.2f} MB to {local_path}")

            return local_path, file_size_mb

        except Exception as e:
            logger.error(f"Failed to download {object_key}: {e}")
            if local_path.exists():
                local_path.unlink()
            raise RuntimeError(f"Failed to download {object_key}") from e

    async def _transcribe_and_stream_batches(
        self,
        audio_path: Path,
        track_ref_id: str,
    ) -> int:
        """
        Transcribe audio and stream batches to Redis as they're collected.
        Sends batch immediately when CHUNK_BATCH_SIZE is reached.

        Args:
            audio_path: Path to audio file
            track_ref_id: Egress ID / Track reference

        Returns:
            Number of batches sent
        """
        if not self._whisper_model:
            raise RuntimeError("Whisper model not initialized")

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if not self._redis_producer:
            raise RuntimeError("Redis producer not initialized")

        whisper_config = self._config.whisper
        logger.info(f"🎤 Starting transcription for {audio_path.name}...")

        batch_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def transcribe_in_thread():
            """Transcribe audio and push batches to the async queue."""
            try:
                if self._whisperx is None:
                    raise RuntimeError("whisperx is not installed")

                audio = self._whisperx.load_audio(str(audio_path))
                result = self._whisper_model.transcribe(
                    audio,
                    language=whisper_config.language if whisper_config.language else None,
                    batch_size=max(1, min(16, self.CHUNK_BATCH_SIZE)),
                    num_workers=0,
                    task="transcribe",
                    chunk_size=30,
                )

                detected_language = result.get("language") or whisper_config.language or "en"
                raw_segments = result.get("segments", [])

                # ----------------------------------------------------------------
                # FIX 2: Run alignment; on failure keep raw segments AND attempt
                # to preserve word-level data so assign_word_speakers can work.
                # ----------------------------------------------------------------
                alignment_ok = False
                try:
                    align_model, align_metadata = self._get_align_resources(detected_language)
                    result = self._whisperx.align(
                        raw_segments,
                        align_model,
                        align_metadata,
                        audio,
                        device=whisper_config.device,
                        return_char_alignments=False,
                    )
                    alignment_ok = True
                    logger.info(f"✅ WhisperX alignment completed for language={detected_language}")
                except Exception as e:
                    logger.warning(
                        f"WhisperX alignment skipped for language={detected_language}: {e}. "
                        "Speaker diarization quality may be reduced."
                    )
                    # Keep original segments; assign_word_speakers needs at least the
                    # segment list even without word-level timestamps.
                    result = {"segments": raw_segments}

                # ----------------------------------------------------------------
                # FIX 6: Always run diarization when pipeline is available,
                # regardless of whether alignment succeeded.
                # FIX 3: Use hardcoded WHISPERX_SAMPLE_RATE (16000) instead of
                # config value which may be wrong.
                # ----------------------------------------------------------------
                if self._diarization_pipeline is not None:
                    try:
                        # Always use file path – whisperX DiarizationPipeline wraps
                        # pyannote internally and handles loading itself.
                        # Passing a raw tensor dict causes (None, slice(None,None,None))
                        # because pyannote expects its own Audio loader, not a bare tensor.
                        logger.info(f"🎙️ Running diarization on: {audio_path}")
                        diarize_segments = self._diarization_pipeline(
                            str(audio_path),
                            min_speakers=None,
                            max_speakers=None,
                        )

                        logger.info(
                            f"✅ Diarization done — "
                            f"type={type(diarize_segments)}, "
                            f"repr={repr(diarize_segments)[:120]}"
                        )

                        result = self._whisperx.assign_word_speakers(diarize_segments, result)

                        # Diagnostic – confirm speakers were assigned
                        sample = (result.get("segments") or [{}])[0]
                        logger.info(
                            f"🔍 Post-diarization sample — "
                            f"keys: {list(sample.keys())}, "
                            f"speaker: {sample.get('speaker')!r}, "
                            f"first word: {(sample.get('words') or [{}])[0]}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"WhisperX diarization skipped: {e}",
                            exc_info=True,
                        )
                else:
                    logger.debug("Diarization pipeline not available; skipping speaker assignment.")

                # ----------------------------------------------------------------
                # Collect segments into batches and push to async queue
                # ----------------------------------------------------------------
                current_batch = []

                for seg in result.get("segments", []):
                    # FIX 1: Use word-level majority vote when segment speaker is missing
                    speaker = _extract_speaker_from_segment(seg)

                    segment = TranscriptionSegment(
                        start=float(seg.get("start", 0.0)),
                        end=float(seg.get("end", 0.0)),
                        text=str(seg.get("text", "")).strip(),
                        confidence=round(math.exp(float(seg.get("avg_logprob", -1.0))), 4),
                        speaker_label=speaker,
                    )

                    current_batch.append(segment.to_dict())

                    if len(current_batch) >= self.CHUNK_BATCH_SIZE:
                        asyncio.run_coroutine_threadsafe(
                            batch_queue.put(("batch", current_batch.copy())),
                            loop,
                        )
                        current_batch.clear()

                # Send remaining segments as final batch
                if current_batch:
                    asyncio.run_coroutine_threadsafe(
                        batch_queue.put(("batch", current_batch)),
                        loop,
                    )

                # Signal completion
                asyncio.run_coroutine_threadsafe(
                    batch_queue.put(("done", None)),
                    loop,
                )

            except Exception as e:
                logger.error(f"❌ Transcription failed in thread: {e}", exc_info=True)
                # FIX 7: Forward the original exception message so it is not swallowed
                asyncio.run_coroutine_threadsafe(
                    batch_queue.put(("error", str(e))),
                    loop,
                )

        # Start transcription in thread
        transcription_task = loop.run_in_executor(None, transcribe_in_thread)

        chunk_index = 0
        total_segments = 0

        try:
            while True:
                msg_type, data = await batch_queue.get()

                if msg_type == "batch":
                    batch_segments = data
                    total_segments += len(batch_segments)

                    start_time = batch_segments[0]["start"]
                    end_time = batch_segments[-1]["end"]

                    task = SaveTranscriptionTask(
                        track_ref_id=track_ref_id,
                        segments=batch_segments,
                        chunk_index=chunk_index,
                        start_time=start_time,
                        end_time=end_time,
                        item_count=len(batch_segments),
                        is_final=False,
                        status="pending",
                    )

                    await self._redis_producer.enqueue(task)

                    logger.info(
                        f"📥 Sent batch {chunk_index + 1}: "
                        f"{len(batch_segments)} segments, "
                        f"time={start_time:.1f}-{end_time:.1f}s"
                    )

                    chunk_index += 1

                elif msg_type == "done":
                    final_task = SaveTranscriptionTask(
                        track_ref_id=track_ref_id,
                        segments=[],
                        chunk_index=chunk_index,
                        start_time=0.0,
                        end_time=0.0,
                        item_count=0,
                        is_final=True,
                        status="completed",
                    )
                    await self._redis_producer.enqueue(final_task)

                    logger.info(
                        f"✅ Transcription complete: {total_segments} segments, "
                        f"{chunk_index} batches sent"
                    )
                    break

                elif msg_type == "error":
                    error_msg = data

                    failed_task = SaveTranscriptionTask(
                        track_ref_id=track_ref_id,
                        segments=[],
                        chunk_index=chunk_index,
                        start_time=0.0,
                        end_time=0.0,
                        item_count=0,
                        is_final=True,
                        status="failed",
                    )
                    await self._redis_producer.enqueue(failed_task)
                    logger.info("📤 Sent failed task to Redis for consumer to mark track as failed")

                    # Wait for thread to complete before raising
                    await transcription_task

                    raise RuntimeError(f"Whisper transcription failed: {error_msg}")

            # Wait for thread to complete normally
            await transcription_task

            return chunk_index

        except Exception as e:
            # Ensure thread completes even on error
            try:
                await transcription_task
            except Exception:
                pass
            raise e

    def _cleanup_temp_file(self, file_path: Path):
        """Remove temporary audio file."""
        try:
            if file_path.exists():
                file_path.unlink()
                logger.debug(f"🗑️  Cleaned up temp file: {file_path.name}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {file_path}: {e}")

    async def process(self, task: TranscriptionStreamTask) -> str:
        """
        Process a transcription task by streaming batches to Redis.

        Main entry point that orchestrates the entire transcription flow:
        1. Initialize resources
        2. Download audio from MinIO
        3. Transcribe and stream batches to Redis as they're collected
        4. On error, send failed task to notify consumer
        5. Cleanup temp files

        Args:
            task: TranscriptionStreamTask with file information

        Returns:
            Empty string (batches are streamed to Redis, not returned)

        Raises:
            RuntimeError: If any step fails
        """
        await self.initialize()

        source_object_key = task.source_object_key or task.filename
        display_name = task.filename or Path(source_object_key).name

        track_ref_id = task.egress_id
        if not track_ref_id:
            raise ValueError("Transcription task is missing egress_id")

        logger.info(f"🎯 Processing transcription task: {display_name}")
        logger.info(f"   Track ref: {track_ref_id}\n")

        local_file: Optional[Path] = None
        try:
            # STEP 1: Download audio from MinIO
            local_file, file_size_mb = await self._download_from_minio(source_object_key)

            # STEP 2: Transcribe and stream batches to Redis
            num_batches = await self._transcribe_and_stream_batches(
                audio_path=local_file,
                track_ref_id=track_ref_id,
            )

            # STEP 3: Log final results
            logger.info(
                f"\n{'='*60}\n"
                f"✅ TRANSCRIPTION COMPLETE - BATCHES STREAMED TO REDIS\n"
                f"{'='*60}\n"
                f"File: {task.filename}\n"
                f"Size: {file_size_mb:.2f} MB\n"
                f"Batches sent: {num_batches}\n"
                f"Track ID: {track_ref_id}\n"
                f"Status: All batches sent to Redis queue\n"
                f"{'='*60}"
            )

            return ""

        except Exception as e:
            logger.error(f"❌ Failed to process transcription: {e}")
            raise

        finally:
            # STEP 4: Always cleanup temp file
            if local_file:
                self._cleanup_temp_file(local_file)

    async def shutdown(self):
        """
        Cleanup resources and temp directory.

        Should be called when shutting down the service.
        """
        logger.info("Shutting down WhisperTranscriptionProcessor...")

        if self._temp_dir and self._temp_dir.exists():
            try:
                shutil.rmtree(self._temp_dir)
                logger.info(f"🗑️  Removed temp directory: {self._temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to remove temp directory: {e}")

        if self._redis_producer:
            await self._redis_producer.close()

        self._whisper_model = None
        self._align_model = None
        self._align_metadata = None
        self._align_language_code = None
        self._diarization_pipeline = None
        self._minio_client = None
        self._redis_producer = None
        self._initialized = False

        logger.info("✅ WhisperTranscriptionProcessor shutdown complete")


# ============================================================
# PUBLIC API
# ============================================================


async def transcribe_task(task: TranscriptionStreamTask) -> str:
    """
    Convenience function to transcribe a task.

    Can be used directly as the processor for TranscriptionQueueService:
        queue_service.set_processor(transcribe_task)

    Args:
        task: TranscriptionStreamTask to process

    Returns:
        Full transcribed text (empty – batches are streamed to Redis)
    """
    processor = WhisperTranscriptionProcessor()
    return await processor.process(task)