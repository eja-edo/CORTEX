

**1. OCR Pipeline đã hoàn chỉnh hơn nhiều:**
- `ocr_processor_worker.py` — worker consume Redis stream, chạy `run_pipeline` + `process_metadata_file`, output ra `cleaned_metadata.json`
- `video_pipeline_service.py` — pipeline thực tế, output `metadata.json` với `regions: [{bbox, text}]` mỗi frame
- `layout_processor.py` — reconstruct layout từ bounding boxes thành text có cấu trúc

**2. Output hiện tại của OCR worker là:**
```json
// cleaned_metadata.json
[
  {
    "frame_id": 0,
    "timestamp": 1.0,
    "processed_text": "Error: connection refused\n  docker run -p 5432"
  }
]
```
→ Đây là text đã qua layout reconstruction, **chưa được lưu vào DB nào cả** — worker chỉ log summary rồi bỏ

**3. MongoDB đang dùng cho transcription** (STT), không phải OCR:
- Collections: `transcription_segments`, `transcription_jobs`
- Schema trong `mongo_schemas.py` chỉ có `TranscriptionSegmentInput`, `MongoTranscriptionJobDocument`

**4. PostgreSQL Segments table** — OCR kết quả hiện tại **không được lưu vào đây**

**5. Trigger chain đã có:**
```
Upload complete → enqueue_video_processing (Redis) → OCRProcessorWorker → run_pipeline + process_metadata_file → cleaned_metadata.json (chỉ lưu file, không persist DB)
```

**Gap thực sự cần giải quyết:**

```
cleaned_metadata.json → [MISSING] → MongoDB OCR collection → [MISSING] → Gemini LLM → [MISSING] → Structured Knowledge
```

---

# 🗺️ Plan Cập Nhật — Chính Xác Theo Codebase Thực

## Tổng quan gap analysis

```
✅ Đã có:  Upload → Redis → OCRWorker → run_pipeline → cleaned_metadata.json
❌ Thiếu:  cleaned_metadata.json → MongoDB (persist OCR raw)
❌ Thiếu:  MongoDB OCR → Gemini processing
❌ Thiếu:  Gemini output → MongoDB (persist structured knowledge)
❌ Thiếu:  MongoDB schema cho OCR data
```

---

## PHASE 1: Persist OCR Output vào MongoDB

### 1.1 — Mở rộng MongoDB Schema (`mongo_schemas.py`)

Thêm vào file hiện tại — **không thay đổi schema cũ**, chỉ thêm mới:

