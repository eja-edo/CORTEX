"""
Command argument schemas.

Each command has a strongly-typed Pydantic model for validation.
This prevents AI from passing invalid arguments.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import ScheduleType


# ============================================================================
# Note Commands
# ============================================================================

class NoteCreateArgs(BaseModel):
    """Arguments for note.create command.

    `title` is optional (not required=...): the real `create_note` AI tool
    doesn't collect a title at all — NoteService.create_note() derives one
    from the first line of `content` when omitted. `style` isn't in the
    original Milestone 1.4 draft of this schema; added so the migrated
    create_note tool (which lets the LLM pick a color) can still pass it
    through — NoteCreate.style otherwise silently defaults to yellow.
    """
    workspace_id: UUID
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content: str = Field(default="")
    parent_note_id: Optional[UUID] = None
    content_type: str = Field(default="markdown")
    style: Optional[dict] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip() if v else None


class NoteUpdateArgs(BaseModel):
    """
    Arguments for note.update command.

    Note: the real `update_note_handler` (backend/app/ai/tools/update_note.py)
    does NOT apply changes directly — it creates a Proposal via
    ProposalService, pending user approval. `content` here is the full NEW
    proposed text (not a patch), and a successful note.update command means
    "a proposal was created", not "the note was changed". See
    05_COMMAND_REGISTRY.md / 06_TOOL_MIGRATION.md for the handler.
    """
    note_id: UUID
    version: Optional[int] = Field(
        default=None, ge=1,
        description="Optimistic lock version — accepted for forward-compat with a future "
                     "direct-apply path, but note_update_handler doesn't read it today (the "
                     "Proposal flow has no in-place write to lock against).",
    )
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = None
    parent_note_id: Optional[UUID] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip() if v else None


class NoteDeleteArgs(BaseModel):
    """Arguments for note.delete command."""
    note_id: UUID


# ============================================================================
# Schedule Commands
# ============================================================================

class ScheduleCreateArgs(BaseModel):
    """Arguments for schedule.create command."""
    title: str = Field(..., min_length=1, max_length=255)
    schedule_type: ScheduleType
    start_time: datetime
    end_time: datetime
    location: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    recurrence: Optional[dict] = None
    reminders: Optional[list[dict]] = None

    @model_validator(mode="after")
    def end_after_start(self) -> "ScheduleCreateArgs":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ScheduleUpdateArgs(BaseModel):
    """Arguments for schedule.update command."""
    schedule_id: UUID
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_completed: Optional[bool] = None


class ScheduleDeleteArgs(BaseModel):
    """Arguments for schedule.delete command."""
    schedule_id: UUID


# ============================================================================
# Action Commands (Revert)
# ============================================================================

class ActionRevertArgs(BaseModel):
    """Arguments for action.revert command."""
    action_id: str = Field(..., description="Snapshot ID to revert")
