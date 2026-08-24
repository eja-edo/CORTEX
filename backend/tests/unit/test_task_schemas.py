"""Unit tests for Milestone 2.5 — Task Data Model.

Guards what 2.5 fixes:
  - the status state machine (M3), as a table, so an accidental edit to
    TASK_STATUS_TRANSITIONS is a test failure and not a silent rule change;
  - the columns, including `priority`/`description` (M5);
  - the Task/Schedule boundary — a task has a `due_date`, never a time block;
  - the `task.*` events, including `fields_changed` on task.updated.
"""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.commands.args import TaskCompleteArgs, TaskCreateArgs, TaskUpdateArgs
from app.events.payloads import (
    EVENT_PAYLOAD_REGISTRY,
    TaskCompletedPayload,
    TaskCreatedPayload,
    TaskDeletedPayload,
    TaskOverduePayload,
    TaskUpdatedPayload,
)
from app.events.vocabulary import EVENT_VOCABULARY, implemented_event_types
from app.models import Task, TaskStatus
from app.schemas import TaskCreate, TaskResponse, TaskUpdate
from app.services.tasks import (
    TASK_STATUS_TRANSITIONS,
    InvalidTaskTransition,
    is_valid_transition,
)


# ============================================================================
# State machine (M3)
# ============================================================================

LEGAL_TRANSITIONS = [
    (TaskStatus.TODO, TaskStatus.IN_PROGRESS),
    (TaskStatus.IN_PROGRESS, TaskStatus.DONE),
    (TaskStatus.TODO, TaskStatus.DONE),          # no need to pass through in_progress
    (TaskStatus.IN_PROGRESS, TaskStatus.TODO),   # "not actually started"
    (TaskStatus.DONE, TaskStatus.TODO),          # reopen
    (TaskStatus.TODO, TaskStatus.CANCELLED),     # anything live → cancelled
    (TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED),
    (TaskStatus.DONE, TaskStatus.CANCELLED),
    (TaskStatus.CANCELLED, TaskStatus.TODO),     # restore
    # A suggestion from conversation extraction (formerly Commitment's
    # pending_confirm/reject) — confirm makes it real work, reject is
    # terminal, same reasoning Commitment's five-state machine had.
    (TaskStatus.PENDING_CONFIRM, TaskStatus.TODO),
    (TaskStatus.PENDING_CONFIRM, TaskStatus.REJECTED),
]

ILLEGAL_TRANSITIONS = [
    (TaskStatus.DONE, TaskStatus.IN_PROGRESS),       # reopen via todo instead
    (TaskStatus.CANCELLED, TaskStatus.IN_PROGRESS),  # restore via todo instead
    (TaskStatus.CANCELLED, TaskStatus.DONE),         # can't finish an abandoned task
    # pending_confirm only ever resolves to todo or rejected — skipping the
    # confirm step isn't a described flow.
    (TaskStatus.PENDING_CONFIRM, TaskStatus.IN_PROGRESS),
    (TaskStatus.PENDING_CONFIRM, TaskStatus.DONE),
    (TaskStatus.PENDING_CONFIRM, TaskStatus.CANCELLED),
    # rejected is terminal — reopening a rejected suggestion isn't a
    # described flow, same as Commitment's rejected/fulfilled/cancelled.
    (TaskStatus.REJECTED, TaskStatus.TODO),
    (TaskStatus.REJECTED, TaskStatus.IN_PROGRESS),
    (TaskStatus.REJECTED, TaskStatus.DONE),
    (TaskStatus.REJECTED, TaskStatus.CANCELLED),
    (TaskStatus.REJECTED, TaskStatus.PENDING_CONFIRM),
    # Nothing transitions back into pending_confirm or into rejected except
    # from pending_confirm itself — both are extraction-only entry points.
    (TaskStatus.TODO, TaskStatus.PENDING_CONFIRM),
    (TaskStatus.IN_PROGRESS, TaskStatus.PENDING_CONFIRM),
    (TaskStatus.DONE, TaskStatus.PENDING_CONFIRM),
    (TaskStatus.CANCELLED, TaskStatus.PENDING_CONFIRM),
    (TaskStatus.TODO, TaskStatus.REJECTED),
    (TaskStatus.IN_PROGRESS, TaskStatus.REJECTED),
    (TaskStatus.DONE, TaskStatus.REJECTED),
    (TaskStatus.CANCELLED, TaskStatus.REJECTED),
]