```python
# ── OCR Frame Document ──────────────────────────────────────────────
class OCRFrameDocument(BaseModel):
    """Một frame đã qua layout reconstruction."""
    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr                    # UUID của asset trong PostgreSQL
    user_id: StrictStr
    workspace_id: Optional[StrictStr] = None

    frame_id: StrictInt                    # thứ tự frame
    timestamp_sec: StrictFloat             # thời điểm trong video (giây)
    processed_text: StrictStr              # output của layout_processor
    ssim_score: Optional[float] = None     # từ metadata.json gốc
    changed: bool = True                   # frame có thay đổi so với trước không
    theme: Optional[StrictStr] = None      # "dark" | "light"

    # Raw regions từ pipeline (giữ lại để debug/reprocess)
    raw_regions: list[dict] = Field(default_factory=list)  # [{bbox, text}]
    ui_regions: list[list[int]] = Field(default_factory=list)

    created_at: datetime


class OCRJobDocument(BaseModel):
    """Metadata của một OCR processing job cho một asset."""
    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    workspace_id: Optional[StrictStr] = None
    task_id: StrictStr                     # OCRProcessorTask.task_id

    status: Literal["pending", "processing", "completed", "failed"]
    total_frames: int = 0
    non_empty_frames: int = 0
    output_dir: Optional[StrictStr] = None

    # LLM processing state
    llm_status: Literal["pending", "processing", "completed", "failed", "skipped"] = "pending"
    llm_processed_at: Optional[datetime] = None

    updated_at: datetime


# ── LLM Processed Document ─────────────────────────────────────────
class LLMFrameAnalysis(BaseModel):
    """Kết quả Gemini cho một frame/batch."""
    model_config = ConfigDict(extra="allow")

    screen_type: Optional[str] = None
    application: Optional[str] = None
    user_intent: Optional[str] = None
    knowledge_value: float = 0.0
    summary: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)
    searchable_keywords: list[str] = Field(default_factory=list)


class OCRProcessedDocument(BaseModel):
    """
    Một window (batch frames ~30s) sau khi Gemini xử lý.
    Đây là unit chính để search và query.
    """
    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    ocr_job_id: StrictStr                  # _id của OCRJobDocument

    # Time range của window này
    start_timestamp_sec: float
    end_timestamp_sec: float
    frame_ids: list[int] = Field(default_factory=list)

    # Raw text (concat của các frames trong window)
    combined_text: StrictStr

    # Gemini output
    analysis: Optional[LLMFrameAnalysis] = None
    llm_model: Optional[str] = None
    tokens_used: int = 0
    cost_usd: float = 0.0

    status: Literal["pending", "processing", "completed", "failed"] = "pending"
    error_message: Optional[str] = None

    created_at: datetime
    processed_at: Optional[datetime] = None


class KnowledgeUnitDocument(BaseModel):
    """
    Atomic knowledge fact — extracted từ OCR content bởi Gemini.
    Cross-asset searchable.
    """
    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    ocr_processed_id: StrictStr            # ref đến OCRProcessedDocument

    unit_type: Literal["fact", "error", "code_pattern", "command", "reference"]
    content: StrictStr
    context: Optional[str] = None
    confidence: float = 1.0

    # Type-specific
    error_type: Optional[str] = None
    resolution: Optional[str] = None
    language: Optional[str] = None
    url: Optional[str] = None
    platform: Optional[str] = None
    reusability: float = 0.5

    content_hash: StrictStr               # sha256(user_id + content) cho dedup

    is_verified: bool = False
    deleted_at: Optional[datetime] = None
    created_at: datetime


class AssetKnowledgeSummary(BaseModel):
    """Session-level synthesis của toàn bộ asset."""
    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    ocr_job_id: StrictStr

    session_title: Optional[str] = None
    primary_technology: Optional[str] = None
    difficulty_level: Optional[str] = None
    overall_summary: Optional[str] = None

    tags: list[str] = Field(default_factory=list)
    workflow: list[dict] = Field(default_factory=list)
    problems_encountered: list[dict] = Field(default_factory=list)
    solutions_found: list[dict] = Field(default_factory=list)
    knowledge_gained: list[str] = Field(default_factory=list)

    llm_model: Optional[str] = None
    tokens_used: int = 0
    cost_usd: float = 0.0

    status: Literal["pending", "processing", "completed", "failed"] = "pending"
    synthesized_at: Optional[datetime] = None
    created_at: datetime
```

### 1.2 — Mở rộng `mongo_service.py`

Thêm class `MongoOCRService` vào file — **không chạm vào `MongoTranscriptionService`**:

