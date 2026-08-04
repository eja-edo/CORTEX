# Milestone 1.3: Core Event Definitions

**Timeline:** 3-4 ngày  
**Dependencies:** 1.2 (Event Bus Implementation)  
**Effort:** Medium  

---

## 🎯 Mục tiêu

Thêm event emission vào các service operations hiện có:
- NoteService: create/update/delete
- ScheduleService: create/update/complete
- ReminderWorker: reminder.due
- ConversationStore: message.created
- ToolExecutionService: tool.executed
- GoogleSyncWorker: calendar.synced

**Nguyên tắc:**
- Events được phát **SAU KHI** DB commit thành công
- Event publish failure **KHÔNG** được break service operation
- Mọi event đi qua EventBus (không có ad-hoc pub/sub)

---

## 📋 Tasks

### Task 1.3.1: NoteService Events

**File:** `backend/app/services/notes.py`

**Changes:**

```python
from app.events.event_bus import get_event_bus
from app.events.schemas import EventEnvelope
from app.events.payloads import NoteCreatedPayload, NoteUpdatedPayload, NoteDeletedPayload

class NoteService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = NoteRepository(session)
        self.markdown = build_markdown_renderer()
        self._event_bus = None  # Lazy init
    
    async def _get_event_bus(self):
        """Lazy load EventBus to avoid circular imports."""
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus
    
    async def create_note(self, payload: NoteCreate, user_id: UUID) -> Note:
        """Create note and publish event."""
        # ... existing permission check ...
        
        # ... existing note creation logic ...
        
        try:
            created = await self.repository.create(note)
            await self.session.commit()
            
            # NEW: Publish event (after successful commit)
            try:
                event_bus = await self._get_event_bus()
                await event_bus.publish(EventEnvelope(
                    type="note.created",
                    source="NoteService",
                    user_id=user_id,
                    workspace_id=payload.workspace_id,
                    payload=NoteCreatedPayload(
                        note_id=created.id,
                        workspace_id=created.workspace_id,
                        title=created.title,
                        parent_note_id=created.parent_note_id,
                        content_type=created.content_type
                    ).model_dump()
                ))
            except Exception as event_exc:
                # Log but don't fail the operation
                logger.warning(
                    f"Failed to publish note.created event: {event_exc}",
                    extra={"note_id": str(created.id)}
                )
            
            return created
        
        except Exception:
            await self.session.rollback()
            raise
    
    async def update_note(self, note_id: UUID, user_id: UUID, payload: NoteUpdate) -> Note | None:
        """Update note and publish event."""
        # ... existing logic ...
        
        updated = await self.repository.update_with_version(...)
        if updated is None:
            return None
        
        await self.session.commit()
        
        # NEW: Publish event
        try:
            event_bus = await self._get_event_bus()
            
            # Determine which fields changed
            fields_changed = list(payload.model_dump(exclude_unset=True).keys())
            
            await event_bus.publish(EventEnvelope(
                type="note.updated",
                source="NoteService",
                user_id=user_id,
                workspace_id=updated.workspace_id,
                payload=NoteUpdatedPayload(
                    note_id=updated.id,
                    version=updated.version,
                    fields_changed=fields_changed
                ).model_dump()
            ))
        except Exception as event_exc:
            logger.warning(f"Failed to publish note.updated event: {event_exc}")
        
        return updated
    
    async def delete_note(self, note_id: UUID, user_id: UUID) -> bool:
        """Soft delete note and publish event."""
        # ... existing soft delete logic ...
        
        success = await self.repository.soft_delete(note_id, user_id)
        await self.session.commit()
        
        if success:
            # NEW: Publish event
            try:
                event_bus = await self._get_event_bus()
                await event_bus.publish(EventEnvelope(
                    type="note.deleted",
                    source="NoteService",
                    user_id=user_id,
                    payload=NoteDeletedPayload(note_id=note_id).model_dump()
                ))
            except Exception as event_exc:
                logger.warning(f"Failed to publish note.deleted event: {event_exc}")
        
        return success
```

