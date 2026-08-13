"""Unit tests for Milestone 1.4 — Command Schema Design."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.commands.args import (
    ActionRevertArgs,
    NoteCreateArgs,
    NoteDeleteArgs,
    NoteUpdateArgs,
    PlanProposeArgs,
    ScheduleCreateArgs,
    ScheduleDeleteArgs,
    ScheduleUpdateArgs,
)
from app.commands.schemas import Command, CommandResult, CommandStatus, PermissionScope
from app.models import ScheduleType


# ============================================================================
# Command envelope
# ============================================================================

def test_command_envelope_creation():
    cmd = Command(
        command_name="note.create",
        args={"workspace_id": str(uuid4()), "title": "Test", "content": ""},
        requested_by=uuid4(),
    )

    assert cmd.command_id is not None
    assert cmd.status == CommandStatus.PENDING
    assert cmd.permission_scope == PermissionScope.WRITE
    assert cmd.schema_version == "1.0.0"
    assert cmd.revertable is False


def test_command_requires_requested_by():
    with pytest.raises(ValidationError):
        Command(command_name="note.create", args={})


def test_command_ids_are_unique():
    cmd1 = Command(command_name="note.create", args={}, requested_by=uuid4())
    cmd2 = Command(command_name="note.create", args={}, requested_by=uuid4())
    assert cmd1.command_id != cmd2.command_id


def test_command_result():
    result = CommandResult(
        command_id=str(uuid4()),
        success=True,
        data={"note_id": str(uuid4())},
        action_id=str(uuid4()),
        duration_ms=150,
        revert_hint="To undo: revert_action(...)",
    )

    assert result.success is True
    assert result.action_id is not None
    assert result.duration_ms == 150
    assert isinstance(result.executed_at, datetime)


def test_permission_scope_enum():
    assert PermissionScope.READ.value == "read"
    assert PermissionScope.WRITE.value == "write"
    assert PermissionScope.ADMIN.value == "admin"


def test_command_status_enum():
    assert CommandStatus.PENDING.value == "pending"
    assert CommandStatus.EXECUTING.value == "executing"
    assert CommandStatus.COMPLETED.value == "completed"
    assert CommandStatus.FAILED.value == "failed"
    assert CommandStatus.REVERTED.value == "reverted"


# ============================================================================
# NoteCreateArgs / NoteUpdateArgs / NoteDeleteArgs
# ============================================================================

def test_note_create_args_valid():
    args = NoteCreateArgs(workspace_id=uuid4(), title="Test Note", content="Content")
    assert args.title == "Test Note"
    assert args.content_type == "markdown"  # default


def test_note_create_args_strips_title_whitespace():
    args = NoteCreateArgs(workspace_id=uuid4(), title="  Padded  ", content="")
    assert args.title == "Padded"


def test_note_create_args_rejects_empty_title():
    with pytest.raises(ValidationError):
        NoteCreateArgs(workspace_id=uuid4(), title="   ", content="")


def test_note_create_args_rejects_title_too_long():
    with pytest.raises(ValidationError):
        NoteCreateArgs(workspace_id=uuid4(), title="x" * 300, content="")


def test_note_create_args_requires_workspace_id():
    with pytest.raises(ValidationError):
        NoteCreateArgs(title="Test", content="")


def test_note_update_args_optional_fields():
    args = NoteUpdateArgs(note_id=uuid4(), version=1)
    assert args.title is None
    assert args.content is None


def test_note_update_args_rejects_empty_title_when_provided():
    with pytest.raises(ValidationError):
        NoteUpdateArgs(note_id=uuid4(), version=1, title="   ")


def test_note_update_args_requires_version_at_least_1():
    with pytest.raises(ValidationError):
        NoteUpdateArgs(note_id=uuid4(), version=0)


def test_note_delete_args():
    note_id = uuid4()
    args = NoteDeleteArgs(note_id=note_id)
    assert args.note_id == note_id


# ============================================================================
# ScheduleCreateArgs / ScheduleUpdateArgs / ScheduleDeleteArgs
# ============================================================================

def test_schedule_create_args_valid():
    now = datetime.now(timezone.utc)
    args = ScheduleCreateArgs(
        title="Meeting",
        schedule_type=ScheduleType.PERSONAL,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )
    assert args.title == "Meeting"
    assert args.schedule_type == ScheduleType.PERSONAL


def test_schedule_create_args_accepts_string_schedule_type():
    """AI tool args arrive as plain dicts/strings, not enum instances."""
    now = datetime.now(timezone.utc)
    args = ScheduleCreateArgs(
        title="Meeting",
        schedule_type="PERSONAL",
        start_time=now,
        end_time=now + timedelta(hours=1),
    )
    assert args.schedule_type == ScheduleType.PERSONAL


def test_schedule_create_args_rejects_end_before_start():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        ScheduleCreateArgs(
            title="Meeting",
            schedule_type=ScheduleType.PERSONAL,
            start_time=now,
            end_time=now - timedelta(hours=1),
        )


def test_schedule_create_args_rejects_invalid_schedule_type():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        ScheduleCreateArgs(
            title="Meeting",
            schedule_type="NOT_A_REAL_TYPE",
            start_time=now,
            end_time=now + timedelta(hours=1),
        )


def test_schedule_update_args_all_optional():
    args = ScheduleUpdateArgs(schedule_id=uuid4())
    assert args.title is None
    assert args.is_completed is None


def test_schedule_delete_args():
    schedule_id = uuid4()
    args = ScheduleDeleteArgs(schedule_id=schedule_id)
    assert args.schedule_id == schedule_id


# ============================================================================
# ActionRevertArgs
# ============================================================================

def test_action_revert_args():
    args = ActionRevertArgs(action_id="some-snapshot-id")
    assert args.action_id == "some-snapshot-id"


def test_action_revert_args_requires_action_id():
    with pytest.raises(ValidationError):
        ActionRevertArgs()


# ============================================================================
# PlanProposeArgs (3.2 AI Planner)
# ============================================================================

def test_plan_propose_args_valid_flat():
    args = PlanProposeArgs(items=[{"key": "t1", "type": "task", "title": "Học ngữ pháp"}])
    assert len(args.items) == 1


def test_plan_propose_args_valid_nested():
    args = PlanProposeArgs(items=[
        {"key": "t1", "type": "task", "title": "Milestone"},
        {"key": "t2", "type": "task", "title": "Sub-task", "parent_key": "t1"},
    ])
    assert args.items[1].parent_key == "t1"


def test_plan_propose_args_rejects_empty_list():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[])


def test_plan_propose_args_rejects_duplicate_keys():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[
            {"key": "t1", "type": "task", "title": "a"},
            {"key": "t1", "type": "task", "title": "b"},
        ])


def test_plan_propose_args_rejects_unknown_parent_key():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[{"key": "t1", "type": "task", "title": "a", "parent_key": "nope"}])


def test_plan_propose_args_rejects_self_parent():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[{"key": "t1", "type": "task", "title": "a", "parent_key": "t1"}])


def test_plan_propose_args_rejects_event_as_parent():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[
            {
                "key": "e1", "type": "event", "title": "ev",
                "start_time": "2026-08-15T09:00:00", "end_time": "2026-08-15T10:00:00",
            },
            {"key": "t1", "type": "task", "title": "a", "parent_key": "e1"},
        ])


def test_plan_propose_args_rejects_cycle():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[
            {"key": "t1", "type": "task", "title": "a", "parent_key": "t2"},
            {"key": "t2", "type": "task", "title": "b", "parent_key": "t1"},
        ])


def test_plan_propose_args_rejects_task_with_event_fields():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[
            {"key": "t1", "type": "task", "title": "a", "start_time": "2026-08-15T09:00:00"},
        ])


def test_plan_propose_args_event_requires_start_and_end():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[{"key": "e1", "type": "event", "title": "ev"}])


def test_plan_propose_args_event_accepts_recurrence():
    args = PlanProposeArgs(items=[{
        "key": "e1", "type": "event", "title": "ev",
        "start_time": "2026-08-10T19:00:00", "end_time": "2026-08-10T19:45:00",
        "recurrence": {"freq": "WEEKLY", "interval": 1, "until": "2027-02-22T19:45:00"},
    }])
    assert args.items[0].recurrence["freq"] == "WEEKLY"


def test_plan_propose_args_task_links_to_event():
    args = PlanProposeArgs(items=[
        {
            "key": "e1", "type": "event", "title": "ev",
            "start_time": "2026-08-10T19:00:00", "end_time": "2026-08-10T19:45:00",
        },
        {"key": "t1", "type": "task", "title": "daily words", "related_event_key": "e1"},
    ])
    assert args.items[1].related_event_key == "e1"


def test_plan_propose_args_rejects_related_event_key_pointing_to_task():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[
            {"key": "t1", "type": "task", "title": "a"},
            {"key": "t2", "type": "task", "title": "b", "related_event_key": "t1"},
        ])


def test_plan_propose_args_rejects_dangling_related_event_key():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[{"key": "t1", "type": "task", "title": "a", "related_event_key": "nope"}])


def test_plan_propose_args_rejects_task_with_recurrence():
    with pytest.raises(ValidationError):
        PlanProposeArgs(items=[{"key": "t1", "type": "task", "title": "a", "recurrence": {"freq": "DAILY"}}])