```python
class MongoOCRService:
    """
    Service cho OCR và LLM knowledge data trong MongoDB.
    
    Collections:
      ocr_jobs           — một doc per asset/task
      ocr_frames         — raw frames sau layout reconstruction
      ocr_processed      — windowed frames sau Gemini processing
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
            name="ix_ocr_frames_asset_timestamp"
        )
        await db[self.OCR_FRAMES_COLLECTION].create_index(
            [("asset_id", 1), ("frame_id", 1)],
            unique=True, name="uq_ocr_frames_asset_frame"
        )

        # ocr_processed: query by asset
        await db[self.OCR_PROCESSED_COLLECTION].create_index(
            [("asset_id", 1), ("start_timestamp_sec", 1)],
            name="ix_ocr_processed_asset_time"
        )
        await db[self.OCR_PROCESSED_COLLECTION].create_index(
            [("user_id", 1), ("status", 1)],
            name="ix_ocr_processed_user_status"
        )

        # knowledge_units: dedup + search
        await db[self.KNOWLEDGE_UNITS_COLLECTION].create_index(
            [("content_hash", 1)], name="ix_knowledge_units_hash"
        )
        await db[self.KNOWLEDGE_UNITS_COLLECTION].create_index(
            [("user_id", 1), ("unit_type", 1)],
            name="ix_knowledge_units_user_type"
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
        """Tạo hoặc update OCR job. Trả về _id dạng string."""
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
                    "created_at": now,   # <-- thêm created_at khi insert
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
            {"$set": {
                "llm_status": llm_status,
                "llm_processed_at": datetime.utcnow() if llm_status == "completed" else None,
                "updated_at": datetime.utcnow(),
            }},
        )

    # ── OCR Frames ───────────────────────────────────────────────────────────

    async def save_ocr_frames(
        self,
        asset_id: str,
        user_id: str,
        frames: list[dict],  # list dicts từ cleaned_metadata.json
    ) -> int:
        """
        Bulk upsert OCR frames. Idempotent dựa trên (asset_id, frame_id).
        
        Args:
            frames: List of dicts với keys: frame_id, timestamp, processed_text,
                    ssim_score, changed, theme, regions, ui_regions
        Returns:
            Số frames đã upsert
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
            await self._db[self.OCR_FRAMES_COLLECTION].bulk_write(
                ops, ordered=False
            )

        return len(ops)

    async def get_ocr_frames(
        self, asset_id: str, skip_empty: bool = True
    ) -> list[dict]:
        """Lấy tất cả frames của một asset, sort theo timestamp."""
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
        """Lưu một processed window. Trả về _id."""
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
        """Lấy tất cả processed windows của asset."""
        cursor = self._db[self.OCR_PROCESSED_COLLECTION].find(
            {"asset_id": asset_id, "status": "completed"},
            sort=[("start_timestamp_sec", 1)],
        )
        return await cursor.to_list(length=None)

    # ── Knowledge Units ──────────────────────────────────────────────────────

    async def save_knowledge_unit(self, unit: dict) -> bool:
        """
        Lưu một knowledge unit. Dedup dựa trên content_hash.
        Trả về True nếu inserted (mới), False nếu đã tồn tại.
        """
        existing = await self._db[self.KNOWLEDGE_UNITS_COLLECTION].find_one(
            {"content_hash": unit["content_hash"], "deleted_at": None}
        )
        if existing:
            return False

        now = datetime.utcnow()
        await self._db[self.KNOWLEDGE_UNITS_COLLECTION].insert_one({
            **unit,
            "created_at": now,
        })
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


# Singleton
mongo_ocr_service = MongoOCRService()
```

---

## PHASE 2: Wiring vào `ocr_processor_worker.py`

Đây là điểm quan trọng nhất. Hiện tại worker đang **bỏ kết quả đi** sau khi xử lý:

```python
# HIỆN TẠI (dòng cuối _run_pipeline_and_layout):
return {
    "output_dir": str(output_dir),
    "metadata_frames": len(processed_data),
    ...
}
# → Chỉ log, không persist gì cả ❌
```

Cần sửa `_process_task` để persist:

