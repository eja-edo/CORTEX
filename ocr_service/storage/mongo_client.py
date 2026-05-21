"""
MongoDB Client for OCR Service

Handles OCR job and frame operations in MongoDB.
Simplified from backend's MongoOCRService - no event loop workaround needed.
"""

from datetime import datetime
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ReplaceOne, ReturnDocument

from config import settings


class MongoOCRWriter:
    """MongoDB client for OCR operations (write-only for Phase 1)."""
    
    OCR_JOBS_COLLECTION = "ocr_jobs"
    OCR_FRAMES_COLLECTION = "ocr_frames"
    STT_JOBS_COLLECTION = "transcription_jobs"
    
    def __init__(self) -> None:
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._connected = False
    
    async def connect(self) -> None:
        """Connect to MongoDB."""
        if self._connected:
            return
        
        self._client = AsyncIOMotorClient(settings.mongodb_url)
        await self._client.admin.command("ping")
        self._db = self._client[settings.mongodb_db]
        await self._create_indexes()
        self._connected = True
    
    async def disconnect(self) -> None:
        """Disconnect from MongoDB."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._connected = False
    
    async def _create_indexes(self) -> None:
        """Create necessary indexes (idempotent)."""
        db = self._db
        
        await db[self.OCR_JOBS_COLLECTION].create_index(
            [("asset_id", 1)], unique=True, name="uq_ocr_jobs_asset_id"
        )
        await db[self.OCR_JOBS_COLLECTION].create_index(
            [("user_id", 1), ("status", 1)], name="ix_ocr_jobs_user_status"
        )
        
        await db[self.OCR_FRAMES_COLLECTION].create_index(
            [("asset_id", 1), ("timestamp_sec", 1)],
            name="ix_ocr_frames_asset_timestamp",
        )
        await db[self.OCR_FRAMES_COLLECTION].create_index(
            [("asset_id", 1), ("frame_id", 1)],
            unique=True,
            name="uq_ocr_frames_asset_frame",
        )
    
    async def upsert_ocr_job(
        self,
        asset_id: str,
        user_id: str,
        task_id: str,
        status: str = "processing",
    ) -> str:
        """Create or update an OCR job record."""
        if not self._connected:
            await self.connect()
        
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
        """Update OCR job statistics."""
        if not self._connected:
            await self.connect()
        
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
    
    async def save_ocr_frames(
        self,
        asset_id: str,
        user_id: str,
        frames: list[dict],
    ) -> int:
        """Save OCR frames to MongoDB (upsert by asset_id + frame_id)."""
        if not self._connected:
            await self.connect()
        
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
    
    async def has_transcript(self, asset_id: str) -> bool:
        """Check if a transcript exists for the given asset."""
        if not self._connected:
            await self.connect()
        
        job = await self._db[self.STT_JOBS_COLLECTION].find_one(
            {"track_ref_id": asset_id},
            {"_id": 1},
        )
        return job is not None
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to MongoDB."""
        return self._connected
