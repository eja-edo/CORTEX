from __future__ import annotations

import asyncio
import json
import socket
import uuid

import redis.asyncio as redis
from redis.exceptions import ResponseError

from app.config import settings
from app.mongo_schemas import SaveTranscriptionChunkMessage
from app.services.mongo_service import mongo_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TranscriptionResultsConsumer:
    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._consumer_task: asyncio.Task | None = None
        self._running = False

        self._stream_key = settings.REDIS_SAVE_STREAM_KEY
        self._group_name = settings.REDIS_SAVE_CONSUMER_GROUP
        self._consumer_name = f"backend-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

    async def start(self) -> None:
        if self._running:
            return

        self._redis = redis.from_url(settings.REDIS_URL, decode_responses=False)
        await self._redis.ping()

        # Connect to MongoDB via mongo_service
        await mongo_service.connect()
        
        await self._ensure_consumer_group()

        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_loop(), name="transcription-results-consumer")

        logger.info(
            "Started transcription results consumer "
            f"stream={self._stream_key} group={self._group_name} consumer={self._consumer_name}"
        )

    async def stop(self) -> None:
        self._running = False

        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

        if self._redis:
            await self._redis.close()
            self._redis = None

        # Disconnect MongoDB via mongo_service
        await mongo_service.disconnect()

    async def _ensure_consumer_group(self) -> None:
        assert self._redis is not None

        try:
            await self._redis.xgroup_create(
                self._stream_key,
                self._group_name,
                id="0",
                mkstream=True,
            )
            logger.info(f"Created consumer group {self._group_name} for {self._stream_key}")
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _consume_loop(self) -> None:
        assert self._redis is not None

        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    groupname=self._group_name,
                    consumername=self._consumer_name,
                    streams={self._stream_key: ">"},
                    count=10,
                    block=settings.REDIS_SAVE_READ_BLOCK_MS,
                )

                if not messages:
                    continue

                for _, entries in messages:
                    for message_id, raw in entries:
                        message_id_str = message_id.decode() if isinstance(message_id, bytes) else str(message_id)
                        try:
                            parsed = self._parse_message(raw)
                            await self._persist_chunk(parsed)
                            await self._redis.xack(self._stream_key, self._group_name, message_id)
                        except Exception as exc:
                            logger.error(
                                f"Failed handling message {message_id_str} from {self._stream_key}: {exc}",
                                exc_info=True,
                            )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Consumer loop error: {exc}", exc_info=True)
                await asyncio.sleep(1)

    def _parse_message(self, raw: dict[bytes, bytes]) -> SaveTranscriptionChunkMessage:
        decoded = {
            (k.decode() if isinstance(k, bytes) else str(k)): (v.decode() if isinstance(v, bytes) else str(v))
            for k, v in raw.items()
        }

        segments_raw = decoded.get("segments", "[]")
        try:
            segments = json.loads(segments_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid segments JSON: {exc}") from exc

        payload = {
            "task_id": decoded.get("task_id", ""),
            "track_ref_id": decoded.get("track_ref_id", ""),
            "chunk_index": int(decoded.get("chunk_index", 0)),
            "start_time": float(decoded.get("start_time", 0)),
            "end_time": float(decoded.get("end_time", 0)),
            "item_count": int(decoded.get("item_count", 0)),
            "is_final": str(decoded.get("is_final", "False")).lower() == "true",
            "status": decoded.get("status", "pending"),
            "segments": segments,
        }

        return SaveTranscriptionChunkMessage.model_validate(payload)

    async def _persist_chunk(self, chunk: SaveTranscriptionChunkMessage) -> None:
        """Persist transcription chunk to MongoDB."""
        try:
            job_id = await mongo_service.upsert_job(
                track_ref_id=chunk.track_ref_id,
                status=chunk.status,
            )

            # Save segments if any
            if chunk.segments:
                await mongo_service.save_segments(
                    transcription_job_id=job_id,
                    chunk_index=chunk.chunk_index,
                    segments=chunk.segments,
                )
            
            # Update job metadata
            await mongo_service.update_job(
                job_id=job_id,
                status=chunk.status,
            )
            
        except Exception as e:
            logger.error(f"Error persisting chunk for {chunk.track_ref_id}: {e}", exc_info=True)
            raise


transcription_results_consumer = TranscriptionResultsConsumer()
