# Milestone 1.1: Event Schema Design

**Timeline:** 2-3 ngày  
**Dependencies:** None (có thể bắt đầu ngay)  
**Effort:** Small  

---

## 🎯 Mục tiêu

Định nghĩa event envelope chuẩn thống nhất cho toàn hệ thống, thay thế các format khác nhau hiện tại:
- Redis Stream messages (transcription, LLM processing)
- SSE events (sync status, notifications)
- Workflow events

**Nguyên tắc:**
- Một format duy nhất cho mọi event
- Schema versioning để hỗ trợ evolution
- Strongly-typed với Pydantic
- JSON serialization chuẩn

---

## 📋 Tasks

### Task 1.1.1: Design Event Envelope Schema

**Output:** `backend/app/events/schemas.py`

```python
"""
Event schemas for Cortex Event Bus.

All events in the system follow this unified envelope format.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    """
    Unified event envelope for all events in Cortex.
    
    Format: domain.entity.action
    Examples: 
      - schedule.reminder.due
      - note.created
      - tool.executed
      
    Design principles:
    - Self-contained: All metadata in envelope
    - Traceable: correlation_id for request tracing
    - Versioned: schema_version for evolution
    - Timestamped: UTC timestamp for ordering
    """
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    type: str = Field(..., description="Event type: domain.entity.action")
    source: str = Field(..., description="Event source service/component")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = Field(None, description="Request trace ID")
    user_id: Optional[UUID] = Field(None, description="User who triggered event")
    workspace_id: Optional[UUID] = Field(None, description="Workspace context")
    conversation_id: Optional[UUID] = Field(None, description="Conversation context")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event-specific data")
    version: str = Field(default="1.0.0", description="Event schema version")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for Redis/JSON serialization."""
        return self.model_dump(mode='json')
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'EventEnvelope':
        """Parse from Redis/JSON dict."""
        # Convert ISO strings back to datetime
        if 'timestamp' in data and isinstance(data['timestamp'], str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        
        # Convert string UUIDs back to UUID objects
        for field in ['user_id', 'workspace_id', 'conversation_id']:
            if field in data and data[field] and isinstance(data[field], str):
                data[field] = UUID(data[field])
        
        return cls(**data)
```

**Checklist:**
- [ ] EventEnvelope Pydantic model với validation
- [ ] Version field để hỗ trợ schema evolution
- [ ] JSON serialization methods (to_dict/from_dict)
- [ ] Context fields: user_id, workspace_id, conversation_id
- [ ] Tracing fields: correlation_id, source
- [ ] Documentation với ví dụ cho từng field
- [ ] Unit test cho serialization/deserialization

---

### Task 1.1.2: Define Event Type Naming Convention

**Output:** `backend/app/events/README.md`

```markdown
# Event Architecture

## Event Naming Convention

**Format:** `{domain}.{entity}.{action}`

### Domains:
- `note`: Note operations
- `schedule`: Schedule operations  
- `conversation`: Conversation operations
- `tool`: Tool execution
- `command`: Command execution (Phase 1.5+)
- `google_calendar`: External integrations
- `workflow`: Workflow operations
- `goal`: Goal operations (Phase 2)
- `task`: Task operations (Phase 2)

### Entities:
- `note`, `schedule`, `reminder`, `message`, `action`, etc.
- Có thể nested: `schedule.reminder` → `schedule.reminder.due`

### Actions:
- **CRUD:** `created`, `updated`, `deleted`
- **State transitions:** `completed`, `failed`, `cancelled`, `archived`
- **Time-based:** `due`, `overdue`, `approaching`
- **External:** `synced`, `exported`, `imported`
- **Execution:** `executed`, `started`, `finished`

---

## Event Type Registry

### Core Events (Phase 1.3)

| Event Type | Domain | Description | Payload Schema |
|-----------|--------|-------------|----------------|
| `note.created` | note | Note was created | NoteCreatedPayload |
| `note.updated` | note | Note was updated | NoteUpdatedPayload |
| `note.deleted` | note | Note was soft-deleted | NoteDeletedPayload |
| `schedule.created` | schedule | Schedule was created | ScheduleCreatedPayload |
| `schedule.updated` | schedule | Schedule was updated | ScheduleUpdatedPayload |
| `schedule.completed` | schedule | Schedule marked as complete | ScheduleCompletedPayload |
| `schedule.reminder.due` | schedule | Reminder is due | ReminderDuePayload |
| `conversation.message.created` | conversation | Message added to conversation | MessageCreatedPayload |
| `tool.executed` | tool | Tool finished execution | ToolExecutedPayload |
| `google_calendar.synced` | google_calendar | Calendar sync completed | GoogleCalendarSyncedPayload |

### Command Events (Phase 1.5)

| Event Type | Domain | Description |
|-----------|--------|-------------|
| `command.note.create` | command | note.create command executed |
| `command.note.update` | command | note.update command executed |
| `command.schedule.create` | command | schedule.create command executed |
| `command.action.revert` | command | action.revert command executed |

---

## Event Flow

```
Service Operation (e.g., NoteService.create_note)
    ↓
Business Logic Executes
    ↓
DB Transaction Commits
    ↓
Event Published to EventBus
    ↓
EventBus Routes to Subscribers
    ├─ Subscriber 1: Workflow Trigger
    ├─ Subscriber 2: Analytics Logger
    ├─ Subscriber 3: Frontend SSE
    └─ Subscriber 4: External Integration