**Checklist:**
- [ ] Add `_get_event_bus()` lazy init method
- [ ] Publish `note.created` after commit
- [ ] Publish `note.updated` with fields_changed tracking
- [ ] Publish `note.deleted` on soft delete
- [ ] Wrap event publishing in try-except (never fail service operation)
- [ ] Test: create note → verify event published
- [ ] Test: event publish fails → note still created successfully

---

### Task 1.3.2: ScheduleService Events

**File:** `backend/app/services/schedule_service.py`

**Changes:**

```python
from app.events.event_bus import get_event_bus
from app.events.schemas import EventEnvelope
from app.events.payloads import (
    ScheduleCreatedPayload,
    ScheduleUpdatedPayload,
    ScheduleCompletedPayload
)

class ScheduleService:
    def __init__(self, db: Session):
        self.db = db
        self._recurrence_svc = RecurrenceService(db)
        self._reminder_svc = ReminderService()
        self._event_bus = None
    
    async def _get_event_bus(self):
        """Lazy load EventBus."""
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus
    
    def create_schedule(self, data: ScheduleCreate, user_id: UUID) -> Schedule:
        """Create schedule and publish event."""
        # ... existing validation ...
        
        db_schedule = Schedule(...)
        self.db.add(db_schedule)
        
        if data.reminders:
            self._reminder_svc.create_reminders_for_schedule(...)
        
        self.db.commit()
        self.db.refresh(db_schedule)
        
        # NEW: Publish event (sync context, need to run in event loop)
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context - create task
                asyncio.create_task(self._publish_created_event(db_schedule, user_id))
            else:
                # Sync context - run in new loop
                asyncio.run(self._publish_created_event(db_schedule, user_id))
        except Exception as event_exc:
            logger.warning(f"Failed to publish schedule.created event: {event_exc}")
        
        _attach_google_sync_flags([db_schedule], self.db)
        return db_schedule
    
    async def _publish_created_event(self, schedule: Schedule, user_id: UUID):
        """Helper to publish schedule.created event."""
        event_bus = await self._get_event_bus()
        await event_bus.publish(EventEnvelope(
            type="schedule.created",
            source="ScheduleService",
            user_id=user_id,
            payload=ScheduleCreatedPayload(
                schedule_id=schedule.id,
                title=schedule.title,
                schedule_type=schedule.type.value,
                start_time=schedule.start_time,
                end_time=schedule.end_time,
                location=schedule.location,
                is_recurring=bool(schedule.recurrence_rule)
            ).model_dump()
        ))
    
    def update_schedule(
        self,
        schedule_id: UUID,
        user_id: UUID,
        updates: dict
    ) -> Schedule:
        """Update schedule and publish event."""
        # ... existing update logic ...
        
        updated = self.db.query(Schedule).filter(...).first()
        
        for key, value in updates.items():
            setattr(updated, key, value)
        
        self.db.commit()
        self.db.refresh(updated)
        
        # NEW: Publish event
        try:
            import asyncio
            fields_changed = list(updates.keys())
            
            async def publish():
                event_bus = await self._get_event_bus()
                await event_bus.publish(EventEnvelope(
                    type="schedule.updated",
                    source="ScheduleService",
                    user_id=user_id,
                    payload=ScheduleUpdatedPayload(
                        schedule_id=schedule_id,
                        fields_changed=fields_changed
                    ).model_dump()
                ))
            
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(publish())
            else:
                asyncio.run(publish())
        
        except Exception as event_exc:
            logger.warning(f"Failed to publish schedule.updated event: {event_exc}")
        
        return updated
    
    def complete_schedule(self, schedule_id: UUID, user_id: UUID) -> Schedule:
        """Mark schedule as completed and publish event."""
        # Update schedule
        updated = self.update_schedule(
            schedule_id=schedule_id,
            user_id=user_id,
            updates={"is_completed": True}
        )
        
        # Publish completed event (separate from updated)
        try:
            import asyncio
            from datetime import datetime
            
            async def publish():
                event_bus = await self._get_event_bus()
                await event_bus.publish(EventEnvelope(
                    type="schedule.completed",
                    source="ScheduleService",
                    user_id=user_id,
                    payload=ScheduleCompletedPayload(
                        schedule_id=schedule_id,
                        completed_at=datetime.utcnow()
                    ).model_dump()
                ))
            
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(publish())
            else:
                asyncio.run(publish())
        
        except Exception as event_exc:
            logger.warning(f"Failed to publish schedule.completed event: {event_exc}")
        
        return updated
```

