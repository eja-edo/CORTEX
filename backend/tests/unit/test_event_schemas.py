"""Unit tests for Milestone 1.1 — Event Schema Design."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.events.payloads import (
    EVENT_PAYLOAD_REGISTRY,
    ConversationMessageCreatedPayload,
    GoogleCalendarSyncedPayload,
    NoteCreatedPayload,
    NoteDeletedPayload,
    NoteUpdatedPayload,
    ReminderDuePayload,
    ScheduleCompletedPayload,
    ScheduleCreatedPayload,
    ScheduleUpdatedPayload,
    ToolExecutedPayload,
)
from app.events.schemas import EventEnvelope


# ============================================================================
# EventEnvelope
# ============================================================================

def test_event_envelope_creation():
    event = EventEnvelope(
        type="note.created",
        source="NoteService",
        user_id=uuid4(),
        payload={"note_id": str(uuid4()), "title": "Test"},
    )

    assert event.event_id is not None
    assert event.type == "note.created"
    assert event.version == "1.0.0"
    assert isinstance(event.timestamp, datetime)


def test_event_envelope_defaults_are_independent():
    """Each envelope must get its own event_id/timestamp, not a shared default."""
    e1 = EventEnvelope(type="note.created", source="NoteService")
    e2 = EventEnvelope(type="note.created", source="NoteService")
    assert e1.event_id != e2.event_id


def test_event_envelope_requires_type_and_source():
    with pytest.raises(ValidationError):
        EventEnvelope(source="NoteService")  # missing type

    with pytest.raises(ValidationError):
        EventEnvelope(type="note.created")  # missing source


def test_event_serialization_round_trip():
    original = EventEnvelope(
        type="note.created",
        source="NoteService",
        user_id=uuid4(),
        project_id=uuid4(),
        payload={"note_id": str(uuid4())},
    )

    event_dict = original.to_dict()
    assert isinstance(event_dict, dict)
    assert event_dict["type"] == "note.created"
    # to_dict() must be JSON-safe: UUID/datetime become plain strings
    assert isinstance(event_dict["user_id"], str)
    assert isinstance(event_dict["timestamp"], str)

    restored = EventEnvelope.from_dict(event_dict)
    assert restored.event_id == original.event_id
    assert restored.user_id == original.user_id
    assert restored.timestamp == original.timestamp


def test_event_envelope_timestamp_is_utc():
    event = EventEnvelope(type="note.created", source="NoteService")
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset() == timezone.utc.utcoffset(None)


# ============================================================================
# Payload schemas
# ============================================================================

def test_note_created_payload():
    payload = NoteCreatedPayload(
        note_id=uuid4(),
        project_id=uuid4(),
        title="Test Note",
        parent_note_id=uuid4(),
    )

    assert payload.title == "Test Note"
    assert payload.content_type == "markdown"  # default


def test_note_updated_payload_defaults():
    payload = NoteUpdatedPayload(note_id=uuid4(), version=2)
    assert payload.fields_changed == []


def test_note_deleted_payload():
    note_id = uuid4()
    payload = NoteDeletedPayload(note_id=note_id)
    assert payload.note_id == note_id


def test_schedule_created_payload():
    now = datetime.now(timezone.utc)
    payload = ScheduleCreatedPayload(
        schedule_id=uuid4(),
        title="Meeting",
        schedule_type="PERSONAL",
        start_time=now,
        end_time=now,
    )
    assert payload.is_recurring is False


def test_schedule_updated_payload():
    payload = ScheduleUpdatedPayload(schedule_id=uuid4(), fields_changed=["title"])
    assert "title" in payload.fields_changed


def test_schedule_completed_payload():
    payload = ScheduleCompletedPayload(schedule_id=uuid4(), completed_at=datetime.now(timezone.utc))
    assert payload.completed_at is not None


def test_reminder_due_payload():
    """`scheduled_at` and `start_time` are distinct instants: the reminder
    fires 15 minutes *before* the event starts. Conflating them is what made
    a 14:00 meeting announce itself as starting at 13:45."""
    start_time = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = ReminderDuePayload(
        reminder_id=uuid4(),
        schedule_id=uuid4(),
        schedule_title="Meeting",
        scheduled_at=start_time - timedelta(minutes=15),
        start_time=start_time,
        location="Phòng họp A",
        reminder_offset_minutes=15,
    )

    assert payload.schedule_title == "Meeting"
    assert payload.reminder_offset_minutes == 15
    assert payload.start_time == start_time
    assert payload.scheduled_at < payload.start_time
    assert payload.location == "Phòng họp A"


def test_conversation_message_created_payload():
    payload = ConversationMessageCreatedPayload(
        conversation_id=uuid4(),
        message_id=uuid4(),
        role="assistant",
        has_tool_calls=True,
    )
    assert payload.role == "assistant"
    assert payload.token_count is None


def test_tool_executed_payload():
    payload = ToolExecutedPayload(
        tool_name="search_notes",
        success=True,
        duration_ms=120,
    )
    assert payload.error is None
    assert payload.action_id is None


def test_google_calendar_synced_payload_defaults():
    payload = GoogleCalendarSyncedPayload(
        user_id=uuid4(),
        sync_direction="bidirectional",
        sync_duration_ms=500,
    )
    assert payload.events_added == 0
    assert payload.errors == []


def test_payload_validation_error_missing_required_field():
    with pytest.raises(ValidationError):
        NoteCreatedPayload(title="Test")  # thiếu note_id


@pytest.mark.parametrize("event_type", list(EVENT_PAYLOAD_REGISTRY.keys()))
def test_event_payload_registry_covers_all_core_events(event_type):
    """Every core event type from the README registry must resolve to a payload class."""
    payload_cls = EVENT_PAYLOAD_REGISTRY[event_type]
    assert payload_cls is not None


def test_event_payload_registry_has_the_ten_phase_1_core_events():
    """The 10 core Milestone 1.1 events must all still be registered. Checked
    as a subset, not an exact count — later phases add their own domains
    (task.* in 2.5), and a count assertion here would just be a chore for
    every one of them."""
    assert {
        "note.created",
        "note.updated",
        "note.deleted",
        "schedule.created",
        "schedule.updated",
        "schedule.completed",
        "schedule.reminder.due",
        "conversation.message.created",
        "tool.executed",
        "google_calendar.synced",
    } <= set(EVENT_PAYLOAD_REGISTRY.keys())
