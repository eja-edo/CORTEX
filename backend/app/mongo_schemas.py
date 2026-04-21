from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr


class TranscriptionSegmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    start: StrictFloat = Field(..., ge=0)
    end: StrictFloat = Field(..., gt=0)
    text: StrictStr = Field(..., min_length=1)
    confidence: StrictFloat = Field(..., ge=0, le=1)
    speaker_label: StrictStr = Field(default="unknown")


class SaveTranscriptionChunkMessage(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    task_id: StrictStr = Field(..., min_length=1)
    track_ref_id: StrictStr = Field(..., min_length=1)
    chunk_index: StrictInt = Field(..., ge=0)
    start_time: StrictFloat = Field(..., ge=0)
    end_time: StrictFloat = Field(..., ge=0)
    item_count: StrictInt = Field(..., ge=0)
    is_final: bool
    status: Literal["pending", "processing", "completed", "failed"]
    segments: list[TranscriptionSegmentInput] = Field(default_factory=list)


class MongoSegmentDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    transcription_job_id: StrictStr
    segment_index: StrictInt
    start_time_sec: StrictFloat
    end_time_sec: StrictFloat
    text: StrictStr
    confidence: StrictFloat
    speaker_label: StrictStr = Field(default="unknown")
    created_at: datetime


class MongoTranscriptionJobDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    track_ref_id: StrictStr
    total_segments: StrictInt = Field(..., ge=0)
    status: Literal["pending", "processing", "completed", "failed"]
    updated_at: datetime


# ══════════════════════════════════════════════════════════════════════════════
# OCR SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════


class OCRFrameDocument(BaseModel):
    """A frame that has gone through layout reconstruction."""

    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr  # UUID of asset in PostgreSQL
    user_id: StrictStr
    workspace_id: StrictStr | None = None

    frame_id: StrictInt  # frame sequence number
    timestamp_sec: StrictFloat  # timestamp in video (seconds)
    processed_text: StrictStr  # output of layout_processor
    ssim_score: StrictFloat | None = None  # from raw metadata.json
    changed: bool = True  # whether frame has changed from previous
    theme: StrictStr | None = None  # "dark" | "light"

    # Raw regions from pipeline (keep for debug/reprocess)
    raw_regions: list[dict] = Field(default_factory=list)  # [{bbox, text}]
    ui_regions: list[list[int]] = Field(default_factory=list)

    created_at: datetime


class OCRJobDocument(BaseModel):
    """Metadata of an OCR processing job for an asset."""

    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    workspace_id: StrictStr | None = None
    task_id: StrictStr  # OCRProcessorTask.task_id

    status: Literal["pending", "processing", "completed", "failed"]
    total_frames: int = 0
    non_empty_frames: int = 0
    output_dir: StrictStr | None = None

    # LLM processing state
    llm_status: Literal[
        "pending", "processing", "completed", "failed", "skipped"
    ] = "pending"
    llm_processed_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


class LLMFrameAnalysis(BaseModel):
    """Gemini result for a frame/batch."""

    model_config = ConfigDict(extra="allow")

    screen_type: str | None = None
    application: str | None = None
    user_intent: str | None = None
    knowledge_value: float = 0.0
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)
    searchable_keywords: list[str] = Field(default_factory=list)


class OCRProcessedDocument(BaseModel):
    """
    A window (batch frames ~30s) after Gemini processing.
    This is the main unit for search and query.
    """

    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    ocr_job_id: StrictStr  # _id of OCRJobDocument

    # Time range of this window
    start_timestamp_sec: float
    end_timestamp_sec: float
    frame_ids: list[int] = Field(default_factory=list)

    # Raw text (concatenation of frames in window)
    combined_text: StrictStr

    # Gemini output
    analysis: LLMFrameAnalysis | None = None
    llm_model: StrictStr | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0

    status: Literal["pending", "processing", "completed", "failed"] = "pending"
    error_message: StrictStr | None = None

    created_at: datetime
    processed_at: datetime | None = None


class KnowledgeUnitDocument(BaseModel):
    """
    Atomic knowledge fact — extracted from OCR content by Gemini.
    Cross-asset searchable.
    """

    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    ocr_processed_id: StrictStr  # reference to OCRProcessedDocument

    unit_type: Literal["fact", "error", "code_pattern", "command", "reference"]
    content: StrictStr
    context: StrictStr | None = None
    confidence: float = 1.0

    # Type-specific fields
    error_type: StrictStr | None = None
    resolution: StrictStr | None = None
    language: StrictStr | None = None
    url: StrictStr | None = None
    platform: StrictStr | None = None
    reusability: float = 0.5

    content_hash: StrictStr  # sha256(user_id + content) for deduplication

    is_verified: bool = False
    deleted_at: datetime | None = None
    created_at: datetime


class AssetKnowledgeSummary(BaseModel):
    """Session-level synthesis of entire asset."""

    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    ocr_job_id: StrictStr

    session_title: StrictStr | None = None
    primary_technology: StrictStr | None = None
    difficulty_level: StrictStr | None = None
    overall_summary: StrictStr | None = None

    tags: list[str] = Field(default_factory=list)
    workflow: list[dict] = Field(default_factory=list)
    problems_encountered: list[dict] = Field(default_factory=list)
    solutions_found: list[dict] = Field(default_factory=list)
    knowledge_gained: list[str] = Field(default_factory=list)

    llm_model: StrictStr | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0

    status: Literal["pending", "processing", "completed", "failed"] = "pending"
    synthesized_at: datetime | None = None
    created_at: datetime