```

**Important:** Events are published AFTER successful commit to ensure consistency.

---

## Versioning Strategy

Events use semantic versioning: `MAJOR.MINOR.PATCH`

### Version Changes

**PATCH (1.0.0 → 1.0.1):**
- Documentation fixes
- No schema changes

**MINOR (1.0.0 → 1.1.0):**
- Add optional fields to payload
- Backward compatible
- Old consumers continue working

**MAJOR (1.0.0 → 2.0.0):**
- Breaking changes (field removed/renamed)
- Requires consumer updates
- EventBus can route both versions during transition

### Example Evolution

```python
# v1.0.0: Initial
class NoteCreatedPayload(BaseModel):
    note_id: UUID
    title: str

# v1.1.0: Add optional field (backward compatible)
class NoteCreatedPayload(BaseModel):
    note_id: UUID
    title: str
    tags: Optional[list[str]] = None  # NEW, optional

# v2.0.0: Breaking change (field renamed)
class NoteCreatedPayload(BaseModel):
    note_id: UUID
    heading: str  # RENAMED from 'title'
    tags: Optional[list[str]] = None
```

Consumers check `event.version` to handle different schemas.

---

## Testing Events

```python
from app.events.schemas import EventEnvelope

# Create event
event = EventEnvelope(
    type="note.created",
    source="NoteService",
    user_id=user_id,
    payload={"note_id": str(note_id), "title": "Test"}
)

# Serialize
event_dict = event.to_dict()

# Deserialize
restored = EventEnvelope.from_dict(event_dict)
assert restored.event_id == event.event_id
```
```

**Checklist:**
- [ ] Naming convention documented với examples
- [ ] Event type registry (10 core events Phase 1)
- [ ] Versioning strategy documented
- [ ] Event flow diagram
- [ ] Testing examples

---

### Task 1.1.3: Define Core Event Payload Schemas

**Output:** `backend/app/events/payloads.py`

```python
"""
Event payload schemas.

Each event type has a strongly-typed payload schema for validation.
"""

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional


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
```

**Checklist:**
- [ ] 10 payload schemas cho core events
- [ ] Pydantic validation rules
- [ ] Field descriptions
- [ ] Type hints đầy đủ
- [ ] Optional fields với defaults
- [ ] Documentation comments

---

## ✅ Milestone 1.1 Definition of Done

- [x] EventEnvelope schema với JSON serialization — `backend/app/events/schemas.py`
- [x] Event naming convention documented — `backend/app/events/README.md`
- [x] 10 payload schemas implemented — `backend/app/events/payloads.py`
- [x] README.md với architecture docs
- [x] Versioning strategy documented
- [x] Unit tests cho schemas — `backend/tests/unit/test_event_schemas.py` (27 tests)
- [x] All schemas pass validation tests — `pytest tests/unit/test_event_schemas.py` 27 passed
- [ ] Documentation reviewed by team (pending human review)

**Status: hoàn thành 2026-08-06** (trừ review của team, không tự động hoá được)

---

## 🧪 Testing

**Unit Tests:** `backend/tests/unit/test_event_schemas.py`

```python
import pytest
from uuid import uuid4
from datetime import datetime
from app.events.schemas import EventEnvelope
from app.events.payloads import NoteCreatedPayload, ReminderDuePayload
from pydantic import ValidationError


def test_event_envelope_creation():
    """Test creating event envelope."""
    event = EventEnvelope(
        type="note.created",
        source="NoteService",
        user_id=uuid4(),
        payload={"note_id": str(uuid4()), "title": "Test"}
    )
    
    assert event.event_id is not None
    assert event.type == "note.created"
    assert event.version == "1.0.0"
    assert isinstance(event.timestamp, datetime)


def test_event_serialization():
    """Test event to_dict and from_dict."""
    original = EventEnvelope(
        type="note.created",
        source="NoteService",
        user_id=uuid4(),
        workspace_id=uuid4(),
        payload={"note_id": str(uuid4())}
    )
    
    # Serialize
    event_dict = original.to_dict()
    assert isinstance(event_dict, dict)
    assert event_dict["type"] == "note.created"
    
    # Deserialize
    restored = EventEnvelope.from_dict(event_dict)
    assert restored.event_id == original.event_id
    assert restored.user_id == original.user_id
    assert restored.timestamp.isoformat() == original.timestamp.isoformat()


def test_note_created_payload():
    """Test NoteCreatedPayload validation."""
    payload = NoteCreatedPayload(
        note_id=uuid4(),
        workspace_id=uuid4(),
        title="Test Note",
        parent_note_id=uuid4()
    )
    
    assert payload.title == "Test Note"
    assert payload.content_type == "markdown"  # default


def test_reminder_due_payload():
    """Test ReminderDuePayload validation."""
    payload = ReminderDuePayload(
        reminder_id=uuid4(),
        schedule_id=uuid4(),
        schedule_title="Meeting",
        scheduled_at=datetime.utcnow(),
        reminder_offset_minutes=15
    )
    
    assert payload.schedule_title == "Meeting"
    assert payload.reminder_offset_minutes == 15


def test_payload_validation_error():
    """Test payload validation catches missing required fields."""
    with pytest.raises(ValidationError):
        NoteCreatedPayload(
            # Missing required fields
            title="Test"
        )
```

**Checklist:**
- [ ] Test EventEnvelope creation
- [ ] Test serialization/deserialization
- [ ] Test all 10 payload schemas
- [ ] Test validation errors
- [ ] Test default values
- [ ] Test optional fields

---

**Next Milestone:** [1.2 Event Bus Implementation](02_EVENT_BUS.md)
