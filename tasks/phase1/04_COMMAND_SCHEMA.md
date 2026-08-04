# Milestone 1.4: Command Schema Design

**Timeline:** 2 ngày  
**Dependencies:** None (có thể song song với 1.1-1.3)  
**Effort:** Small  

---

## 🎯 Mục tiêu

Định nghĩa "Command" như một internal representation tách biệt hoàn toàn khỏi natural language, để AI không thao tác trực tiếp vào DB (theo Product Requirement mục 8).

**Nguyên tắc:**
- Command = validated, structured operation
- AI generates intent → Intent resolver maps to Command → Command executes
- Command có schema validation, permission checking, audit trail built-in
- Commands are versioned và revertable

---

## 📋 Tasks

### Task 1.4.1: Design Command Envelope Schema

**Output:** `backend/app/commands/schemas.py`

```python
"""
Command schemas for Cortex.

Commands represent validated, permission-checked operations.
AI never touches DB directly - only through CommandRegistry.
"""

from pydantic import BaseModel, Field
from typing import Any, Optional
from uuid import UUID, uuid4
from enum import Enum
from datetime import datetime


class PermissionScope(str, Enum):
    """Permission level required to execute command."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class CommandStatus(str, Enum):
    """Command execution status."""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERTED = "reverted"


class Command(BaseModel):
    """
    Command envelope.
    
    Format: {domain}.{action}
    Examples:
      - note.create
      - schedule.update
      - task.complete
    
    Flow:
      Tool handler → Command → CommandRegistry → Permission check → Execute → Audit
    """
    command_id: str = Field(default_factory=lambda: str(uuid4()))
    command_name: str = Field(..., description="Command name: domain.action")
    args: dict[str, Any] = Field(default_factory=dict, description="Validated arguments")
    
    # Context
    requested_by: UUID = Field(..., description="User ID (NEVER from LLM)")
    workspace_id: Optional[UUID] = Field(None, description="Workspace context")
    conversation_id: Optional[UUID] = Field(None, description="Conversation context")
    
    # Permission & Audit
    permission_scope: PermissionScope = Field(default=PermissionScope.WRITE)
    source: str = Field(default="AI", description="Command source: AI, API, Workflow, System")
    correlation_id: Optional[str] = Field(None, description="Request trace ID")
    
    # Versioning
    schema_version: str = Field(default="1.0.0", description="Command schema version")
    
    # Execution tracking (populated by registry)
    status: CommandStatus = Field(default=CommandStatus.PENDING)
    executed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    
    # Undo support
    revertable: bool = Field(default=False)
    snapshot_id: Optional[str] = Field(None, description="ActionSnapshot ID for revert")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }


class CommandResult(BaseModel):
    """
    Result of command execution.
    
    Returned by CommandRegistry.execute().
    """
    command_id: str
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    
    # Audit trail
    action_id: Optional[str] = Field(None, description="Snapshot ID for revertable commands")
    duration_ms: int
    executed_at: datetime
    
    # Revert hint
    revert_hint: Optional[str] = Field(None, description="Human-readable revert instruction")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

**Checklist:**
- [ ] Command envelope với validation
- [ ] Permission scope enum
- [ ] Status tracking fields
- [ ] Revert support fields
- [ ] CommandResult schema
- [ ] Schema versioning
- [ ] Documentation với ví dụ
- [ ] Unit test cho serialization

---

### Task 1.4.2: Define Command Argument Schemas

**Output:** `backend/app/commands/args.py`

```python
"""
Command argument schemas.

Each command has a strongly-typed Pydantic model for validation.
This prevents AI from passing invalid arguments.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional
from uuid import UUID
from datetime import datetime


# ============================================================================
# Note Commands
# ============================================================================

class NoteCreateArgs(BaseModel):
    """Arguments for note.create command."""
    workspace_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(default="")
    parent_note_id: Optional[UUID] = None
    content_type: str = Field(default="markdown")
    
    @validator("title")
    def title_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()


class NoteUpdateArgs(BaseModel):
    """Arguments for note.update command."""
    note_id: UUID
    version: int = Field(..., ge=1, description="Optimistic lock version")
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = None
    parent_note_id: Optional[UUID] = None
    
    @validator("title")
    def title_not_empty(cls, v):
        if v is not None and (not v or not v.strip()):
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
    schedule_type: str = Field(..., regex="^(CLASS|EXAM|DEADLINE|PERSONAL)$")
    start_time: datetime
    end_time: datetime
    location: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    recurrence: Optional[dict] = None
    reminders: Optional[list[dict]] = None
    
    @validator("end_time")
    def end_after_start(cls, v, values):
        if "start_time" in values and v <= values["start_time"]:
            raise ValueError("end_time must be after start_time")
        return v


class ScheduleUpdateArgs(BaseModel):
    """Arguments for schedule.update command."""
    schedule_id: UUID
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_completed: Optional[bool] = None


class ScheduleDeleteArgs(BaseModel):
    """Arguments for schedule.delete command."""
    schedule_id: UUID


# ============================================================================
# Action Commands (Revert)
# ============================================================================

class ActionRevertArgs(BaseModel):
    """Arguments for action.revert command."""
    action_id: str = Field(..., description="Snapshot ID to revert")
```

**Checklist:**
- [ ] 7 command arg schemas (note: create/update/delete, schedule: create/update/delete, action: revert)
- [ ] Pydantic validation rules (min_length, max_length, regex, custom validators)
- [ ] Field descriptions
- [ ] Type hints đầy đủ
- [ ] Unit tests cho validation (valid + invalid inputs)

---

### Task 1.4.3: Command Naming Convention & Documentation

**Output:** `backend/app/commands/README.md`

```markdown
# Command Architecture

## Overview

Commands are the **only way** AI agents can mutate data in Cortex.

```
User message (NL)
    ↓
LLM Intent Detection
    ↓
Intent Resolver
    ↓
Command (structured, validated)
    ↓
CommandRegistry
    ├─ Permission check
    ├─ Validation
    ├─ Execute
    ├─ Create snapshot (if revertable)
    └─ Audit log
    ↓
Result + action_id
```

---

## Naming Convention

**Format:** `{domain}.{action}`

### Domains:
- `note`: Note operations
- `schedule`: Schedule operations
- `task`: Task operations (Phase 2)
- `goal`: Goal operations (Phase 2)
- `action`: Meta-operations (revert, etc.)

### Actions:
- `create`, `update`, `delete`: CRUD operations
- `complete`, `cancel`: State transitions
- `revert`: Undo operation

### Examples:
- `note.create`: Create a new note
- `note.update`: Update existing note
- `note.delete`: Delete note (soft delete)
- `schedule.create`: Create schedule
- `schedule.update`: Update schedule
- `action.revert`: Revert a previous action

---

## Command vs Tool

| Aspect | Tool | Command |
|--------|------|---------|
| Purpose | AI-facing interface | Internal operation |
| Validation | Basic (Pydantic input_model) | Strict (args schema + permission) |
| Permission | None (tool decides) | Built-in (CommandRegistry enforces) |
| Audit | Optional (tool logs) | Mandatory (CommandRegistry logs) |
| Undo | Manual (tool creates snapshot) | Automatic (CommandRegistry handles) |
| Versioning | None | Schema version field |

**Migration path:** Tools become thin wrappers around Commands.

```python
# OLD (Phase 0):
async def create_note_handler(args: dict, ctx: ToolContext):
    service = NoteService(ctx.async_db)
    note = await service.create_note(...)
    # Manual snapshot creation
    # Manual audit log
    return {"result": ...}

# NEW (Phase 1):
async def create_note_handler(args: dict, ctx: ToolContext):
    command = Command(
        command_name="note.create",
        args=args,
        requested_by=ctx.user_id,
        workspace_id=ctx.workspace_id
    )
    result = await command_registry.execute(command, ctx)
    # Permission, validation, snapshot, audit all handled
    return result.to_tool_format()
```

---

## Schema Versioning

Commands use semantic versioning: `MAJOR.MINOR.PATCH`

### Version Changes

**PATCH (1.0.0 → 1.0.1):**
- Documentation fixes
- No schema changes

**MINOR (1.0.0 → 1.1.0):**
- Add optional fields to args
- Backward compatible
- Old consumers continue working

**MAJOR (1.0.0 → 2.0.0):**
- Breaking changes (field removed/renamed)
- Requires consumer updates
- CommandRegistry can support both versions during transition

### Example Evolution

```python
# v1.0.0: Initial schema
class NoteCreateArgs(BaseModel):
    workspace_id: UUID
    title: str
    content: str

# v1.1.0: Add optional field (backward compatible)
class NoteCreateArgs(BaseModel):
    workspace_id: UUID
    title: str
    content: str
    tags: Optional[list[str]] = None  # NEW, optional

# v2.0.0: Breaking change (field renamed)
class NoteCreateArgs(BaseModel):
    workspace_id: UUID
    heading: str  # RENAMED from 'title'
    content: str
    tags: Optional[list[str]] = None
```

CommandRegistry checks `command.schema_version` to handle different versions.

---

## Command Registry

All commands are registered with CommandRegistry:

```python
from app.commands.registry import get_command_registry
from app.commands.schemas import PermissionScope
from app.commands.args import NoteCreateArgs

registry = get_command_registry()

registry.register(
    name="note.create",
    description="Create a new note in workspace",
    args_schema=NoteCreateArgs,
    handler=note_create_handler,
    permission_scope=PermissionScope.WRITE,
    revertable=True
)
```

### Handler Signature

```python
async def note_create_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Command handler.
    
    Args:
        command: Validated command envelope
        ctx: Tool context (user_id, workspace_id, db access)
    
    Returns:
        dict with result data
    """
    args = NoteCreateArgs(**command.args)  # Already validated by registry
    
    # Execute business logic
    service = NoteService(ctx._async_db)
    note = await service.create_note(...)
    
    return {
        "id": str(note.id),
        "title": note.title,
        "created_at": note.created_at.isoformat()
    }
