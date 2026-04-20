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
