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
    """Payload for schedule.reminder.due event.

    `scheduled_at` and `start_time` are two different instants and were
    conflated for a long time: `reminder_service` sets a reminder's
    `scheduled_at` to `start_time - minutes_before`, so it is *when the
    nudge fires*, not when the event begins. The subscriber rendered it as
    "Starts at {scheduled_at}", which told the user a meeting at 14:00
    started at 13:45. `start_time` is now carried explicitly so nothing has
    to infer one from the other.
    """
    reminder_id: UUID
    schedule_id: UUID
    schedule_title: str
    scheduled_at: datetime = Field(..., description="When the reminder fires (start_time - offset)")
    start_time: datetime = Field(..., description="When the schedule itself begins")
    location: Optional[str] = None
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


class TaskDigestItem(BaseModel):
    """One task as it appears inside a digest event's list.

    A snapshot, not a reference: a subscriber that only got `task_id` would
    have to go back to the database to say anything useful, and events are
    also read by workflow_service across a process boundary where that
    lookup isn't available at all. Kept to what notification text actually
    prints — see `app.services.notification_format.task_line`.
    """
    task_id: UUID
    title: str
    due_date: Optional[datetime] = None
    priority: Optional[str] = Field(None, description="low, medium, high, or urgent")


class ScheduleDigestItem(BaseModel):
    """One calendar event inside a digest event's list. `start_time` is a
    real instant here, unlike `TaskDigestItem.due_date` — see
    `notification_format`'s module docstring."""
    schedule_id: UUID
    title: str
    start_time: datetime
    location: Optional[str] = None


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
    priority: Optional[str] = Field(None, description="low, medium, high, or urgent")


class TaskBlockedCascadePayload(BaseModel):
    """Payload for task.blocked_cascade event (Milestone 4.6 / A1) — a
    parent task is overdue and at least one of its subtasks is still open.
    `task_id` names the parent, since that's the item the reason is about."""
    task_id: UUID
    title: str
    overdue_days: int
    open_subtask_count: int
    due_date: Optional[datetime] = None
    priority: Optional[str] = Field(None, description="low, medium, high, or urgent")
    # The whole point of this reason is *which* work is stuck behind the
    # parent. A bare count named nothing the user could go act on.
    open_subtasks: list[TaskDigestItem] = Field(default_factory=list)


class ScheduleStartsSoonPayload(BaseModel):
    """Payload for schedule.starts_soon event (Milestone 4.6 / A1)."""
    schedule_id: UUID
    title: str
    start_time: datetime
    minutes_until_start: int
    location: Optional[str] = None


class TaskAtRiskPayload(BaseModel):
    """Payload for task.at_risk event (Milestone 6.8/4.4) — an overdue
    task whose `compute_risk` score (priority x overdue_days x cascade)
    crossed `settings.STATE_EVALUATOR_RISK_THRESHOLD`. Escalation on top
    of `task.overdue`, not a replacement for it — a task can be overdue
    without being `at_risk`."""
    task_id: UUID
    title: str
    risk_score: float
    overdue_days: int
    open_subtask_count: int
    priority: Optional[str] = Field(None, description="low, medium, high, or urgent")
    # `risk_score` alone is an uninterpretable number — 12.0 means nothing
    # without the deadline it missed and the work stuck behind it. These
    # are the inputs `risk_detection.compute_risk` multiplied together, so
    # the notification can show its working instead of asserting a verdict.
    due_date: Optional[datetime] = None
    open_subtasks: list[TaskDigestItem] = Field(default_factory=list)


class DayReviewPayload(BaseModel):
    """Payload for day.review event (Milestone 4.6 / A1) — a per-user, not
    per-item, digest anchor: what the day actually came to.

    Originally two counts, which made the end of a productive day and the
    end of a wasted one read identically ("Còn 5 việc chưa xong"). A review
    has to close the loop on both halves: what got finished, and what is
    carrying over.
    """
    open_task_count: int
    overdue_task_count: int
    completed_today_count: int = 0
    completed_today: list[TaskDigestItem] = Field(default_factory=list)
    still_open: list[TaskDigestItem] = Field(default_factory=list)


class DayPlanPayload(BaseModel):
    """Payload for day.plan event — the morning counterpart to
    `day.review`.

    Detection had no start-of-day predicate at all: every task reason fires
    off a deadline that is already close or already missed, so the first
    thing Cortex said about a day's work was a warning about it. This is
    the one reason that arrives before anything has gone wrong.

    `carried_over` is deliberately separate from `due_today`: work that
    slipped from an earlier day is the part a plan has to confront first,
    and folding it into one list would hide it.
    """
    due_today_count: int
    carried_over_count: int
    schedule_count: int = 0
    due_today: list[TaskDigestItem] = Field(default_factory=list)
    carried_over: list[TaskDigestItem] = Field(default_factory=list)
    schedules: list[ScheduleDigestItem] = Field(default_factory=list)


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
    "task.at_risk": TaskAtRiskPayload,
    "day.review": DayReviewPayload,
    "day.plan": DayPlanPayload,
    "conversation.message.created": ConversationMessageCreatedPayload,
    "tool.executed": ToolExecutedPayload,
    "google_calendar.synced": GoogleCalendarSyncedPayload,
}
