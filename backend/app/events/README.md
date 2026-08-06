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
- `workflow`: Workflow operations (owned by `workflow_service`, see below)
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
| `note.created` | note | Note was created | `NoteCreatedPayload` |
| `note.updated` | note | Note was updated | `NoteUpdatedPayload` |
| `note.deleted` | note | Note was soft-deleted | `NoteDeletedPayload` |
| `schedule.created` | schedule | Schedule was created | `ScheduleCreatedPayload` |
| `schedule.updated` | schedule | Schedule was updated | `ScheduleUpdatedPayload` |
| `schedule.completed` | schedule | Schedule marked as complete | `ScheduleCompletedPayload` |
| `schedule.reminder.due` | schedule | Reminder is due | `ReminderDuePayload` |
| `conversation.message.created` | conversation | Message added to conversation | `ConversationMessageCreatedPayload` |
| `tool.executed` | tool | Tool finished execution | `ToolExecutedPayload` |
| `google_calendar.synced` | google_calendar | Calendar sync completed | `GoogleCalendarSyncedPayload` |

All 10 payload classes live in `app/events/payloads.py`; `EVENT_PAYLOAD_REGISTRY`
maps event type string → payload class for lookup/validation.

### Command Events (Phase 1.5)

| Event Type | Domain | Description |
|-----------|--------|-------------|
| `command.note.create` | command | note.create command executed |
| `command.note.update` | command | note.update command executed (proposal created — see 06_TOOL_MIGRATION.md) |
| `command.schedule.create` | command | schedule.create command executed |
| `command.action.revert` | command | action.revert command executed |

### ⚠️ Consumers outside `backend/app`

`workflow_service` (dự án Workflow Runtime riêng, `workflow_feature/`) trigger
workflow dựa trên các event `note.*`/`schedule.*`/`asset.*` ở trên. Trước đây nó
lắng nghe qua Redis Pub/Sub (`cortex:workflow:events`, publish bởi
`backend/app/services/redis/workflow_event_publisher.py` — **hiện không còn
được gọi**); kể từ Milestone 1.2, nó chuyển sang đọc trực tiếp từ Redis Stream
`events:{type}` qua consumer-group riêng (xem `tasks/phase1/02_EVENT_BUS.md`,
Task 1.2.4). Bất kỳ thay đổi breaking nào ở payload của các event trên
(`note.created`, `note.updated`, `note.deleted`, `schedule.created`,
`schedule.updated`, `schedule.completed`) đều ảnh hưởng trực tiếp tới
`workflow_service` — bump `MAJOR` version và báo trước khi đổi.

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
EventBus:
    ├─ XADD vào Redis Stream events:{type} (persistence + cross-process fan-out)
    └─ route_event() ngay cho subscriber trong cùng process (fast path)
         ├─ Subscriber 1: Analytics Logger
         ├─ Subscriber 2: Frontend SSE
         └─ Subscriber 3: ...
    ↓ (cross-process, đọc lại từ Stream qua consumer-group riêng)
    workflow_service (Trigger Engine)
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
- Requires consumer updates (bao gồm cả `workflow_service`, xem trên)
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