```python
async def _process_task(self, task: OCRProcessorTask) -> None:
    """Process task: pipeline → persist OCR frames → trigger LLM."""
    
    if not task.enable_ocr:
        logger.info(f"Skipping {task.task_id}: enable_ocr=False")
        return

    # ── Bước 1: Upsert OCR job record ─────────────────────────────
    from app.services.mongo_service import mongo_ocr_service
    
    if not mongo_ocr_service.is_connected:
        await mongo_ocr_service.connect()

    ocr_job_id = await mongo_ocr_service.upsert_ocr_job(
        asset_id=task.video_id or task.task_id,
        user_id=task.user_id or "",
        task_id=task.task_id,
        workspace_id=task.workspace_id,
        status="processing",
    )

    # ── Bước 2: Chạy pipeline trong thread pool ───────────────────
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

    # ── Bước 3: Đọc cleaned_metadata.json và persist frames ──────
    import json as _json
    from pathlib import Path as _Path

    cleaned_path = _Path(summary["cleaned_metadata_path"])
    with open(cleaned_path, "r", encoding="utf-8") as f:
        cleaned_frames: list[dict] = _json.load(f)

    # Cần merge với metadata.json gốc để có ssim_score, changed, regions, ui_regions
    metadata_path = _Path(summary["output_dir"]) / "metadata.json"
    with open(metadata_path, "r", encoding="utf-8") as f:
        raw_metadata: list[dict] = _json.load(f)

    # Build frame index từ raw_metadata
    raw_by_frame_id = {item["frame_id"]: item for item in raw_metadata}

    # Merge cleaned text vào raw metadata
    merged_frames = []
    for item in cleaned_frames:
        raw = raw_by_frame_id.get(item["frame_id"], {})
        merged_frames.append({
            "frame_id": item["frame_id"],
            "timestamp": item["timestamp"],
            "processed_text": item.get("processed_text", ""),
            "ssim_score": raw.get("ssim_score"),
            "changed": raw.get("changed", True),
            "theme": raw.get("theme"),
            "regions": raw.get("regions", []),
            "ui_regions": raw.get("ui_regions", []),
        })

    asset_id = str(task.video_id) if task.video_id else task.task_id
    
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
        f"total={len(merged_frames)}, non_empty={non_empty}"
    )

    # ── Bước 4: Trigger LLM post-processing qua Redis ────────────
    if non_empty > 0:
        await self._enqueue_llm_processing(
            asset_id=asset_id,
            user_id=task.user_id or "",
            ocr_job_id=ocr_job_id,
            task_context=task.job_context or {},
        )

async def _enqueue_llm_processing(
    self,
    asset_id: str,
    user_id: str,
    ocr_job_id: str,
    task_context: dict,
) -> None:
    """Enqueue LLM processing task vào Redis stream."""
    from app.services.redis.llm_processor_task import enqueue_llm_processing
    
    await enqueue_llm_processing(
        asset_id=asset_id,
        user_id=user_id,
        ocr_job_id=ocr_job_id,
        job_context=task_context,
    )
    logger.info(f"📤 LLM processing enqueued for asset={asset_id}")
```

---

## PHASE 3: LLM Processing Layer

### 3.1 — Redis Task cho LLM

Tạo `backend/app/services/redis/llm_processor_task.py`:

```python
import json, time, uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional
from app.services.redis.base_producer import RedisStreamProducerBase

LLM_PROCESSOR_STREAM_KEY = "llm:processor:stream"


@dataclass
class LLMProcessorTask:
    priority: int = 5
    retry_count: int = 0
    task_id: str = field(
        default_factory=lambda: f"llm_task_{int(time.time()*1000)}_{uuid.uuid4().hex[:4]}"
    )
    created_at: float = field(default_factory=time.time)

    asset_id: str = ""
    user_id: str = ""
    ocr_job_id: str = ""
    job_context: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "priority": str(self.priority),
            "retry_count": str(self.retry_count),
            "created_at": str(self.created_at),
            "asset_id": self.asset_id,
            "user_id": self.user_id,
            "ocr_job_id": self.ocr_job_id,
            "job_context": json.dumps(self.job_context or {}),
        }


class LLMProcessorProducer(RedisStreamProducerBase[LLMProcessorTask]):
    _instance: ClassVar[Optional["LLMProcessorProducer"]] = None

    def __init__(self):
        super().__init__(stream_key=LLM_PROCESSOR_STREAM_KEY)

    @classmethod
    def get_instance(cls) -> "LLMProcessorProducer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


async def enqueue_llm_processing(
    asset_id: str,
    user_id: str,
    ocr_job_id: str,
    job_context: Optional[dict] = None,
) -> str:
    producer = LLMProcessorProducer.get_instance()
    task = LLMProcessorTask(
        asset_id=asset_id,
        user_id=user_id,
        ocr_job_id=ocr_job_id,
        job_context=job_context,
    )
    return await producer.enqueue(task)
```

### 3.2 — Gemini Service

