"""
Integration tests for Milestone 1.3 — Core Event Definitions.

Runs against the real dev Postgres (`cortex_db`) and Redis (`cortex-redis`)
used by the running app — same convention as `workflow_service/tests/
conftest.py` (reuses a real seeded user/workspace rather than building a
throwaway test DB). Every row created here is hard-deleted in teardown.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.events.event_bus import EventBus, reset_event_bus
from app.events.schemas import EventEnvelope
from app.models import (
    AgentConversation,
    AgentMessage,
    Note,
    Notification,
    ReminderMethod,
    ReminderStatus,
    Schedule,
    ScheduleReminder,
    ScheduleType,
)
from app.schemas import NoteCreate, NoteUpdate
from app.services.notes import NoteService
from app.services.reminder_worker import ReminderWorker
from app.services.schedule_service import ScheduleService

# Real seeded user/workspace in the dev DB (same convention as
# workflow_service/tests/conftest.py's TEST_USER_ID).
TEST_USER_ID = UUID("73552833-a6de-40a1-bb69-6e034ca75460")


@pytest_asyncio.fixture(autouse=True)
async def _seeded_user():
    """Tài khoản dev mà tệp này hardcode — dựng nếu DB không còn nó.

    Xem `tests/integration/seeded_user.py`: giả định "hàng này luôn có sẵn"
    đã sai một lần và làm 120 test đỏ cùng lúc.
    """
    from app.database_async import make_async_sessionmaker
    from tests.integration.seeded_user import ensure_seeded_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await ensure_seeded_user(db)
    await engine.dispose()

TEST_WORKSPACE_ID = UUID("4a31721d-13d1-4292-b89e-5838848bac8b")


@pytest_asyncio.fixture
async def event_subscriber():
    """Collects every event published during the test."""
    reset_event_bus()
    bus = EventBus()
    await bus.connect()

    received: list[EventEnvelope] = []

    async def collector(event: EventEnvelope):
        received.append(event)

    # EventBus wildcard matching requires equal segment count (see
    # EventBus._matches_pattern), so "*.*" alone misses 3-segment types like
    # schedule.reminder.due — subscribe both depths to catch everything.
    bus.subscribe("*.*", collector)
    bus.subscribe("*.*.*", collector)

    # Patch the process-wide singleton so service code's get_event_bus()
    # returns this same instance/subscriber.
    import app.events.event_bus as event_bus_module
    event_bus_module._event_bus = bus

    yield received

    bus.unsubscribe("*.*", collector)
    bus.unsubscribe("*.*.*", collector)
    event_bus_module._event_bus = None
    await bus.disconnect()


@pytest_asyncio.fixture
async def async_db():
    """
    Dedicated engine per test, NOT the module-level `AsyncSessionLocal`
    singleton. pytest-asyncio gives each test function its own event loop
    (asyncio_default_fixture_loop_scope=function); a lazily-created
    process-wide engine binds its connection pool to whichever loop touched
    it first, so any later test on a different loop hits "Future attached to
    a different loop" / "Event loop is closed". See ReminderWorker/
    GoogleSyncWorker's own `start()` docstrings — they hit this exact issue
    in production and work around it with `make_async_sessionmaker()`.
    """
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
    await engine.dispose()


@pytest.fixture
def sync_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _events_of_type(events: list[EventEnvelope], event_type: str) -> list[EventEnvelope]:
    return [e for e in events if e.type == event_type]


# ============================================================================
# NoteService
# ============================================================================

@pytest.mark.asyncio
async def test_note_created_event(async_db, event_subscriber):
    service = NoteService(async_db)
    note = await service.create_note(
        payload=NoteCreate(title="Event Test Note", content="hello"),
        user_id=TEST_USER_ID,
    )
    try:
        await asyncio.sleep(0.05)
        events = _events_of_type(event_subscriber, "note.created")
        assert len(events) == 1
        event = events[0]
        assert event.source == "NoteService"
        assert event.user_id == TEST_USER_ID
        # Container nằm trong payload, không phải trên envelope.
        assert event.payload["project_id"] is not None
        assert event.payload["note_id"] == note.id
        assert event.payload["title"] == "Event Test Note"
    finally:
        await async_db.execute(delete(Note).where(Note.id == note.id))
        await async_db.commit()


@pytest.mark.asyncio
async def test_note_updated_event_content_path(async_db, event_subscriber):
    service = NoteService(async_db)
    note = await service.create_note(
        payload=NoteCreate(title="To Update", content="original"),
        user_id=TEST_USER_ID,
    )
    try:
        event_subscriber.clear()
        updated = await service.update_note(
            note_id=note.id,
            user_id=TEST_USER_ID,
            payload=NoteUpdate(version=note.version, content="changed content"),
        )
        await asyncio.sleep(0.05)

        events = _events_of_type(event_subscriber, "note.updated")
        assert len(events) == 1
        assert events[0].payload["note_id"] == updated.id
        assert "content" in events[0].payload["fields_changed"]
    finally:
        await async_db.execute(delete(Note).where(Note.id == note.id))
        await async_db.commit()


@pytest.mark.asyncio
async def test_note_update_noop_does_not_publish(async_db, event_subscriber):
    """Saving the exact same content must not fire note.updated."""
    service = NoteService(async_db)
    note = await service.create_note(
        payload=NoteCreate(title="Noop", content="same"),
        user_id=TEST_USER_ID,
    )
    try:
        event_subscriber.clear()
        result = await service.update_note(
            note_id=note.id,
            user_id=TEST_USER_ID,
            payload=NoteUpdate(version=note.version, content="same"),
        )
        await asyncio.sleep(0.05)
        assert result.id == note.id
        assert _events_of_type(event_subscriber, "note.updated") == []
    finally:
        await async_db.execute(delete(Note).where(Note.id == note.id))
        await async_db.commit()


@pytest.mark.asyncio
async def test_note_deleted_event(async_db, event_subscriber):
    service = NoteService(async_db)
    note = await service.create_note(
        payload=NoteCreate(title="To Delete", content="bye"),
        user_id=TEST_USER_ID,
    )
    event_subscriber.clear()

    success = await service.soft_delete(note.id, TEST_USER_ID)
    await asyncio.sleep(0.05)

    assert success is True
    events = _events_of_type(event_subscriber, "note.deleted")
    assert len(events) == 1
    assert events[0].payload["note_id"] == note.id

    await async_db.execute(delete(Note).where(Note.id == note.id))
    await async_db.commit()


@pytest.mark.asyncio
async def test_event_publish_failure_does_not_break_note_create(async_db, monkeypatch):
    """Event publish raising must never prevent the note from being created."""
    from unittest.mock import AsyncMock

    reset_event_bus()
    broken_bus = AsyncMock()
    broken_bus.publish.side_effect = Exception("Event bus down!")

    async def _get_broken_bus():
        return broken_bus

    monkeypatch.setattr("app.services.notes.get_event_bus", _get_broken_bus)

    service = NoteService(async_db)
    note = await service.create_note(
        payload=NoteCreate(title="Resilient", content="x"),
        user_id=TEST_USER_ID,
    )
    try:
        assert note.id is not None
        assert note.title == "Resilient"
    finally:
        await async_db.execute(delete(Note).where(Note.id == note.id))
        await async_db.commit()


# ============================================================================
# ScheduleService
# ============================================================================

@pytest.mark.asyncio
async def test_schedule_created_event(sync_db, event_subscriber):
    service = ScheduleService(sync_db)
    now = datetime.now(timezone.utc)

    schedule = service.create_schedule_simple(
        user_id=TEST_USER_ID,
        title="Event Test Meeting",
        schedule_type=ScheduleType.PERSONAL,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )
    try:
        await asyncio.sleep(0.1)
        events = _events_of_type(event_subscriber, "schedule.created")
        assert len(events) == 1
        assert events[0].payload["schedule_id"] == schedule.id
        assert events[0].payload["title"] == "Event Test Meeting"
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


@pytest.mark.asyncio
async def test_schedule_update_and_complete_events(sync_db, event_subscriber):
    service = ScheduleService(sync_db)
    now = datetime.now(timezone.utc)
    schedule = service.create_schedule_simple(
        user_id=TEST_USER_ID,
        title="To Complete",
        schedule_type=ScheduleType.PERSONAL,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )
    try:
        event_subscriber.clear()

        updated = service.update_schedule_fields(
            schedule_id=schedule.id,
            user_id=TEST_USER_ID,
            is_completed=True,
        )
        await asyncio.sleep(0.1)

        updated_events = _events_of_type(event_subscriber, "schedule.updated")
        completed_events = _events_of_type(event_subscriber, "schedule.completed")
        assert len(updated_events) == 1
        assert "is_completed" in updated_events[0].payload["fields_changed"]
        assert len(completed_events) == 1
        assert completed_events[0].payload["schedule_id"] == updated.id
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


@pytest.mark.asyncio
async def test_schedule_update_without_completion_does_not_fire_completed(sync_db, event_subscriber):
    service = ScheduleService(sync_db)
    now = datetime.now(timezone.utc)
    schedule = service.create_schedule_simple(
        user_id=TEST_USER_ID,
        title="Just Rename",
        schedule_type=ScheduleType.PERSONAL,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )
    try:
        event_subscriber.clear()
        service.update_schedule_fields(schedule_id=schedule.id, user_id=TEST_USER_ID, title="Renamed")
        await asyncio.sleep(0.1)

        assert len(_events_of_type(event_subscriber, "schedule.updated")) == 1
        assert _events_of_type(event_subscriber, "schedule.completed") == []
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


# ============================================================================
# ReminderWorker
# ============================================================================

@pytest.mark.asyncio
async def test_reminder_due_event(async_db, sync_db, event_subscriber):
    """
    Exercises _send_notification() + _publish_reminder_due() directly rather
    than the full _process_due_reminders() loop: this dev DB's `reminderstatus`
    Postgres enum is missing the "processing" value that the PENDING->
    PROCESSING optimistic-lock UPDATE inside that loop requires (pre-existing
    schema drift, unrelated to Milestone 1.3 — same family of issue as the
    missing last_summary_message_id column found on ConversationStore).
    """
    now = datetime.now(timezone.utc)
    service = ScheduleService(sync_db)
    schedule = service.create_schedule_simple(
        user_id=TEST_USER_ID,
        title="Reminder Source Meeting",
        schedule_type=ScheduleType.PERSONAL,
        start_time=now + timedelta(minutes=10),
        end_time=now + timedelta(minutes=40),
    )

    reminder = ScheduleReminder(
        schedule_id=schedule.id,
        user_id=TEST_USER_ID,
        minutes_before=10,
        method=ReminderMethod.PUSH,
        status=ReminderStatus.PENDING,
        scheduled_at=now - timedelta(seconds=1),  # already due
    )
    async_db.add(reminder)
    await async_db.commit()

    try:
        event_subscriber.clear()

        worker = ReminderWorker()
        fetched_schedule = await worker._send_notification(reminder, async_db)
        assert fetched_schedule is not None
        await worker._publish_reminder_due(reminder, fetched_schedule)
        await asyncio.sleep(0.05)

        events = _events_of_type(event_subscriber, "schedule.reminder.due")
        assert len(events) == 1
        assert events[0].payload["schedule_id"] == schedule.id
        assert events[0].payload["reminder_offset_minutes"] == 10
    finally:
        # _send_notification() also flushes a Notification row (push method)
        await async_db.execute(delete(Notification).where(
            Notification.user_id == TEST_USER_ID,
            Notification.title == f"Reminder: {schedule.title}",
        ))
        await async_db.execute(delete(ScheduleReminder).where(ScheduleReminder.id == reminder.id))
        await async_db.commit()
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


# ============================================================================
# ConversationStore
# ============================================================================

@pytest.mark.asyncio
async def test_conversation_message_created_event(async_db, event_subscriber):
    from app.ai.agents.conversation_store import ConversationStore

    store = ConversationStore(async_db)
    conv = await store.get_or_create_conversation(user_id=TEST_USER_ID)
    await async_db.commit()

    try:
        event_subscriber.clear()
        message = await store.save_message(conversation_id=conv.id, role="user", content="hello world")
        await asyncio.sleep(0.05)

        events = _events_of_type(event_subscriber, "conversation.message.created")
        assert len(events) == 1
        assert events[0].conversation_id == conv.id
        assert events[0].payload["message_id"] == message.id
        assert events[0].payload["role"] == "user"
        assert events[0].payload["has_tool_calls"] is False
    finally:
        await async_db.execute(delete(AgentMessage).where(AgentMessage.conversation_id == conv.id))
        await async_db.execute(delete(AgentConversation).where(AgentConversation.id == conv.id))
        await async_db.commit()


@pytest.mark.asyncio
async def test_conversation_empty_message_does_not_publish(async_db, event_subscriber):
    from app.ai.agents.conversation_store import ConversationStore

    store = ConversationStore(async_db)
    conv = await store.get_or_create_conversation(user_id=TEST_USER_ID)
    await async_db.commit()

    try:
        event_subscriber.clear()
        result = await store.save_message(conversation_id=conv.id, role="user", content="   ")
        await asyncio.sleep(0.05)

        assert result is None
        assert _events_of_type(event_subscriber, "conversation.message.created") == []
    finally:
        await async_db.execute(delete(AgentConversation).where(AgentConversation.id == conv.id))
        await async_db.commit()


# ============================================================================
# ToolExecutionService
# ============================================================================

@pytest.mark.asyncio
async def test_tool_executed_event(async_db, event_subscriber):
    from app.ai.agents.tool_context import ToolContext
    from app.ai.agents.tool_execution_service import ToolExecutionService
    from app.ai.agents.tool_registry import get_tool_registry

    registry = get_tool_registry()
    store_stub = None  # execute_single_tool doesn't touch self.store
    service = ToolExecutionService(user=None, db=async_db, store=store_stub, registry=registry)

    ctx = ToolContext(user_id=TEST_USER_ID, async_db=async_db)

    # Chủ thể của test là *một tool chạy sinh đúng một event*, không phải
    # tool nào. Dùng `list_pending_tasks` vì nó nằm trong tám tool đang sống
    # (`app/ai/tools/__init__.py`); `search_notes` đã đóng băng theo Notes
    # (DESIGN 11.3) nên gọi nó ở đây chỉ đo được "tool không tồn tại".
    result = await service.execute_single_tool("list_pending_tasks", {}, ctx)
    await asyncio.sleep(0.05)

    events = _events_of_type(event_subscriber, "tool.executed")
    assert len(events) == 1
    assert events[0].payload["tool_name"] == "list_pending_tasks"
    assert events[0].payload["success"] is True
    assert events[0].payload["duration_ms"] >= 0
    assert result is not None


@pytest.mark.asyncio
async def test_tool_executed_event_on_failure(async_db, event_subscriber):
    from app.ai.agents.tool_context import ToolContext
    from app.ai.agents.tool_execution_service import ToolExecutionService
    from app.ai.agents.tool_registry import get_tool_registry

    registry = get_tool_registry()
    service = ToolExecutionService(user=None, db=async_db, store=None, registry=registry)
    ctx = ToolContext(user_id=TEST_USER_ID, async_db=async_db)

    result = await service.execute_single_tool("nonexistent_tool_xyz", {}, ctx)
    await asyncio.sleep(0.05)

    assert result["success"] is False
    events = _events_of_type(event_subscriber, "tool.executed")
    assert len(events) == 1
    assert events[0].payload["success"] is False
    assert events[0].payload["error"] is not None


# ============================================================================
# GoogleSyncWorker
# ============================================================================

@pytest.mark.asyncio
async def test_google_calendar_synced_event(sync_db, event_subscriber):
    """
    Unit-level check of _publish_sync_event: a full run through the real
    consume loop needs live Google OAuth credentials we don't have here, so
    this exercises the event-publishing helper directly with a real Schedule
    row and a synthetic task-like object.
    """
    from types import SimpleNamespace

    from app.models import SyncOperation
    from app.services.google_sync_worker import GoogleSyncWorker

    service = ScheduleService(sync_db)
    now = datetime.now(timezone.utc)
    schedule = service.create_schedule_simple(
        user_id=TEST_USER_ID,
        title="Sync Test",
        schedule_type=ScheduleType.PERSONAL,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )

    try:
        worker = GoogleSyncWorker()
        fake_task = SimpleNamespace(operation=SyncOperation.UPSERT.value, task_id="test-task-1")

        await worker._publish_sync_event(schedule, fake_task, 0.25, success=True)
        await asyncio.sleep(0.05)

        events = _events_of_type(event_subscriber, "google_calendar.synced")
        assert len(events) == 1
        assert events[0].payload["user_id"] == TEST_USER_ID
        assert events[0].payload["events_updated"] == 1
        assert events[0].payload["sync_duration_ms"] == 250
        assert events[0].payload["errors"] == []
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


# ============================================================================
# Cross-cutting
# ============================================================================

@pytest.mark.asyncio
async def test_all_ten_core_event_types_have_payload_schemas():
    from app.events.payloads import EVENT_PAYLOAD_REGISTRY

    expected_types = [
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
    ]
    for event_type in expected_types:
        assert event_type in EVENT_PAYLOAD_REGISTRY
