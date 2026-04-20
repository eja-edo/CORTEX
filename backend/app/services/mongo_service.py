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


# Singleton instance
mongo_service = MongoTranscriptionService()
