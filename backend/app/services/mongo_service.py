"""
MongoDB Service for Transcription Results

Handles all MongoDB operations for storing transcription segments and job metadata.
Encapsulates collection names and indexes within the service.
"""

from datetime import datetime
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ReplaceOne, ReturnDocument

from app.config import settings
from app.mongo_schemas import (
    MongoSegmentDocument,
    MongoTranscriptionJobDocument,
    TranscriptionSegmentInput,
    OCRFrameDocument,
    OCRJobDocument,
    OCRProcessedDocument,
    KnowledgeUnitDocument,
    AssetKnowledgeSummary,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MongoTranscriptionService:
    """
    Service for MongoDB operations on transcription data.
    
    Manages:
    - Connection to MongoDB
    - Collection names (hardcoded, not in settings)
    - Index management
    - Document persistence (segments and jobs)
    """
    
    # Collection names hardcoded in service
    SEGMENTS_COLLECTION = "transcription_segments"
    JOBS_COLLECTION = "transcription_jobs"
    
    def __init__(self) -> None:
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._connected = False
    
    async def connect(self) -> None:
        """
        Establish connection to MongoDB and initialize indexes.
        
        Raises:
            ConnectionError: If unable to connect to MongoDB
        """
        if self._connected:
            logger.debug("Already connected to MongoDB")
            return
        
        try:
            self._client = AsyncIOMotorClient(settings.MONGODB_URL)
            
            # Test connection
            await self._client.admin.command("ping")
            
            # Get database
            self._db = self._client[settings.MONGODB_DB_NAME]
            
            # Create indexes
            await self._create_indexes()
            
            self._connected = True
            logger.info(
                f"✅ Connected to MongoDB: {settings.MONGODB_URL} / {settings.MONGODB_DB_NAME}"
            )
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self._client = None
            self._db = None
            raise ConnectionError(f"MongoDB connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Close MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._connected = False
            logger.info("MongoDB connection closed")
    
    async def _create_indexes(self) -> None:
        """Create necessary indexes for efficient queries."""
        if self._db is None:
            raise RuntimeError("Not connected to MongoDB")
        
        try:
            # Backfill transcription_job_id from track_ref_id for existing data.
            jobs_cursor = self._db[self.JOBS_COLLECTION].find(
                {"track_ref_id": {"$exists": True, "$ne": ""}},
                {"_id": 1, "track_ref_id": 1},
            )
            async for job in jobs_cursor:
                await self._db[self.SEGMENTS_COLLECTION].update_many(
                    {
                        "track_ref_id": job["track_ref_id"],
                        "transcription_job_id": {"$exists": False},
                    },
                    {"$set": {"transcription_job_id": str(job["_id"])}},
                )

            # Remove deprecated segment fields.
            await self._db[self.SEGMENTS_COLLECTION].update_many(
                {},
                {
                    "$unset": {
                        "track_ref_id": "",
                        "chunk_index": "",
                        "source_task_id": "",
                        "source_message_id": "",
                    }
                },
            )

            # Drop old unique index based on legacy keys.
            try:
                await self._db[self.SEGMENTS_COLLECTION].drop_index("uq_track_chunk_segment")
            except Exception:
                pass

            # Segments index: query by owning transcription job.
            await self._db[self.SEGMENTS_COLLECTION].create_index(
                [("transcription_job_id", 1)],
                name="ix_segments_transcription_job_id",
            )
            logger.debug(f"✓ Index created on {self.SEGMENTS_COLLECTION}")
            
            # Jobs index: unique constraint on track_ref_id
            await self._db[self.JOBS_COLLECTION].create_index(
                [("track_ref_id", 1)],
                unique=True,
                name="uq_track_ref_id",
            )
            logger.debug(f"✓ Index created on {self.JOBS_COLLECTION}")
            
        except Exception as e:
            logger.warning(f"Error creating indexes: {e}")
    
    async def save_segments(
        self,
        transcription_job_id: str,
        chunk_index: int,
        segments: list[TranscriptionSegmentInput],
    ) -> int:
        """
        Save transcription segments to MongoDB.
        
        Args:
            transcription_job_id: _id of transcription_jobs document
            chunk_index: Batch index number (used for idempotent segment IDs)
            segments: List of TranscriptionSegmentInput models with start, end, text, confidence, speaker_label
        
        Returns:
            Number of segments inserted/updated
        
        Raises:
            RuntimeError: If not connected to MongoDB
        """
        if self._db is None:
            raise RuntimeError("Not connected to MongoDB")
        
        if not segments:
            return 0
        
        now = datetime.utcnow()
        ops = []
        
        for idx, seg in enumerate(segments):
            doc = MongoSegmentDocument(
                transcription_job_id=transcription_job_id,
                segment_index=idx,
                start_time_sec=seg.start,
                end_time_sec=seg.end,
                text=seg.text,
                confidence=seg.confidence,
                speaker_label=seg.speaker_label,
                created_at=now,
            )
            data = doc.model_dump()
            segment_doc_id = f"{transcription_job_id}:{chunk_index}:{idx}"
            data["_id"] = segment_doc_id
            ops.append(
                ReplaceOne(
                    {"_id": segment_doc_id},
                    data,
                    upsert=True,
                )
            )
        
        if ops:
            result = await self._db[self.SEGMENTS_COLLECTION].bulk_write(ops, ordered=False)
            return len(ops)
        
        return 0
    
    async def upsert_job(self, track_ref_id: str, status: str) -> str:
        """Create/update job by track_ref_id and return the Mongo _id as string."""
        if self._db is None:
            raise RuntimeError("Not connected to MongoDB")

        now = datetime.utcnow()
        result = await self._db[self.JOBS_COLLECTION].find_one_and_update(
            {"track_ref_id": track_ref_id},
            {
                "$set": {
                    "status": status,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "track_ref_id": track_ref_id,
                    "total_segments": 0,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise RuntimeError(f"Failed to upsert transcription job for {track_ref_id}")

        return str(result["_id"])

    async def update_job(self, job_id: str, status: str) -> None:
        """
        Update transcription job metadata.
        
        Counts total segments in MongoDB to get accurate total.
        
        Args:
            job_id: _id of transcription_jobs document
            status: Job status (pending, processing, completed, failed)
        
        Raises:
            RuntimeError: If not connected to MongoDB
        """
        if self._db is None:
            raise RuntimeError("Not connected to MongoDB")

        total_segments = await self._db[self.SEGMENTS_COLLECTION].count_documents(
            {"transcription_job_id": job_id}
        )

        existing = await self._db[self.JOBS_COLLECTION].find_one({"_id": ObjectId(job_id)})
        if existing is None:
            raise RuntimeError(f"Transcription job not found: {job_id}")

        job_doc = MongoTranscriptionJobDocument(
            track_ref_id=existing["track_ref_id"],
            total_segments=total_segments,
            status=status,
            updated_at=datetime.utcnow(),
        )

        await self._db[self.JOBS_COLLECTION].replace_one(
            {"_id": ObjectId(job_id)},
            {"_id": ObjectId(job_id), **job_doc.model_dump()},
            upsert=False,
        )
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to MongoDB."""
        return self._connected


# ══════════════════════════════════════════════════════════════════════════════
# OCR Service
# ══════════════════════════════════════════════════════════════════════════════


class MongoOCRService:
    """
    Service for OCR and LLM knowledge data in MongoDB.

    Collections:
      ocr_jobs           — one doc per asset/task
      ocr_frames         — raw frames after layout reconstruction
      ocr_processed      — windowed frames after Gemini processing
      knowledge_units    — atomic knowledge facts
      asset_knowledge    — session-level summaries
    """

    OCR_JOBS_COLLECTION = "ocr_jobs"
    OCR_FRAMES_COLLECTION = "ocr_frames"
    OCR_PROCESSED_COLLECTION = "ocr_processed"
    KNOWLEDGE_UNITS_COLLECTION = "knowledge_units"
    ASSET_KNOWLEDGE_COLLECTION = "asset_knowledge"

    def __init__(self) -> None:
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._connected = False

    async def connect(self) -> None:
        if self._connected:
            return
        self._client = AsyncIOMotorClient(settings.MONGODB_URL)
        await self._client.admin.command("ping")
        self._db = self._client[settings.MONGODB_DB_NAME]
        await self._create_indexes()
        self._connected = True
        logger.info("✅ MongoOCRService connected")

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._connected = False

    async def _create_indexes(self) -> None:
        db = self._db

        # ocr_jobs: unique per asset_id
        await db[self.OCR_JOBS_COLLECTION].create_index(
            [("asset_id", 1)], unique=True, name="uq_ocr_jobs_asset_id"
        )
        await db[self.OCR_JOBS_COLLECTION].create_index(
            [("user_id", 1), ("status", 1)], name="ix_ocr_jobs_user_status"
        )
        await db[self.OCR_JOBS_COLLECTION].create_index(
            [("llm_status", 1)], name="ix_ocr_jobs_llm_status"
        )

        # ocr_frames: query by asset + timestamp
        await db[self.OCR_FRAMES_COLLECTION].create_index(
            [("asset_id", 1), ("timestamp_sec", 1)],
            name="ix_ocr_frames_asset_timestamp",
        )
        await db[self.OCR_FRAMES_COLLECTION].create_index(
            [("asset_id", 1), ("frame_id", 1)],
            unique=True,
            name="uq_ocr_frames_asset_frame",
        )

        # ocr_processed: query by asset
        await db[self.OCR_PROCESSED_COLLECTION].create_index(
            [("asset_id", 1), ("start_timestamp_sec", 1)],
            name="ix_ocr_processed_asset_time",
        )
        await db[self.OCR_PROCESSED_COLLECTION].create_index(
            [("user_id", 1), ("status", 1)],
            name="ix_ocr_processed_user_status",
        )

        # knowledge_units: dedup + search
        await db[self.KNOWLEDGE_UNITS_COLLECTION].create_index(
            [("content_hash", 1)], name="ix_knowledge_units_hash"
        )
        await db[self.KNOWLEDGE_UNITS_COLLECTION].create_index(
            [("user_id", 1), ("unit_type", 1)],
            name="ix_knowledge_units_user_type",
        )
        await db[self.KNOWLEDGE_UNITS_COLLECTION].create_index(
            [("asset_id", 1)], name="ix_knowledge_units_asset"
        )

        # asset_knowledge: unique per asset
        await db[self.ASSET_KNOWLEDGE_COLLECTION].create_index(
            [("asset_id", 1)], unique=True, name="uq_asset_knowledge_asset"
        )

    # ── OCR Job CRUD ─────────────────────────────────────────────────────────

    async def upsert_ocr_job(
        self,
        asset_id: str,
        user_id: str,
        task_id: str,
        workspace_id: Optional[str] = None,
        status: str = "processing",
    ) -> str:
        """Create or update OCR job. Returns _id as string."""
        now = datetime.utcnow()
        result = await self._db[self.OCR_JOBS_COLLECTION].find_one_and_update(
            {"asset_id": asset_id},
            {
                "$set": {
                    "status": status,
                    "task_id": task_id,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "asset_id": asset_id,
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "total_frames": 0,
                    "non_empty_frames": 0,
                    "llm_status": "pending",
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return str(result["_id"])

    async def update_ocr_job_stats(
        self,
        job_id: str,
        total_frames: int,
        non_empty_frames: int,
        status: str,
        output_dir: Optional[str] = None,
    ) -> None:
        update = {
            "$set": {
                "status": status,
                "total_frames": total_frames,
                "non_empty_frames": non_empty_frames,
                "updated_at": datetime.utcnow(),
            }
        }
        if output_dir:
            update["$set"]["output_dir"] = output_dir
        await self._db[self.OCR_JOBS_COLLECTION].update_one(
            {"_id": ObjectId(job_id)}, update
        )

    async def set_llm_status(self, job_id: str, llm_status: str) -> None:
        await self._db[self.OCR_JOBS_COLLECTION].update_one(
            {"_id": ObjectId(job_id)},
            {
                "$set": {
                    "llm_status": llm_status,
                    "llm_processed_at": (
                        datetime.utcnow() if llm_status == "completed" else None
                    ),
                    "updated_at": datetime.utcnow(),
                }
            },
        )

    # ── OCR Frames ───────────────────────────────────────────────────────────

    async def save_ocr_frames(
        self,
        asset_id: str,
        user_id: str,
        frames: list[dict],  # list of dicts from cleaned_metadata.json
    ) -> int:
        """
        Bulk upsert OCR frames. Idempotent based on (asset_id, frame_id).

        Args:
            frames: List of dicts with keys: frame_id, timestamp, processed_text,
                    ssim_score, changed, theme, regions, ui_regions
        Returns:
            Number of frames upserted
        """
        if not frames:
            return 0

        now = datetime.utcnow()
        ops = []

        for frame in frames:
            doc = {
                "asset_id": asset_id,
                "user_id": user_id,
                "frame_id": frame["frame_id"],
                "timestamp_sec": float(frame["timestamp"]),
                "processed_text": frame.get("processed_text", ""),
                "ssim_score": frame.get("ssim_score"),
                "changed": frame.get("changed", True),
                "theme": frame.get("theme"),
                "raw_regions": frame.get("regions", []),
                "ui_regions": frame.get("ui_regions", []),
                "created_at": now,
            }
            ops.append(
                ReplaceOne(
                    {"asset_id": asset_id, "frame_id": frame["frame_id"]},
                    doc,
                    upsert=True,
                )
            )

        if ops:
            await self._db[self.OCR_FRAMES_COLLECTION].bulk_write(ops, ordered=False)

        return len(ops)

    async def get_ocr_frames(
        self, asset_id: str, skip_empty: bool = True
    ) -> list[dict]:
        """Get all frames of an asset, sorted by timestamp."""
        query: dict = {"asset_id": asset_id}
        if skip_empty:
            query["processed_text"] = {"$ne": ""}

        cursor = self._db[self.OCR_FRAMES_COLLECTION].find(
            query,
            sort=[("timestamp_sec", 1)],
        )
        return await cursor.to_list(length=None)

    # ── OCR Processed (Gemini windows) ───────────────────────────────────────

    async def save_ocr_processed(
        self,
        asset_id: str,
        user_id: str,
        ocr_job_id: str,
        window: dict,
    ) -> str:
        """Save a processed window. Returns _id."""
        now = datetime.utcnow()
        doc = {
            "asset_id": asset_id,
            "user_id": user_id,
            "ocr_job_id": ocr_job_id,
            "start_timestamp_sec": window["start_timestamp_sec"],
            "end_timestamp_sec": window["end_timestamp_sec"],
            "frame_ids": window.get("frame_ids", []),
            "combined_text": window.get("combined_text", ""),
            "analysis": window.get("analysis"),
            "llm_model": window.get("llm_model"),
            "tokens_used": window.get("tokens_used", 0),
            "cost_usd": window.get("cost_usd", 0.0),
            "status": window.get("status", "completed"),
            "error_message": window.get("error_message"),
            "created_at": now,
            "processed_at": now if window.get("status") == "completed" else None,
        }
        result = await self._db[self.OCR_PROCESSED_COLLECTION].insert_one(doc)
        return str(result.inserted_id)

    async def get_ocr_processed(self, asset_id: str) -> list[dict]:
        """Get all processed windows of an asset."""
        cursor = self._db[self.OCR_PROCESSED_COLLECTION].find(
            {"asset_id": asset_id, "status": "completed"},
            sort=[("start_timestamp_sec", 1)],
        )
        return await cursor.to_list(length=None)

    # ── Knowledge Units ──────────────────────────────────────────────────────

    async def save_knowledge_unit(self, unit: dict) -> bool:
        """
        Save a knowledge unit. Deduplicates based on content_hash.
        Returns True if inserted (new), False if already exists.
        """
        existing = await self._db[self.KNOWLEDGE_UNITS_COLLECTION].find_one(
            {"content_hash": unit["content_hash"], "deleted_at": None}
        )
        if existing:
            return False

        now = datetime.utcnow()
        await self._db[self.KNOWLEDGE_UNITS_COLLECTION].insert_one(
            {
                **unit,
                "created_at": now,
            }
        )
        return True

    async def get_knowledge_units(
        self,
        user_id: str,
        asset_id: Optional[str] = None,
        unit_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        query: dict = {"user_id": user_id, "deleted_at": None}
        if asset_id:
            query["asset_id"] = asset_id
        if unit_type:
            query["unit_type"] = unit_type

        cursor = self._db[self.KNOWLEDGE_UNITS_COLLECTION].find(
            query,
            sort=[("created_at", -1)],
            limit=limit,
        )
        return await cursor.to_list(length=limit)

    # ── Asset Knowledge Summary ───────────────────────────────────────────────

    async def upsert_asset_knowledge(self, asset_id: str, summary: dict) -> str:
        now = datetime.utcnow()
        result = await self._db[self.ASSET_KNOWLEDGE_COLLECTION].find_one_and_update(
            {"asset_id": asset_id},
            {
                "$set": {
                    **summary,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return str(result["_id"])

    async def get_asset_knowledge(self, asset_id: str) -> Optional[dict]:
        return await self._db[self.ASSET_KNOWLEDGE_COLLECTION].find_one(
            {"asset_id": asset_id}
        )

    @property
    def is_connected(self) -> bool:
        return self._connected


# Singleton instances
mongo_service = MongoTranscriptionService()
mongo_ocr_service = MongoOCRService()