Tạo `backend/app/services/llm_processing.py` — giữ đúng như plan trước, chỉ thêm config lấy từ `settings`:

```python
# Trong GeminiProcessingService.__init__:
def __init__(self) -> None:
    self.api_key = settings.GEMINI_API_KEY
    self.timeout = 60
    self.DEFAULT_MODEL = settings.GEMINI_DEFAULT_MODEL      # "gemini-1.5-flash"
    self.SYNTHESIS_MODEL = settings.GEMINI_SYNTHESIS_MODEL  # "gemini-1.5-pro"
```

Config thêm vào `settings`:
```python
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_DEFAULT_MODEL: str = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-1.5-flash")
GEMINI_SYNTHESIS_MODEL: str = os.getenv("GEMINI_SYNTHESIS_MODEL", "gemini-1.5-pro")
LLM_WINDOW_SECONDS: float = float(os.getenv("LLM_WINDOW_SECONDS", "30.0"))
LLM_MIN_KNOWLEDGE_VALUE: float = float(os.getenv("LLM_MIN_KNOWLEDGE_VALUE", "0.3"))
```

### 3.3 — LLM Worker

Tạo `backend/app/services/llm_processor_worker.py`:

```python
"""
LLM Processor Worker

Consume LLM tasks từ Redis → lấy OCR frames từ MongoDB → 
gọi Gemini → lưu kết quả vào MongoDB.
"""

import asyncio, json, hashlib
from datetime import datetime
from typing import Optional
import redis.asyncio as redis

from app.config import settings
from app.services.mongo_service import mongo_ocr_service
from app.services.llm_processing import GeminiProcessingService
from app.services.redis.llm_processor_task import LLM_PROCESSOR_STREAM_KEY, LLMProcessorTask
from app.utils.decorator import singleton
from app.utils.logger import get_logger

logger = get_logger(__name__)

WINDOW_SECONDS = settings.LLM_WINDOW_SECONDS        # 30s per batch
MIN_KNOWLEDGE_VALUE = settings.LLM_MIN_KNOWLEDGE_VALUE


@singleton
class LLMProcessorWorker:

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._stream_key = LLM_PROCESSOR_STREAM_KEY
        self._group_name = "llm-processor-workers"
        self._consumer_id = "llm-worker-main"
        self._running = False
        self._gemini = GeminiProcessingService()

    async def start(self) -> None:
        if self._running:
            return
        self._redis = redis.from_url(settings.REDIS_URL, decode_responses=False)
        await self._redis.ping()
        try:
            await self._redis.xgroup_create(
                self._stream_key, self._group_name, id="0", mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        self._running = True
        logger.info("🤖 LLM Processor Worker started")
        await self._consume_loop()

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def _consume_loop(self) -> None:
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
                    continue
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
                            await self._redis.xack(
                                self._stream_key, self._group_name, msg_id
                            )
            except Exception as exc:
                logger.error(f"LLM consumer loop error: {exc}")
                await asyncio.sleep(2)

    async def _process_task(self, task: LLMProcessorTask) -> None:
        """
        Flow:
          1. Lấy OCR frames từ MongoDB
          2. Group thành windows 30s
          3. Gọi Gemini screen_understanding cho mỗi window
          4. Lưu OCRProcessedDocument
          5. Extract KnowledgeUnits cho windows có knowledge_value >= threshold
          6. Session synthesis → AssetKnowledgeSummary
        """
        if not mongo_ocr_service.is_connected:
            await mongo_ocr_service.connect()

        # Mark job as LLM processing
        await mongo_ocr_service.set_llm_status(task.ocr_job_id, "processing")

        frames = await mongo_ocr_service.get_ocr_frames(
            task.asset_id, skip_empty=True
        )
        if not frames:
            logger.info(f"No frames to process for asset {task.asset_id}")
            await mongo_ocr_service.set_llm_status(task.ocr_job_id, "skipped")
            return

        # ── Group frames vào windows ──────────────────────────────────────
        windows = self._group_frames_into_windows(frames)
        logger.info(f"Processing {len(frames)} frames → {len(windows)} windows")

        processed_summaries = []
        total_tokens = 0
        total_cost = 0.0

        for window in windows:
            result = await asyncio.to_thread(
                self._gemini.process_screen_segments,
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
                "llm_model": self._gemini.DEFAULT_MODEL,
                "tokens_used": result.tokens_used,
                "cost_usd": result.cost_usd,
            }

            if result.success:
                window_doc["analysis"] = result.parsed_data
                processed_summaries.append({
                    "start_ms": int(window["start_timestamp_sec"] * 1000),
                    "end_ms": int(window["end_timestamp_sec"] * 1000),
                    "summary": result.parsed_data.get("summary"),
                    "screen_type": result.parsed_data.get("screen_type"),
                    "user_intent": result.parsed_data.get("user_intent"),
                    "topics": result.parsed_data.get("topics", []),
                    "knowledge_value": float(result.parsed_data.get("knowledge_value", 0)),
                })

                # Extract knowledge units nếu đủ giá trị
                kv = float(result.parsed_data.get("knowledge_value", 0))
                if kv >= MIN_KNOWLEDGE_VALUE:
                    await self._extract_and_save_knowledge_units(
                        window["combined_text"],
                        result.parsed_data.get("summary", ""),
                        task.asset_id,
                        task.user_id,
                    )

            # Persist window
            await mongo_ocr_service.save_ocr_processed(
                asset_id=task.asset_id,
                user_id=task.user_id,
                ocr_job_id=task.ocr_job_id,
                window=window_doc,
            )

        # ── Session synthesis ─────────────────────────────────────────────
        if len(processed_summaries) >= 2:
            await self._synthesize_and_save(
                task, processed_summaries, total_tokens, total_cost
            )

        await mongo_ocr_service.set_llm_status(task.ocr_job_id, "completed")
        logger.info(
            f"✅ LLM processing done: asset={task.asset_id}, "
            f"windows={len(windows)}, tokens={total_tokens}, cost=${total_cost:.4f}"
        )

    def _group_frames_into_windows(self, frames: list[dict]) -> list[dict]:
        """Group frames liên tiếp vào windows WINDOW_SECONDS giây."""
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
        combined = "\n\n---\n\n".join(
            f.get("processed_text", "").strip() for f in frames
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
        result = await asyncio.to_thread(
            self._gemini.extract_knowledge, text, context
        )
        if not result.success:
            return 0

        count = 0
        data = result.parsed_data

        type_map = [
            ("facts",         "fact",         lambda x: x.get("content", "")),
            ("errors",        "error",        lambda x: x.get("message", "")),
            ("code_patterns", "code_pattern", lambda x: x.get("snippet", "")),
            ("commands",      "command",      lambda x: x.get("command", "")),
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

                inserted = await mongo_ocr_service.save_knowledge_unit(unit)
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
        duration_ms = (
            summaries[-1]["end_ms"] - summaries[0]["start_ms"]
            if summaries else 0
        )
        result = await asyncio.to_thread(
            self._gemini.synthesize_session,
            processed_segments=summaries[:50],
            asset_title=f"asset_{task.asset_id}",
            duration_ms=duration_ms,
        )

        summary_doc = {
            "asset_id": task.asset_id,
            "user_id": task.user_id,
            "ocr_job_id": task.ocr_job_id,
            "status": "completed" if result.success else "failed",
            "llm_model": self._gemini.SYNTHESIS_MODEL,
            "tokens_used": result.tokens_used,
            "cost_usd": result.cost_usd,
            **(result.parsed_data if result.success else {}),
            "synthesized_at": datetime.utcnow().isoformat(),
        }

        await mongo_ocr_service.upsert_asset_knowledge(
            asset_id=task.asset_id,
            summary=summary_doc,
        )


def get_llm_processor_worker() -> LLMProcessorWorker:
    return LLMProcessorWorker()
```