@pytest.mark.parametrize("current,requested", LEGAL_TRANSITIONS)
def test_legal_transitions(current, requested):
    assert is_valid_transition(current, requested) is True


@pytest.mark.parametrize("current,requested", ILLEGAL_TRANSITIONS)
def test_illegal_transitions(current, requested):
    assert is_valid_transition(current, requested) is False


def test_transition_table_is_exactly_the_agreed_set():
    """Every (from, to) pair in the enum is either explicitly legal or
    explicitly illegal above — no pair goes unclassified."""
    classified = {(a, b) for a, b in LEGAL_TRANSITIONS + ILLEGAL_TRANSITIONS}
    all_pairs = {(a, b) for a in TaskStatus for b in TaskStatus if a != b}
    assert classified == all_pairs


@pytest.mark.parametrize("status", list(TaskStatus))
def test_same_status_is_a_no_op_not_an_error(status):
    """Ticking an already-done checkbox twice must not fail — the second
    write is idempotent, and 2.6's checklist will do exactly this."""
    assert is_valid_transition(status, status) is True


def test_every_live_status_can_be_cancelled():
    """"Live" excludes `pending_confirm` (not yet real work — reject is the
    way out, not cancel) and `rejected` (already terminal)."""
    live_statuses = {TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.DONE}
    for status in live_statuses:
        assert TaskStatus.CANCELLED in TASK_STATUS_TRANSITIONS[status]


def test_cancelled_only_goes_back_to_todo():
    assert TASK_STATUS_TRANSITIONS[TaskStatus.CANCELLED] == frozenset({TaskStatus.TODO})


def test_invalid_transition_error_is_a_value_error_and_explains_itself():
    """ValueError subclass so CommandRegistry's generic handling still turns
    it into a failed CommandResult rather than a 500."""
    exc = InvalidTaskTransition(TaskStatus.CANCELLED, TaskStatus.DONE)
    assert isinstance(exc, ValueError)
    assert "cancelled" in str(exc) and "done" in str(exc)
    assert "todo" in str(exc)  # tells the caller what IS allowed


# ============================================================================
# M5 — `priority` is a real, user-set field
# ============================================================================

def test_task_model_has_priority_column():
    assert "priority" in Task.__table__.columns


@pytest.mark.parametrize(
    "model", [TaskCreate, TaskUpdate, TaskResponse, TaskCreateArgs, TaskUpdateArgs]
)
def test_task_schemas_have_priority_field(model):
    assert "priority" in model.model_fields


# ============================================================================
# Table shape / Task-vs-Schedule boundary
# ============================================================================

def test_tasks_table_has_exactly_the_agreed_columns():
    """`related_commitment_id` is gone and `source_conversation_id`/
    `source_message_id` took its place — Commitment's provenance fields,
    moved here when Commitment was folded into Task. `parent_task_id` is a
    task's own checklist — self-referential, same shape as
    `related_event_id`. `recurrence_id`/`original_start_time`/`is_exception`
    are the per-occurrence completion mechanism for a checklist task tied to
    a recurring event — mirrors `Schedule`'s own exception-row columns."""
    assert {c.name for c in Task.__table__.columns} == {
        "id",
        "user_id",
        "title",
        "status",
        "due_date",
        "priority",
        "description",
        "related_event_id",
        "parent_task_id",
        "source_conversation_id",
        "source_message_id",
        "completed_at",
        "recurrence_id",
        "original_start_time",
        "is_exception",
        "created_at",
        "updated_at",
    }


@pytest.mark.parametrize("column", ["start_time", "end_time", "duration", "is_completed"])
def test_task_has_no_time_block_columns(column):
    """"A schedule occupies time, a task consumes it." A task that could
    carry a start/end would be a schedule row in disguise, and would poison
    the free-slot (3.3) and interruptibility (6.2) calculations."""
    assert column not in Task.__table__.columns