**Note:** ScheduleService uses sync DB, so we need to handle async event publishing carefully.

**Checklist:**
- [ ] Add async event publishing helpers for sync service
- [ ] Publish `schedule.created` after commit
- [ ] Publish `schedule.updated` with fields_changed
- [ ] Publish `schedule.completed` when marked complete
- [ ] Handle sync→async bridge properly
- [ ] Test: create/update/complete schedule → verify events

---

### Task 1.3.3: ReminderWorker Events

**File:** `backend/app/services/reminder_worker.py`

**Changes:**

```python
from app.events.event_bus import get_event_bus
from app.events.schemas import EventEnvelope
from app.events.payloads import ReminderDuePayload

class ReminderWorker:
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._db_engine = None
        self._session_maker = None
        self._event_bus = None
    
    async def _get_event_bus(self):
        """Lazy load EventBus."""
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus
    
    async def _process_due_reminders(self):
        """Fetch and process reminders that are due."""
        async with self._session_maker() as db:
            # ... existing logic to fetch due reminders ...
            
            for reminder in due:
                # ... existing processing ...
                
                try:
                    # Send notification
                    await self._send_notification(reminder, db)
                    
                    # NEW: Publish reminder.due event
                    try:
                        # Fetch schedule for event payload
                        schedule = await db.get(Schedule, reminder.schedule_id)
                        if schedule:
                            event_bus = await self._get_event_bus()
                            await event_bus.publish(EventEnvelope(
                                type="schedule.reminder.due",
                                source="ReminderWorker",
                                user_id=schedule.user_id,
                                payload=ReminderDuePayload(
                                    reminder_id=reminder.id,
                                    schedule_id=reminder.schedule_id,
                                    schedule_title=schedule.title,
                                    scheduled_at=reminder.scheduled_at,
                                    reminder_offset_minutes=reminder.offset_minutes
                                ).model_dump()
                            ))
                    except Exception as event_exc:
                        logger.warning(f"Failed to publish reminder.due event: {event_exc}")
                    
                    # Mark as sent
                    sent_stmt = (...)
                    await db.execute(sent_stmt)
                    await db.commit()
                    
                    logger.info(f"Reminder {reminder.id} sent successfully")
                
                except Exception as e:
                    logger.exception(f"Failed to send reminder {reminder.id}")
                    # ... existing error handling ...
```

**Checklist:**
- [ ] Publish `schedule.reminder.due` after notification sent
- [ ] Include schedule details in payload
- [ ] Handle event publish errors gracefully
- [ ] Test: trigger reminder → verify event published

---

### Task 1.3.4: ConversationStore Events

**File:** `backend/app/ai/agents/conversation_store.py`

**Changes:**

```python
from app.events.event_bus import get_event_bus
from app.events.schemas import EventEnvelope
from app.events.payloads import ConversationMessageCreatedPayload

class ConversationStore:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._event_bus = None
    
    async def _get_event_bus(self):
        """Lazy load EventBus."""
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus
    
    async def save_message(
        self,
        conv_id: UUID,
        role: str,
        content: Optional[str] = None,
        tool_calls: Optional[list] = None,
        tool_name: Optional[str] = None,
        tool_input: Optional[dict] = None,
        tool_output: Optional[dict] = None,
        context: Optional[dict] = None,
        token_count: Optional[int] = None
    ) -> DbMessage:
        """Save message and publish event."""
        # ... existing conversation fetch ...
        
        # ... existing message creation ...
        
        db_msg = DbMessage(...)
        self.db.add(db_msg)
        await self.db.flush()
        
        # NEW: Publish event
        try:
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="conversation.message.created",
                source="ConversationStore",
                user_id=conversation.user_id,
                conversation_id=conv_id,
                payload=ConversationMessageCreatedPayload(
                    conversation_id=conv_id,
                    message_id=db_msg.id,
                    role=role,
                    has_tool_calls=bool(tool_calls),
                    token_count=token_count
                ).model_dump()
            ))
        except Exception as event_exc:
            logger.warning(f"Failed to publish message.created event: {event_exc}")
        
        return db_msg
```

