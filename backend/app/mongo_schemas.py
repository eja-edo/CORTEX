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

    asset_id: StrictStr
    user_id: StrictStr

    frame_id: StrictInt
    timestamp_sec: StrictFloat
    processed_text: StrictStr
    ssim_score: StrictFloat | None = None
    changed: bool = True
    theme: StrictStr | None = None

    raw_regions: list[dict] = Field(default_factory=list)
    ui_regions: list[list[int]] = Field(default_factory=list)

    created_at: datetime


class OCRJobDocument(BaseModel):
    """Metadata of an OCR processing job for an asset."""

    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    task_id: StrictStr

    status: Literal["pending", "processing", "completed", "failed"]
    total_frames: int = 0
    non_empty_frames: int = 0
    output_dir: StrictStr | None = None


    created_at: datetime
    updated_at: datetime


# ══════════════════════════════════════════════════════════════════════════════
# TIMELINE-BASED KNOWLEDGE SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════


class TimelineEventEntity(BaseModel):
    """A named entity extracted within a timeline event."""

    model_config = ConfigDict(extra="allow")

    type: str  # "url", "code", "error", "person", "tool", "file"
    value: str
    confidence: float = 1.0


class TimelineEvent(BaseModel):
    """
    Atomic knowledge event anchored to a specific time range.

    This is the core unit stored in the knowledge timeline — every piece
    of information is pinned to start_sec/end_sec so the UI can link
    back to the exact moment in the recording.
    """

    model_config = ConfigDict(extra="allow")

    # Time anchor (seconds)
    start_sec: float
    end_sec: float

    # Content source flags
    has_ocr: bool = False       # was OCR text available for this window
    has_transcript: bool = False  # was speech transcript available

    # Screen context (from OCR, None for audio-only)
    screen_type: str | None = None   # "browser", "editor", "terminal", "settings", "other"
    application: str | None = None

    # What the user was doing / saying
    activity_summary: str        # concise description of this moment
    spoken_content: str | None = None   # verbatim or near-verbatim transcript excerpt
    screen_content: str | None = None   # key text visible on screen

    # Semantic tags
    topics: list[str] = Field(default_factory=list)
    entities: list[TimelineEventEntity] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    # Signal strength
    knowledge_value: float = 0.0  # 0.0 = trivial, 1.0 = critical learning moment
    event_type: str = "activity"  # "activity", "error", "solution", "decision", "explanation"


class LLMFrameAnalysis(BaseModel):
    """
    Gemini result for a combined OCR+transcript window.

    Replaces the old flat structure with a timeline_events list so every
    insight is anchored to a timestamp.
    """

    model_config = ConfigDict(extra="allow")

    # Legacy flat fields kept for backward compatibility
    screen_type: str | None = None
    application: str | None = None
    user_intent: str | None = None
    knowledge_value: float = 0.0
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)
    searchable_keywords: list[str] = Field(default_factory=list)

    # New: fine-grained timeline events for this window
    timeline_events: list[TimelineEvent] = Field(default_factory=list)


class OCRProcessedDocument(BaseModel):
    """
    A window (batch ~30s) after Gemini processing.
    Now stores both legacy flat fields AND timeline_events.
    """

    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    ocr_job_id: StrictStr

    start_timestamp_sec: float
    end_timestamp_sec: float
    frame_ids: list[int] = Field(default_factory=list)

    combined_text: StrictStr          # raw OCR text
    transcript_text: StrictStr = ""   # raw transcript text for this window

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
    Atomic knowledge fact — anchored to a specific time range so the UI
    can jump to the exact moment in the recording.
    """

    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr

    unit_type: Literal["fact", "error", "code_pattern", "command", "reference", "explanation", "decision"]
    content: StrictStr
    confidence: float = 1.0

    # Time anchor
    start_sec: float = 0.0
    end_sec: float = 0.0

    # Type-specific fields
    language: StrictStr | None = None
    url: StrictStr | None = None
    platform: StrictStr | None = None

    content_hash: StrictStr

    is_verified: bool = False
    deleted_at: datetime | None = None
    created_at: datetime


class AssetKnowledgeSummary(BaseModel):
    """
    Session-level synthesis of entire asset.
    Now includes a full knowledge_timeline list ordered by time.
    """

    model_config = ConfigDict(extra="forbid")

    asset_id: StrictStr
    user_id: StrictStr
    ocr_job_id: StrictStr

    # Asset type context
    has_video: bool = False
    has_audio: bool = False

    session_title: StrictStr | None = None
    primary_technology: StrictStr | None = None
    difficulty_level: StrictStr | None = None
    overall_summary: StrictStr | None = None

    tags: list[str] = Field(default_factory=list)
    workflow: list[dict] = Field(default_factory=list)
    problems_encountered: list[dict] = Field(default_factory=list)
    solutions_found: list[dict] = Field(default_factory=list)
    knowledge_gained: list[str] = Field(default_factory=list)

    knowledge_timeline: list[TimelineEvent] = Field(default_factory=list)

    llm_model: StrictStr | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0

    status: Literal["pending", "processing", "completed", "failed"] = "pending"
    synthesized_at: datetime | None = None
    created_at: datetime