"""
Event payload schemas.

Each event type has a strongly-typed payload schema for validation.
These are the 10 core events for Phase 1 (see app/events/README.md
for the full event type registry and naming convention).
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# Note Events
# ============================================================================

class NoteCreatedPayload(BaseModel):
    """Payload for note.created event."""
    note_id: UUID
    workspace_id: UUID
    title: str
    parent_note_id: Optional[UUID] = None
    content_type: str = "markdown"


class NoteUpdatedPayload(BaseModel):
    """Payload for note.updated event."""
    note_id: UUID
    version: int
    fields_changed: list[str] = Field(default_factory=list, description="Fields that were modified")


class NoteDeletedPayload(BaseModel):
    """Payload for note.deleted event (soft delete)."""
    note_id: UUID


# ============================================================================
# Schedule Events
# ============================================================================

class ScheduleCreatedPayload(BaseModel):
    """Payload for schedule.created event."""
    schedule_id: UUID
    title: str
    schedule_type: str
    start_time: datetime
    end_time: datetime
    location: Optional[str] = None
    is_recurring: bool = False


class ScheduleUpdatedPayload(BaseModel):
    """Payload for schedule.updated event."""
    schedule_id: UUID
    fields_changed: list[str] = Field(default_factory=list)


class ScheduleCompletedPayload(BaseModel):
    """Payload for schedule.completed event."""
    schedule_id: UUID
    completed_at: datetime


class ReminderDuePayload(BaseModel):
    """Payload for schedule.reminder.due event."""
    reminder_id: UUID
    schedule_id: UUID
    schedule_title: str
    scheduled_at: datetime
    reminder_offset_minutes: Optional[int] = None
    method: str = "push"


# ============================================================================
# Task Events (Milestone 2.5)
# ============================================================================
#
# task.overdue is not published from a mutation like the others here —
# overdue is a property of the clock, not of a write. app.services.
# state_evaluator.StateEvaluator polls for it and owns publishing it
# (Milestone 4.6).

class TaskCreatedPayload(BaseModel):
    """Payload for task.created event."""
    task_id: UUID
    title: str
    status: str = Field(
        ..., description="pending_confirm, todo, in_progress, done, cancelled, or rejected"
    )
    due_date: Optional[datetime] = None
    priority: Optional[str] = Field(None, description="low, medium, high, or urgent")
    related_event_id: Optional[UUID] = None


class TaskUpdatedPayload(BaseModel):
    """Payload for task.updated event."""
    task_id: UUID
    status: str
    fields_changed: list[str] = Field(default_factory=list)


class TaskCompletedPayload(BaseModel):
    """Payload for task.completed event (status transitioned to `done`).

    Published *instead of* task.updated for that transition, so a subscriber
    never sees the same change twice.
    """
    task_id: UUID
    completed_at: datetime
    fields_changed: list[str] = Field(default_factory=list)


class TaskDeletedPayload(BaseModel):
    """Payload for task.deleted event (hard delete)."""
    task_id: UUID
    status: str


class TaskOverduePayload(BaseModel):
    """Payload for task.overdue event (Milestone 4.6). Published once per
    transition into overdue, not once per poll — see StateEvaluator."""
    task_id: UUID
    title: str
    due_date: datetime
    priority: Optional[str] = Field(None, description="low, medium, high, or urgent")
    overdue_days: int


class TaskDueSoonPayload(BaseModel):
    """Payload for task.due_soon event (Milestone 4.6 / A1). Published once
    per transition into the due-soon window — see StateEvaluator."""
    task_id: UUID
    title: str
    due_date: datetime
    priority: Optional[str] = Field(None, description="low, medium, high, or urgent")
    hours_until_due: int


class TaskStalePayload(BaseModel):
    """Payload for task.stale event (Milestone 4.6 / A1) — an open,
    undated task nobody has touched in a while."""
    task_id: UUID
    title: str
    created_at: datetime
    days_since_update: int


class TaskBlockedCascadePayload(BaseModel):
    """Payload for task.blocked_cascade event (Milestone 4.6 / A1) — a
    parent task is overdue and at least one of its subtasks is still open.
    `task_id` names the parent, since that's the item the reason is about."""
    task_id: UUID
    title: str
    overdue_days: int
    open_subtask_count: int


class ScheduleStartsSoonPayload(BaseModel):
    """Payload for schedule.starts_soon event (Milestone 4.6 / A1)."""
    schedule_id: UUID
    title: str
    start_time: datetime
    minutes_until_start: int


class DayReviewPayload(BaseModel):
    """Payload for day.review event (Milestone 4.6 / A1) — a per-user, not
    per-item, digest anchor: still work open as the day winds down."""
    open_task_count: int
    overdue_task_count: int


# ============================================================================
# Conversation Events
# ============================================================================

class ConversationMessageCreatedPayload(BaseModel):
    """Payload for conversation.message.created event."""
    conversation_id: UUID
    message_id: UUID
    role: str = Field(..., description="user, assistant, or tool")
    has_tool_calls: bool = False
    token_count: Optional[int] = None


# ============================================================================
# Tool Events
# ============================================================================

class ToolExecutedPayload(BaseModel):
    """Payload for tool.executed event."""
    tool_name: str
    conversation_id: Optional[UUID] = None
    success: bool
    duration_ms: int
    action_id: Optional[str] = Field(None, description="Snapshot ID for revertable tools")
    error: Optional[str] = None


# ============================================================================
# Integration Events
# ============================================================================

class GoogleCalendarSyncedPayload(BaseModel):
    """Payload for google_calendar.synced event."""
    user_id: UUID
    sync_direction: str = Field(..., description="push, pull, or bidirectional")
    events_added: int = 0
    events_updated: int = 0
    events_deleted: int = 0
    sync_duration_ms: int
    errors: list[str] = Field(default_factory=list)


# Registry mapping event type -> payload schema, used for validation/tests
# and by anything that needs to look up a payload class by event type string.
EVENT_PAYLOAD_REGISTRY: dict[str, type[BaseModel]] = {
    "note.created": NoteCreatedPayload,
    "note.updated": NoteUpdatedPayload,
    "note.deleted": NoteDeletedPayload,
    "schedule.created": ScheduleCreatedPayload,
    "schedule.updated": ScheduleUpdatedPayload,
    "schedule.completed": ScheduleCompletedPayload,
    "schedule.reminder.due": ReminderDuePayload,
    "task.created": TaskCreatedPayload,
    "task.updated": TaskUpdatedPayload,
    "task.completed": TaskCompletedPayload,
    "task.deleted": TaskDeletedPayload,
    "task.overdue": TaskOverduePayload,
    "task.due_soon": TaskDueSoonPayload,
    "task.stale": TaskStalePayload,
    "task.blocked_cascade": TaskBlockedCascadePayload,
    "schedule.starts_soon": ScheduleStartsSoonPayload,
    "day.review": DayReviewPayload,
    "conversation.message.created": ConversationMessageCreatedPayload,
    "tool.executed": ToolExecutedPayload,
    "google_calendar.synced": GoogleCalendarSyncedPayload,
}