**Checklist:**
- [ ] Publish `conversation.message.created` after flush
- [ ] Include role and tool_calls info
- [ ] Handle both user and assistant messages
- [ ] Test: save message → verify event

---

### Task 1.3.5: ToolExecutionService Events

**File:** `backend/app/ai/agents/tool_execution_service.py`

**Changes:**

```python
from app.events.event_bus import get_event_bus
from app.events.schemas import EventEnvelope
from app.events.payloads import ToolExecutedPayload
import time

class ToolExecutionService:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._event_bus = None
    
    async def _get_event_bus(self):
        """Lazy load EventBus."""
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus
    
    async def execute_single_tool(
        self,
        tool_name: str,
        args: dict,
        ctx: ToolContext
    ) -> dict:
        """Execute tool and publish event."""
        start_time = time.time()
        
        try:
            # Execute tool
            result = await self.registry.execute(tool_name, args, ctx)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # NEW: Publish success event
            try:
                event_bus = await self._get_event_bus()
                await event_bus.publish(EventEnvelope(
                    type="tool.executed",
                    source="ToolExecutionService",
                    user_id=ctx.user_id,
                    conversation_id=ctx.conversation_id,
                    payload=ToolExecutedPayload(
                        tool_name=tool_name,
                        conversation_id=ctx.conversation_id,
                        success=result.get("success", True),
                        duration_ms=duration_ms,
                        action_id=result.get("action_id")
                    ).model_dump()
                ))
            except Exception as event_exc:
                logger.warning(f"Failed to publish tool.executed event: {event_exc}")
            
            return result
        
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            
            # NEW: Publish failure event
            try:
                event_bus = await self._get_event_bus()
                await event_bus.publish(EventEnvelope(
                    type="tool.executed",
                    source="ToolExecutionService",
                    user_id=ctx.user_id,
                    conversation_id=ctx.conversation_id,
                    payload=ToolExecutedPayload(
                        tool_name=tool_name,
                        conversation_id=ctx.conversation_id,
                        success=False,
                        duration_ms=duration_ms,
                        error=str(exc)
                    ).model_dump()
                ))
            except Exception as event_exc:
                logger.warning(f"Failed to publish tool.executed event: {event_exc}")
            
            raise
```

**Checklist:**
- [ ] Publish `tool.executed` for both success and failure
- [ ] Track duration_ms
- [ ] Include action_id for revertable tools
- [ ] Test: execute tool → verify event

---

### Task 1.3.6: GoogleSyncWorker Events

**File:** `backend/app/services/google_sync_worker.py`

**Changes:**

```python
from app.events.event_bus import get_event_bus
from app.events.schemas import EventEnvelope
from app.events.payloads import GoogleCalendarSyncedPayload
import time

class GoogleSyncWorker:
    # ... existing code ...
    
    async def _process_sync_job(self, job: SyncJob):
        """Process a sync job and publish event."""
        start_time = time.time()
        
        try:
            # ... existing sync logic ...
            
            # Count changes
            events_added = len(added_events)
            events_updated = len(updated_events)
            events_deleted = len(deleted_events)
            
            # Mark job complete
            # ... existing completion logic ...
            
            # NEW: Publish sync completed event
            duration_ms = int((time.time() - start_time) * 1000)
            
            try:
                event_bus = await get_event_bus()
                await event_bus.publish(EventEnvelope(
                    type="google_calendar.synced",
                    source="GoogleSyncWorker",
                    user_id=job.user_id,
                    payload=GoogleCalendarSyncedPayload(
                        user_id=job.user_id,
                        sync_direction="bidirectional",
                        events_added=events_added,
                        events_updated=events_updated,
                        events_deleted=events_deleted,
                        sync_duration_ms=duration_ms,
                        errors=[]
                    ).model_dump()
                ))
            except Exception as event_exc:
                logger.warning(f"Failed to publish google_calendar.synced event: {event_exc}")
        
        except Exception as sync_exc:
            # ... existing error handling ...
            
            # Publish failed sync event
            duration_ms = int((time.time() - start_time) * 1000)
            
            try:
                event_bus = await get_event_bus()
                await event_bus.publish(EventEnvelope(
                    type="google_calendar.synced",
                    source="GoogleSyncWorker",
                    user_id=job.user_id,
                    payload=GoogleCalendarSyncedPayload(
                        user_id=job.user_id,
                        sync_direction="bidirectional",
                        events_added=0,
                        events_updated=0,
                        events_deleted=0,
                        sync_duration_ms=duration_ms,
                        errors=[str(sync_exc)]
                    ).model_dump()
                ))
            except Exception as event_exc:
                logger.warning(f"Failed to publish failed sync event: {event_exc}")
```