---

## PHASE 4: Đăng ký Worker vào Lifespan

Sửa `backend/app/__init__.py` — thêm LLM worker vào lifespan:

```python
# Thêm import
from app.services.llm_processor_worker import get_llm_processor_worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing code ...
    
    # Start LLM processor worker
    llm_worker = get_llm_processor_worker()
    llm_worker_task = asyncio.create_task(llm_worker.start())

    try:
        yield
    finally:
        await transcription_results_consumer.stop()
        await ocr_worker.stop()
        await llm_worker.stop()           # ← thêm dòng này
        
        # Cancel tasks
        for task in [ocr_worker_task, llm_worker_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
```

---

## PHASE 5: API Endpoints để query knowledge

Tạo `backend/app/api/knowledge.py`:

```python
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from app.dependencies import get_current_active_user
from app.models import User
from app.services.mongo_service import mongo_ocr_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/assets/{asset_id}/summary")
async def get_asset_summary(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
):
    if not mongo_ocr_service.is_connected:
        await mongo_ocr_service.connect()
    
    doc = await mongo_ocr_service.get_asset_knowledge(str(asset_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Knowledge summary not yet generated")
    
    # Verify ownership
    if doc.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")
    
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/assets/{asset_id}/frames")
async def get_asset_ocr_frames(
    asset_id: UUID,
    skip_empty: bool = Query(default=True),
    current_user: User = Depends(get_current_active_user),
):
    if not mongo_ocr_service.is_connected:
        await mongo_ocr_service.connect()
    
    frames = await mongo_ocr_service.get_ocr_frames(str(asset_id), skip_empty=skip_empty)
    # Verify ownership bằng cách check frame đầu tiên
    if frames and frames[0].get("user_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")
    
    for f in frames:
        f["_id"] = str(f["_id"])
    return frames


@router.get("/assets/{asset_id}/processed")
async def get_asset_processed_windows(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
):
    if not mongo_ocr_service.is_connected:
        await mongo_ocr_service.connect()
    
    windows = await mongo_ocr_service.get_ocr_processed(str(asset_id))
    for w in windows:
        w["_id"] = str(w["_id"])
    return windows


@router.get("/units")
async def get_knowledge_units(
    asset_id: UUID | None = Query(default=None),
    unit_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
):
    if not mongo_ocr_service.is_connected:
        await mongo_ocr_service.connect()
    
    units = await mongo_ocr_service.get_knowledge_units(
        user_id=str(current_user.id),
        asset_id=str(asset_id) if asset_id else None,
        unit_type=unit_type,
        limit=limit,
    )
    for u in units:
        u["_id"] = str(u["_id"])
    return units
```