```

---

## Permission System

Commands declare required permission scope:

```python
class PermissionScope(str, Enum):
    READ = "read"      # Anyone can read
    WRITE = "write"    # Editor role in workspace
    ADMIN = "admin"    # Admin role in workspace
```

CommandRegistry checks permissions before execution:

```python
# User must be editor in workspace to create note
registry.register(
    name="note.create",
    permission_scope=PermissionScope.WRITE,
    ...
)
```

---

## Revert System

Revertable commands automatically create snapshots:

```python
# Mark command as revertable
registry.register(
    name="note.create",
    revertable=True,  # CommandRegistry creates snapshot
    ...
)

# In handler, include previous state for revert
return {
    "id": str(note.id),
    "prev_state": {}  # For note.create, prev_state is empty
}
```

To revert:

```python
command = Command(
    command_name="action.revert",
    args={"action_id": "..."},
    requested_by=user_id
)

result = await registry.execute(command, ctx)
# Note is deleted (create reverted)
```

---

## Testing Commands

```python
from app.commands.schemas import Command
from app.commands.args import NoteCreateArgs

# Create command
command = Command(
    command_name="note.create",
    args=NoteCreateArgs(
        workspace_id=workspace_id,
        title="Test Note",
        content="Test content"
    ).model_dump(),
    requested_by=user_id,
    workspace_id=workspace_id
)