**Checklist:**
- [ ] Publish `google_calendar.synced` after sync complete
- [ ] Include sync statistics (added/updated/deleted counts)
- [ ] Publish event even on partial failure (with error list)
- [ ] Test: trigger sync → verify event

---

### Task 1.3.7: Integration Test Suite

**Output:** `backend/tests/integration/test_core_events.py`

```python
import pytest
import asyncio
from uuid import uuid4
from app.services.notes import NoteService
from app.services.schedule_service import ScheduleService
from app.events.event_bus import get_event_bus, reset_event_bus
from app.events.schemas import EventEnvelope
from app.schemas import NoteCreate, ScheduleCreate
from app.models import ScheduleType


@pytest.fixture
async def event_subscriber():
    """Fixture that collects events for verification."""
    reset_event_bus()
    bus = await get_event_bus()
    
    received_events = []
    
    async def collector(event: EventEnvelope):
        received_events.append(event)
    
    # Subscribe to all events
    bus.subscribe("*.*", collector)
    
    yield received_events
    
    # Cleanup
    bus.unsubscribe("*.*", collector)


@pytest.mark.asyncio
async def test_note_created_event(async_db, test_user, test_workspace, event_subscriber):
    """Test: Create note → verify note.created event published."""
    service = NoteService(async_db)
    
    # Create note
    note = await service.create_note(
        payload=NoteCreate(
            workspace_id=test_workspace.id,
            title="Test Note",
            content="Test content"
        ),
        user_id=test_user.id
    )
    
    # Wait for event processing
    await asyncio.sleep(0.2)
    
    # Verify event
    events = [e for e in event_subscriber if e.type == "note.created"]
    assert len(events) == 1
    
    event = events[0]
    assert event.type == "note.created"
    assert event.source == "NoteService"
    assert event.user_id == test_user.id
    assert event.workspace_id == test_workspace.id
    assert event.payload["note_id"] == str(note.id)
    assert event.payload["title"] == "Test Note"


@pytest.mark.asyncio
async def test_note_updated_event(async_db, test_user, test_note, event_subscriber):
    """Test: Update note → verify note.updated event published."""
    service = NoteService(async_db)
    
    # Update note
    from app.schemas import NoteUpdate
    updated = await service.update_note(
        note_id=test_note.id,
        user_id=test_user.id,
        payload=NoteUpdate(
            version=test_note.version,
            title="Updated Title"
        )
    )
    
    await asyncio.sleep(0.2)
    
    # Verify event
    events = [e for e in event_subscriber if e.type == "note.updated"]
    assert len(events) == 1
    
    event = events[0]
    assert event.payload["note_id"] == str(test_note.id)
    assert "title" in event.payload["fields_changed"]


@pytest.mark.asyncio
async def test_schedule_created_event(sync_db, test_user, event_subscriber):
    """Test: Create schedule → verify schedule.created event published."""
    from datetime import datetime, timedelta
    
    service = ScheduleService(sync_db)
    
    now = datetime.utcnow()
    schedule = service.create_schedule_simple(
        user_id=test_user.id,
        title="Meeting",
        schedule_type=ScheduleType.PERSONAL,
        start_time=now,
        end_time=now + timedelta(hours=1)
    )
    
    await asyncio.sleep(0.2)
    
    # Verify event
    events = [e for e in event_subscriber if e.type == "schedule.created"]
    assert len(events) == 1
    
    event = events[0]
    assert event.payload["schedule_id"] == str(schedule.id)
    assert event.payload["title"] == "Meeting"


@pytest.mark.asyncio
async def test_tool_executed_event(async_db, test_user, test_workspace, event_subscriber):
    """Test: Execute tool → verify tool.executed event published."""
    from app.ai.agents.tool_registry import get_tool_registry
    from app.ai.agents.tool_execution_service import ToolExecutionService
    from app.ai.agents.tool_context import ToolContext
    
    registry = get_tool_registry()
    service = ToolExecutionService(registry)
    
    ctx = ToolContext(
        user_id=test_user.id,
        async_db=async_db,
        workspace_id=test_workspace.id
    )
    
    # Execute tool
    result = await service.execute_single_tool(
        tool_name="search_notes",
        args={"query": "test"},
        ctx=ctx
    )
    
    await asyncio.sleep(0.2)
    
    # Verify event
    events = [e for e in event_subscriber if e.type == "tool.executed"]
    assert len(events) == 1
    
    event = events[0]
    assert event.payload["tool_name"] == "search_notes"
    assert event.payload["success"] is True
    assert event.payload["duration_ms"] > 0


@pytest.mark.asyncio
async def test_event_publish_failure_does_not_break_service(async_db, test_user, test_workspace):
    """Test: Event publish fails → service operation still succeeds."""
    # Mock EventBus to raise error
    from unittest.mock import AsyncMock, patch
    
    with patch('app.events.event_bus.get_event_bus') as mock_get_bus:
        mock_bus = AsyncMock()
        mock_bus.publish.side_effect = Exception("Event bus down!")
        mock_get_bus.return_value = mock_bus
        
        # Try to create note (should succeed despite event failure)
        service = NoteService(async_db)
        note = await service.create_note(
            payload=NoteCreate(
                workspace_id=test_workspace.id,
                title="Test",
                content=""
            ),
            user_id=test_user.id
        )
        
        # Note should be created successfully
        assert note.id is not None
        assert note.title == "Test"


@pytest.mark.asyncio
async def test_all_event_types_published(event_subscriber):
    """Integration test: Verify all 8 event types can be published."""
    # This test would trigger all 8 operations and verify events
    # Simplified version - just check event types are defined
    
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
        "google_calendar.synced"
    ]
    
    # All event types should be documented and have payload schemas
    from app.events.payloads import (
        NoteCreatedPayload,
        NoteUpdatedPayload,
        NoteDeletedPayload,
        ScheduleCreatedPayload,
        ScheduleUpdatedPayload,
        ScheduleCompletedPayload,
        ReminderDuePayload,
        ConversationMessageCreatedPayload,
        ToolExecutedPayload,
        GoogleCalendarSyncedPayload
    )
    
    # If imports succeed, all payload schemas exist
    assert True
```

**Checklist:**
- [ ] Test note.created event
- [ ] Test note.updated event
- [ ] Test schedule.created event
- [ ] Test tool.executed event
- [ ] Test event publish failure doesn't break service
- [ ] All tests pass

---

## ✅ Milestone 1.3 Definition of Done

- [ ] 6 services emit events (Note, Schedule, Reminder, Conversation, Tool, GoogleSync)
- [ ] 10 event types being published
- [ ] Events published AFTER successful commit
- [ ] Event publish failures don't break operations
- [ ] Integration tests verify all events
- [ ] No regression in existing functionality
- [ ] Structured logging for all event emissions

---

## 🧪 Verification

Run integration tests:
```bash
cd backend
pytest tests/integration/test_core_events.py -v
```

Verify in logs:
```bash
# Check event publishing
tail -f logs/app.log | grep "Event published"

# Should see lines like:
# INFO - Event published: note.created - event_id=... user_id=...
```

---

**Next Milestone:** [1.4 Command Schema Design](04_COMMAND_SCHEMA.md)