Đăng ký trong `__init__.py`:
```python
from app.api.knowledge import router as knowledge_router
app.include_router(knowledge_router, prefix=settings.API_STR)
```

---

## ✅ Checklist theo thứ tự thực hiện

**Phase 1 — Schema + Service:**
- [ ] Thêm 5 Pydantic models mới vào `mongo_schemas.py`
- [ ] Thêm `MongoOCRService` vào `mongo_service.py`
- [ ] Test `mongo_ocr_service.connect()` thành công

**Phase 2 — Persist OCR output:**
- [ ] Sửa `_process_task` trong `ocr_processor_worker.py`
- [ ] Test: upload video → check MongoDB `ocr_frames` collection có data

**Phase 3 — LLM layer:**
- [ ] Tạo `services/redis/llm_processor_task.py`
- [ ] Thêm config Gemini vào `settings`
- [ ] Tạo `services/llm_processing.py` (Gemini service)
- [ ] Tạo `services/llm_processor_worker.py`

**Phase 4 — Wiring:**
- [ ] Thêm `LLMProcessorWorker` vào lifespan trong `__init__.py`

**Phase 5 — API:**
- [ ] Tạo `api/knowledge.py`
- [ ] Đăng ký router

**Verify end-to-end:**
- [ ] Upload 1 video ngắn (30s)
- [ ] Check `ocr_frames` có data
- [ ] Check `ocr_processed` có Gemini analysis
- [ ] Check `knowledge_units` có extracted facts
- [ ] Check `asset_knowledge` có session summary
- [ ] `GET /api/knowledge/assets/{id}/summary` trả về data