# Execute
result = await registry.execute(command, ctx)

assert result.success is True
assert result.action_id is not None  # Revertable
```
```

**Checklist:**
- [ ] Architecture overview
- [ ] Naming convention
- [ ] Command vs Tool comparison
- [ ] Schema versioning strategy
- [ ] Permission system docs
- [ ] Revert system docs
- [ ] Testing examples

---

## ✅ Milestone 1.4 Definition of Done

- [ ] Command envelope schema với validation
- [ ] CommandResult schema
- [ ] 7 command argument schemas với Pydantic validation
- [ ] Naming convention documented
- [ ] Command architecture documented
- [ ] Permission scope enum
- [ ] Schema versioning strategy
- [ ] Unit tests cho schemas (serialization, validation)
- [ ] README.md explaining Command architecture

---

## 🧪 Testing

**Unit Tests:** `backend/tests/unit/test_command_schemas.py`

```python
import pytest
from uuid import uuid4
from app.commands.schemas import Command, PermissionScope, CommandStatus
from app.commands.args import NoteCreateArgs, ScheduleCreateArgs
from pydantic import ValidationError
from datetime import datetime, timedelta


def test_command_envelope_creation():
    """Test creating command envelope."""
    cmd = Command(
        command_name="note.create",
        args={"workspace_id": str(uuid4()), "title": "Test", "content": ""},
        requested_by=uuid4()
    )
    
    assert cmd.command_id is not None
    assert cmd.status == CommandStatus.PENDING
    assert cmd.permission_scope == PermissionScope.WRITE
    assert cmd.schema_version == "1.0.0"


def test_note_create_args_validation():
    """Test NoteCreateArgs validation."""
    workspace_id = uuid4()
    
    # Valid
    args = NoteCreateArgs(
        workspace_id=workspace_id,
        title="Test Note",
        content="Content"
    )
    assert args.title == "Test Note"
    assert args.content_type == "markdown"  # default
    
    # Invalid: empty title
    with pytest.raises(ValidationError):
        NoteCreateArgs(
            workspace_id=workspace_id,
            title="",
            content=""
        )
    
    # Invalid: title too long
    with pytest.raises(ValidationError):
        NoteCreateArgs(
            workspace_id=workspace_id,
            title="x" * 300,
            content=""
        )
    
    # Invalid: missing required field
    with pytest.raises(ValidationError):
        NoteCreateArgs(
            title="Test"
            # Missing workspace_id
        )


def test_schedule_create_args_validation():
    """Test ScheduleCreateArgs validation."""
    now = datetime.utcnow()
    
    # Valid
    args = ScheduleCreateArgs(
        title="Meeting",
        schedule_type="PERSONAL",
        start_time=now,
        end_time=now + timedelta(hours=1)
    )
    assert args.title == "Meeting"
    
    # Invalid: end_time before start_time
    with pytest.raises(ValidationError):
        ScheduleCreateArgs(
            title="Meeting",
            schedule_type="PERSONAL",
            start_time=now,
            end_time=now - timedelta(hours=1)
        )
    
    # Invalid: wrong schedule_type
    with pytest.raises(ValidationError):
        ScheduleCreateArgs(
            title="Meeting",
            schedule_type="INVALID_TYPE",
            start_time=now,
            end_time=now + timedelta(hours=1)
        )


def test_command_result():
    """Test CommandResult schema."""
    result = CommandResult(
        command_id=str(uuid4()),
        success=True,
        data={"note_id": str(uuid4())},
        action_id=str(uuid4()),
        duration_ms=150,
        executed_at=datetime.utcnow(),
        revert_hint="To undo: revert_action(...)"
    )
    
    assert result.success is True
    assert result.action_id is not None
    assert result.duration_ms == 150


def test_permission_scope_enum():
    """Test PermissionScope enum."""
    assert PermissionScope.READ.value == "read"
    assert PermissionScope.WRITE.value == "write"
    assert PermissionScope.ADMIN.value == "admin"


def test_command_status_enum():
    """Test CommandStatus enum."""
    assert CommandStatus.PENDING.value == "pending"
    assert CommandStatus.EXECUTING.value == "executing"
    assert CommandStatus.COMPLETED.value == "completed"
    assert CommandStatus.FAILED.value == "failed"
    assert CommandStatus.REVERTED.value == "reverted"
```

**Checklist:**
- [ ] Test Command envelope creation
- [ ] Test all 7 command arg schemas
- [ ] Test validation rules (min_length, max_length, custom validators)
- [ ] Test invalid inputs raise ValidationError
- [ ] Test CommandResult schema
- [ ] Test enums
- [ ] All tests pass

---

**Next Milestone:** [1.5 Command Registry](05_COMMAND_REGISTRY.md)
