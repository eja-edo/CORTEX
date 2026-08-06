# Command Architecture

## Overview

Commands are the **only way** AI agents mutate data in Cortex.

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
- `revert`: Undo operation

### Commands defined in Phase 1 (7 total)

| Command | Args schema | Revertable? | Notes |
|---------|------------|-------------|-------|
| `note.create` | `NoteCreateArgs` | Yes | |
| `note.update` | `NoteUpdateArgs` | **No** | Creates a Proposal (pending approval), not a direct edit — see below |
| `note.delete` | `NoteDeleteArgs` | Yes | Soft delete |
| `schedule.create` | `ScheduleCreateArgs` | Yes | |
| `schedule.update` | `ScheduleUpdateArgs` | Yes | |
| `schedule.delete` | `ScheduleDeleteArgs` | Yes | |
| `action.revert` | `ActionRevertArgs` | N/A | Meta-command, undoes a revertable command |

### ⚠️ `note.update` is not a direct edit

The real `update_note_handler` (`backend/app/ai/tools/update_note.py`) does not
apply changes to the note directly — it builds a diff and calls
`ProposalService.create_proposal()`, which the user must approve before the
note actually changes. `NoteUpdateArgs.content` is therefore the **full
proposed text**, not a patch, and a successful `note.update` command means
"a proposal was created" — there is no prior state to snapshot, so it is
**not revertable** through `CommandRegistry`. To cancel a pending proposal,
use a separate mechanism (proposal reject), not `action.revert`.

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

**Migration path:** Tools become thin wrappers around Commands (see
06_TOOL_MIGRATION.md).

```python
# OLD (Phase 0): tool calls the service directly, manages its own snapshot
async def create_note_handler(args: dict, ctx: ToolContext):
    service = NoteService(ctx.async_db)
    note = await service.create_note(...)
    # Manual snapshot creation, manual audit log
    return {"result": ...}

# NEW (Phase 1): tool builds a Command, CommandRegistry does the rest
async def create_note_handler(args: dict, ctx: ToolContext):
    command = Command(
        command_name="note.create",
        args=args,
        requested_by=ctx.user_id,
        workspace_id=ctx.workspace_id,
    )
    result = await command_registry.execute(command, ctx)
    return result.model_dump()
```

---

## Schema Versioning

Commands use semantic versioning: `MAJOR.MINOR.PATCH`.

- **PATCH** (1.0.0 → 1.0.1): docs only, no schema change.
- **MINOR** (1.0.0 → 1.1.0): add an optional field to args — backward compatible.
- **MAJOR** (1.0.0 → 2.0.0): breaking change (field removed/renamed) — requires
  consumer updates. `CommandRegistry` can support both versions during transition.

`CommandRegistry` checks `command.schema_version` to handle different versions.

---

## Command Registry (Milestone 1.5)

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
    revertable=True,
)
```

### Handler signature

```python
async def note_create_handler(command: Command, ctx: ToolContext) -> dict:
    """Called by CommandRegistry after validation + permission checks."""
    args = NoteCreateArgs(**command.args)
    service = NoteService(ctx._async_db)
    note = await service.create_note(...)
    return {
        "id": str(note.id),
        "title": note.title,
        "prev_state": {},  # empty for create — nothing to restore
    }
```

---

## Permission System

```python
class PermissionScope(str, Enum):
    READ = "read"      # Anyone can read
    WRITE = "write"    # Editor role in workspace (note.*) / owner (schedule.*)
    ADMIN = "admin"    # Admin role in workspace
```

Note domains are workspace-scoped (checked via `WorkspacePermission`); the
`Schedule` model has no `workspace_id` (only `user_id`), so `schedule.*`
commands are checked by ownership instead — see 05_COMMAND_REGISTRY.md.

---

## Revert System

Revertable commands automatically create a snapshot on success:

```python
registry.register(name="note.create", revertable=True, ...)

# Handler includes prev_state for revert:
return {"id": str(note.id), "prev_state": {}}  # note.create: nothing to restore
```

To revert:

```python
command = Command(command_name="action.revert", args={"action_id": "..."}, requested_by=user_id)
result = await registry.execute(command, ctx)
```

`note.update` is registered with `revertable=False` (see above) — it isn't
reverted this way.

---

## Testing Commands

```python
from app.commands.schemas import Command
from app.commands.args import NoteCreateArgs

command = Command(
    command_name="note.create",
    args=NoteCreateArgs(workspace_id=workspace_id, title="Test Note", content="Test content").model_dump(),
    requested_by=user_id,
    workspace_id=workspace_id,
)

result = await registry.execute(command, ctx)
assert result.success is True
assert result.action_id is not None  # revertable
```
