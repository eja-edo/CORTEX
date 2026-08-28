"""
Command argument schemas.

Each command has a strongly-typed Pydantic model for validation.
This prevents AI from passing invalid arguments.
"""

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import (
    EditScope,
    ScheduleType,
    TaskPriority,
    TaskStatus,
)


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
    # Container của ghi chú. `None` là hợp lệ — service rơi về dự án cá
    # nhân (DESIGN 3.5 bước 3).
    project_id: Optional[UUID] = None
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
    """Arguments for schedule.update command.

    `original_start_time`/`edit_scope` are required when the target
    schedule turns out to be recurring — the handler rejects an ambiguous
    update rather than silently mutating the whole series. See
    `app.commands.handlers.schedule_commands.schedule_update_handler`.
    """
    schedule_id: UUID
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_completed: Optional[bool] = None
    original_start_time: Optional[datetime] = None
    edit_scope: Optional[EditScope] = None


class ScheduleDeleteArgs(BaseModel):
    """Arguments for schedule.delete command."""
    schedule_id: UUID


# ============================================================================
# Task Commands (Milestone 2.5)
# ============================================================================

class TaskCreateArgs(BaseModel):
    """Arguments for task.create command.

    No `workspace_id`: tasks are user-scoped, so they take CommandRegistry's
    ownership path.
    """
    title: str = Field(..., min_length=1, max_length=255)
    status: TaskStatus = TaskStatus.TODO
    due_date: Optional[date] = None
    priority: Optional[TaskPriority] = None
    description: Optional[str] = Field(None, max_length=10000)
    # Đã giải sẵn từ `project_ref` ở tầng tool — command layer không bao
    # giờ nhận một cái *tên* dự án. Giải tên có thể phải hỏi lại người dùng
    # (`ask_user_choice`), và một command không có chỗ cho một câu hỏi.
    project_id: Optional[UUID] = None
    related_event_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()


class TaskUpdateArgs(BaseModel):
    """Arguments for task.update command.

    `None` means "leave unchanged" on this path — the registry re-serializes
    validated args before the handler sees them, so unset-ness doesn't
    survive. Clearing a `due_date`/`priority`/`description` is an API-only
    operation.

    An illegal `status` transition is rejected by TaskService, so the AI
    can't move a cancelled task straight to done by calling this.

    `occurrence_start_time`/`edit_scope` are required only when this task
    is a checklist item (`related_event_id` set) whose event turns out to
    be recurring — same "reject an ambiguous write" rule as
    `ScheduleUpdateArgs`. A task has no `this_and_after`: it doesn't own a
    recurrence rule (the event does), so only `this_only`/`all` apply.
    """
    task_id: UUID
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[TaskStatus] = None
    due_date: Optional[date] = None
    priority: Optional[TaskPriority] = None
    description: Optional[str] = Field(None, max_length=10000)
    related_event_id: Optional[UUID] = None
    occurrence_start_time: Optional[datetime] = None
    edit_scope: Optional[Literal["this_only", "all"]] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip() if v else None


class TaskCompleteArgs(BaseModel):
    """Arguments for task.complete command — ticking the box needs nothing
    but the id, unless this task is a checklist item on a recurring event
    (see `TaskUpdateArgs` docstring — same occurrence rule applies)."""
    task_id: UUID
    occurrence_start_time: Optional[datetime] = None
    edit_scope: Optional[Literal["this_only", "all"]] = None


class TaskDeleteArgs(BaseModel):
    """Arguments for task.delete command.

    Deleting a line from an event's checklist (2.6) is a task deletion, not
    a text edit — the checklist has no text of its own to edit.
    """
    task_id: UUID


class TaskConfirmArgs(BaseModel):
    """Arguments for task.confirm command — approving a suggestion the
    extraction pipeline made needs nothing but the id."""
    task_id: UUID


class TaskRejectArgs(BaseModel):
    """Arguments for task.reject command."""
    task_id: UUID


# ============================================================================
# Plan Commands (3.2 AI Planner)
# ============================================================================

class PlanProposeItemArgs(BaseModel):
    """One draft item inside a plan.propose command — see
    `PlanProposalItemIn` (app/schemas.py) for the equivalent request/response
    shape; kept separate here per the existing args.py/schemas.py split
    (e.g. NoteUpdateArgs vs NoteUpdate)."""
    key: str = Field(..., min_length=1, max_length=50)
    type: Literal["task", "event"]
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=10000)

    due_date: Optional[datetime] = None
    priority: Optional[TaskPriority] = None
    parent_key: Optional[str] = None
    related_event_key: Optional[str] = None

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=255)
    recurrence: Optional[dict] = None

    @model_validator(mode="after")
    def _fields_match_type(self) -> "PlanProposeItemArgs":
        task_only = {
            "due_date": self.due_date,
            "priority": self.priority,
            "parent_key": self.parent_key,
            "related_event_key": self.related_event_key,
        }
        event_only = {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "location": self.location,
            "recurrence": self.recurrence,
        }
        if self.type == "task":
            set_event_fields = [name for name, value in event_only.items() if value is not None]
            if set_event_fields:
                raise ValueError(f"task item '{self.key}' cannot set event field(s): {set_event_fields}")
        else:
            set_task_fields = [name for name, value in task_only.items() if value is not None]
            if set_task_fields:
                raise ValueError(f"event item '{self.key}' cannot set task field(s): {set_task_fields}")
            if self.start_time is None or self.end_time is None:
                raise ValueError(f"event item '{self.key}' requires start_time and end_time")
        return self


class PlanProposeArgs(BaseModel):
    """Arguments for plan.propose command.

    Validates the item list as a whole: unique keys, every `parent_key`
    resolves to a `task` item in the SAME list, and no cycles — so a
    malformed LLM-generated plan is rejected before a proposal row is ever
    created, not discovered later at approve time.
    """
    items: list[PlanProposeItemArgs] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def _validate_item_graph(self) -> "PlanProposeArgs":
        by_key: dict[str, PlanProposeItemArgs] = {}
        for item in self.items:
            if item.key in by_key:
                raise ValueError(f"duplicate item key: {item.key}")
            by_key[item.key] = item

        for item in self.items:
            if item.parent_key is None:
                continue
            if item.parent_key == item.key:
                raise ValueError(f"item '{item.key}' cannot be its own parent")
            parent = by_key.get(item.parent_key)
            if parent is None:
                raise ValueError(f"item '{item.key}' has parent_key '{item.parent_key}' which does not exist")
            if parent.type != "task":
                raise ValueError(f"item '{item.key}' has parent_key '{item.parent_key}' which is not a task")

        for item in self.items:
            if item.related_event_key is None:
                continue
            linked = by_key.get(item.related_event_key)
            if linked is None:
                raise ValueError(f"item '{item.key}' has related_event_key '{item.related_event_key}' which does not exist")
            if linked.type != "event":
                raise ValueError(f"item '{item.key}' has related_event_key '{item.related_event_key}' which is not an event")

        # Cycle check: walk parent_key chains, each must terminate at None.
        for item in self.items:
            seen: set[str] = set()
            current: Optional[PlanProposeItemArgs] = item
            while current is not None and current.parent_key is not None:
                if current.key in seen:
                    raise ValueError(f"cycle detected in parent_key chain starting at '{item.key}'")
                seen.add(current.key)
                current = by_key.get(current.parent_key)
        return self


# ============================================================================
# Action Commands (Revert)
# ============================================================================

class ActionRevertArgs(BaseModel):
    """Arguments for action.revert command."""
    action_id: str = Field(..., description="Snapshot ID to revert")