@pytest.mark.parametrize(
    "column",
    ["related_event_id", "source_conversation_id", "source_message_id", "due_date", "priority", "description"],
)
def test_all_relations_are_nullable(column):
    """Tasks born in chat or created by Cortex itself belong to nothing —
    that's the common case, not the exception."""
    assert Task.__table__.columns[column].nullable is True


def test_no_related_project_id():
    """2.5's prose mentions it; Phase 2's "Không làm" table defers the whole
    Project entity. No FK to a table that doesn't exist."""
    assert "related_project_id" not in Task.__table__.columns


# ============================================================================
# API / command schemas
# ============================================================================

def test_task_create_requires_title():
    with pytest.raises(ValidationError):
        TaskCreate(due_date=date(2026, 12, 31))


def test_task_create_rejects_blank_title():
    with pytest.raises(ValidationError):
        TaskCreate(title="   ")


def test_task_create_defaults_to_todo_and_no_relations():
    task = TaskCreate(title="Write API spec")
    assert task.status is TaskStatus.TODO
    assert task.due_date is None
    assert task.priority is None
    assert task.description is None
    assert task.related_event_id is None


def test_task_update_distinguishes_unset_from_explicit_null():
    omitted = TaskUpdate(title="New title")
    assert "due_date" not in omitted.model_dump(exclude_unset=True)

    detached = TaskUpdate(related_event_id=None)
    assert detached.model_dump(exclude_unset=True) == {"related_event_id": None}


def test_task_update_rejects_unknown_status():
    with pytest.raises(ValidationError):
        TaskUpdate(status="blocked")


def test_task_complete_args_needs_only_the_id():
    """`occurrence_start_time`/`edit_scope` are optional here — they're only
    required (checked at the handler, not the schema, since it depends on
    the task's own `related_event_id`) when this task is a checklist item on
    a recurring event."""
    args = TaskCompleteArgs(task_id=uuid4())
    assert set(TaskCompleteArgs.model_fields) == {"task_id", "occurrence_start_time", "edit_scope"}
    assert args.task_id is not None
    assert args.occurrence_start_time is None
    assert args.edit_scope is None


def test_task_create_args_has_no_workspace_id():
    assert "workspace_id" not in TaskCreateArgs.model_fields


# ============================================================================
# Events (M4)
# ============================================================================

@pytest.mark.parametrize(
    "event_type", ["task.created", "task.updated", "task.completed", "task.deleted"]
)
def test_task_events_are_in_the_vocabulary(event_type):
    assert event_type in EVENT_VOCABULARY
    assert event_type in implemented_event_types()
    assert EVENT_VOCABULARY[event_type].published_by == "app.services.tasks.TaskService"


def test_task_event_payload_classes():
    assert EVENT_PAYLOAD_REGISTRY["task.created"] is TaskCreatedPayload
    assert EVENT_PAYLOAD_REGISTRY["task.updated"] is TaskUpdatedPayload
    assert EVENT_PAYLOAD_REGISTRY["task.completed"] is TaskCompletedPayload
    assert EVENT_PAYLOAD_REGISTRY["task.deleted"] is TaskDeletedPayload


def test_task_overdue_is_published_by_state_evaluator_not_a_mutation():
    """Overdue is a property of the clock, not of a write — so unlike the
    task.* events above (published_by=TaskService), this one is owned by
    the State Evaluator (4.6), which polls rather than reacts to a mutation."""
    assert "task.overdue" in EVENT_VOCABULARY
    assert EVENT_VOCABULARY["task.overdue"].published_by == "app.services.state_evaluator.StateEvaluator"
    assert "task.overdue" in EVENT_PAYLOAD_REGISTRY
    assert EVENT_PAYLOAD_REGISTRY["task.overdue"] is TaskOverduePayload


def test_task_updated_payload_carries_fields_changed():
    """A consumer reads this to know which fields actually moved."""
    payload = TaskUpdatedPayload(
        task_id=uuid4(),
        status="todo",
        fields_changed=["priority"],
    )
    dumped = payload.model_dump(mode="json")
    assert dumped["fields_changed"] == ["priority"]


def test_task_deleted_payload_is_id_and_status_only():
    payload = TaskDeletedPayload(task_id=uuid4(), status="todo")
    assert set(payload.model_fields) == {"task_id", "status"}
