# Milestone 1.5: Command Registry

**Timeline:** 5-6 ngày  
**Dependencies:** 1.4 (Command Schema)  
**Effort:** Large  

---

## 🎯 Mục tiêu

Xây dựng CommandRegistry — lớp trung gian bắt buộc mọi hành động mutating đi qua:
- **Validation** → **Permission check** → **Execution** → **Audit** → **Event publish**

Thay thế ToolRegistry singleton pattern bằng architecture sạch hơn với:
- Permission checking built-in
- Audit logging automatic
- Undo/revert automatic
- Event publishing automatic
- Schema versioning support

---

## 📋 Tasks

### Task 1.5.1: CommandRegistry Core Implementation

**Output:** `backend/app/commands/registry.py`

```python
"""
CommandRegistry: Central command execution with built-in validation, permission, audit.

Architecture:
  Command → CommandRegistry → Handler → Result
            ├─ Validate args
            ├─ Check permission
            ├─ Create snapshot (if revertable)
            ├─ Execute handler
            ├─ Log audit trail
            └─ Publish event
"""

from typing import Callable, Optional
from uuid import UUID
import time
from datetime import datetime

from pydantic import BaseModel, ValidationError

from app.commands.schemas import (
    Command,
    CommandResult,
    CommandStatus,
    PermissionScope
)
from app.ai.agents.tool_context import ToolContext
from app.ai.agents.action_snapshot_store import ActionSnapshotStore, ActionSnapshot
from app.events.event_bus import get_event_bus
from app.events.schemas import EventEnvelope
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CommandHandler(BaseModel):
    """
    Command handler definition.
    
    Similar to ToolDefinition but with stricter contracts.
    """
    name: str
    description: str
    args_schema: type[BaseModel]  # Pydantic model for validation
    handler: Callable  # async (command: Command, ctx: ToolContext) -> dict
    permission_scope: PermissionScope
    revertable: bool = False
    revert_handler: Optional[Callable] = None
    
    class Config:
        arbitrary_types_allowed = True


class CommandRegistry:
    """
    Central registry for command execution.
    
    Unlike ToolRegistry (global singleton), CommandRegistry:
    - Enforces permission checks
    - Auto-creates audit logs
    - Auto-handles undo snapshots
    - Validates against versioned schemas
    - Publishes events automatically
    """
    
    def __init__(
        self,
        snapshot_store: Optional[ActionSnapshotStore] = None
    ):
        self._handlers: dict[str, CommandHandler] = {}
        self._snapshot_store = snapshot_store
        self._event_bus = None  # Lazy init
    
    async def _get_event_bus(self):
        """Lazy load EventBus."""
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus
    
    def _get_snapshot_store(self) -> ActionSnapshotStore:
        """Get or create snapshot store."""
        if self._snapshot_store is None:
            from app.ai.agents.action_snapshot_store import get_snapshot_store
            self._snapshot_store = get_snapshot_store()
        return self._snapshot_store
    
    def register(
        self,
        name: str,
        description: str,
        args_schema: type[BaseModel],
        handler: Callable,
        permission_scope: PermissionScope = PermissionScope.WRITE,
        revertable: bool = False,
        revert_handler: Optional[Callable] = None
    ):
        """
        Register a command handler.
        
        Args:
            name: Command name (domain.action)
            description: Human-readable description
            args_schema: Pydantic model for argument validation
            handler: async (command: Command, ctx: ToolContext) -> dict
            permission_scope: Required permission level
            revertable: Whether command can be undone
            revert_handler: Custom revert logic (optional, default uses snapshot)
        """
        if name in self._handlers:
            raise ValueError(f"Command already registered: {name}")
        
        handler_def = CommandHandler(
            name=name,
            description=description,
            args_schema=args_schema,
            handler=handler,
            permission_scope=permission_scope,
            revertable=revertable,
            revert_handler=revert_handler
        )
        
        self._handlers[name] = handler_def
        logger.info(
            f"Command registered: {name}",
            extra={
                "command": name,
                "permission": permission_scope.value,
                "revertable": revertable
            }
        )
    
    async def execute(
        self,
        command: Command,
        ctx: ToolContext
    ) -> CommandResult:
        """
        Execute a command with full validation, permission, audit pipeline.
        
        Flow:
          1. Validate command exists
          2. Validate arguments against schema
          3. Check user permissions
          4. Create snapshot (if revertable)
          5. Execute handler
          6. Log audit trail
          7. Publish event
          8. Return result
        """
        start_time = time.time()
        command.status = CommandStatus.EXECUTING
        
        try:
            # 1. Lookup handler
            handler_def = self._handlers.get(command.command_name)
            if not handler_def:
                raise ValueError(f"Unknown command: {command.command_name}")
            
            # 2. Validate arguments
            try:
                validated_args = handler_def.args_schema(**command.args)
            except ValidationError as exc:
                raise ValueError(f"Invalid arguments: {exc}")
            
            # 3. Check permissions
            await self._check_permission(command, handler_def, ctx)
            
            # 4. Execute handler
            command_with_validated_args = command.model_copy(update={
                "args": validated_args.model_dump()
            })
            
            result_data = await handler_def.handler(command_with_validated_args, ctx)
            
            # 5. Create snapshot (if revertable) - after successful execution
            snapshot_id = None
            if handler_def.revertable:
                snapshot_id = await self._create_snapshot(
                    command,
                    result_data,
                    ctx
                )
            
            # 6. Mark success
            duration_ms = int((time.time() - start_time) * 1000)
            command.status = CommandStatus.COMPLETED
            command.executed_at = datetime.utcnow()
            command.duration_ms = duration_ms
            command.snapshot_id = snapshot_id
            
            # 7. Audit log
            await self._log_audit(command, result_data, ctx)
            
            # 8. Publish event
            await self._publish_event(command, result_data, ctx)
            
            # 9. Return result
            return CommandResult(
                command_id=command.command_id,
                success=True,
                data=result_data,
                action_id=snapshot_id,
                duration_ms=duration_ms,
                executed_at=command.executed_at,
                revert_hint=self._generate_revert_hint(command, snapshot_id) if snapshot_id else None
            )
        
        except Exception as exc:
            # Error handling
            duration_ms = int((time.time() - start_time) * 1000)
            command.status = CommandStatus.FAILED
            command.error = str(exc)
            command.executed_at = datetime.utcnow()
            command.duration_ms = duration_ms
            
            # Log error
            logger.error(
                f"Command execution failed: {command.command_name}",
                exc_info=True,
                extra={
                    "command_id": command.command_id,
                    "command_name": command.command_name,
                    "user_id": str(command.requested_by),
                    "error": str(exc)
                }
            )
            
            # Audit log
            await self._log_audit(command, None, ctx)
            
            return CommandResult(
                command_id=command.command_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
                executed_at=command.executed_at
            )
    
    async def _check_permission(
        self,
        command: Command,
        handler_def: CommandHandler,
        ctx: ToolContext
    ):
        """
        Check if user has permission to execute command.
        
        Permission rules:
        - READ: Anyone can read
        - WRITE: Must be editor in workspace
        - ADMIN: Must be admin in workspace
        """
        from app.database import SessionLocal
        from app.services.workspace_permission import WorkspacePermission
        
        if handler_def.permission_scope == PermissionScope.READ:
            return  # Always allowed
        
        if command.workspace_id is None:
            return  # No workspace context - allow
        
        # Sync DB check (WorkspacePermission uses sync session)
        with SessionLocal() as sync_db:
            try:
                member = WorkspacePermission.require_member(
                    command.workspace_id,
                    command.requested_by,
                    sync_db
                )
                
                if handler_def.permission_scope == PermissionScope.WRITE:
                    WorkspacePermission.require_editor(member)
                elif handler_def.permission_scope == PermissionScope.ADMIN:
                    WorkspacePermission.require_admin(member)
            
            except ValueError as exc:
                raise PermissionError(f"Permission denied: {exc}")
        
        logger.debug(
            f"Permission granted: {command.command_name}",
            extra={"user_id": str(command.requested_by)}
        )
    
    async def _create_snapshot(
        self,
        command: Command,
        result_data: dict,
        ctx: ToolContext
    ) -> str:
        """
        Create snapshot for revertable command.
        
        Snapshot contains:
        - Command name
        - Arguments
        - Result data (for context)
        - Previous state (from result_data["prev_state"] if provided)
        
        Returns snapshot_id for later revert.
        """
        snapshot = ActionSnapshot(
            tool_name=command.command_name,  # Store as tool_name for compatibility
            user_id=str(command.requested_by),
            conversation_id=str(command.conversation_id) if command.conversation_id else None,
            snapshot=result_data.get("prev_state", {}),  # Handler provides prev_state
            action_id=command.command_id
        )
        
        # Save to store
        store = self._get_snapshot_store()
        
        # Save to Redis + PG
        if hasattr(ctx, '_async_db') and ctx._async_db:
            action_id = await store.save(snapshot, db_session=ctx._async_db)
        else:
            # Sync context
            with ctx.get_sync_db() as sync_db:
                action_id = store.save_sync(snapshot, db_session=sync_db)
        
        logger.info(
            f"Snapshot created: {action_id}",
            extra={
                "command": command.command_name,
                "action_id": action_id
            }
        )
        
        return action_id
    
    async def _log_audit(
        self,
        command: Command,
        result: Optional[dict],
        ctx: ToolContext
    ):
        """
        Log command execution to audit trail.
        
        Logged to structured logger (JSONL).
        Also stored in PostgreSQL via snapshot store.
        """
        logger.info(
            f"Command executed: {command.command_name}",
            extra={
                "command_id": command.command_id,
                "command_name": command.command_name,
                "user_id": str(command.requested_by),
                "workspace_id": str(command.workspace_id) if command.workspace_id else None,
                "conversation_id": str(command.conversation_id) if command.conversation_id else None,
                "status": command.status.value,
                "duration_ms": command.duration_ms,
                "success": command.status == CommandStatus.COMPLETED,
                "error": command.error,
                "source": command.source,
                "action_id": command.snapshot_id
            }
        )
    
    async def _publish_event(
        self,
        command: Command,
        result: Optional[dict],
        ctx: ToolContext
    ):
        """
        Publish event for completed command.
        
        Event type: command.{domain}.{action}
        Example: command.note.create
        """
        if command.status != CommandStatus.COMPLETED:
            return  # Only publish events for successful commands
        
        try:
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type=f"command.{command.command_name}",
                source="CommandRegistry",
                user_id=command.requested_by,
                workspace_id=command.workspace_id,
                conversation_id=command.conversation_id,
                correlation_id=command.correlation_id,
                payload={
                    "command_id": command.command_id,
                    "command_name": command.command_name,
                    "action_id": command.snapshot_id,
                    "duration_ms": command.duration_ms,
                    **(result or {})
                }
            ))
        except Exception as exc:
            logger.warning(
                f"Failed to publish command event: {exc}",
                extra={"command_id": command.command_id}
            )
            # Don't fail command execution if event publish fails
    
    def _generate_revert_hint(self, command: Command, snapshot_id: str) -> str:
        """Generate human-readable revert hint."""
        return f"To undo this action, use: revert_action(action_id='{snapshot_id}')"
    
    async def revert_command(
        self,
        action_id: str,
        ctx: ToolContext
    ) -> CommandResult:
        """
        Revert a previously executed command.
        
        Flow:
          1. Fetch snapshot from store
          2. Validate ownership
          3. Execute revert handler (or use default)
          4. Mark snapshot as reverted
          5. Audit log
        """
        start_time = time.time()
        
        try:
            # Fetch snapshot
            store = self._get_snapshot_store()
            snapshot = await store.get(
                user_id=str(ctx.user_id),
                action_id=action_id
            )
            
            if not snapshot:
                raise ValueError(f"Snapshot not found: {action_id}")
            
            if snapshot.reverted_at:
                raise ValueError(f"Action already reverted: {action_id}")
            
            # Get handler
            handler_def = self._handlers.get(snapshot.tool_name)
            if not handler_def:
                raise ValueError(f"Unknown command: {snapshot.tool_name}")
            
            if not handler_def.revertable:
                raise ValueError(f"Command is not revertable: {snapshot.tool_name}")
            
            # Execute revert
            if handler_def.revert_handler:
                # Custom revert logic
                await handler_def.revert_handler(snapshot, ctx)
            else:
                # Default: use snapshot to restore prev state
                await self._default_revert(snapshot, ctx)
            
            # Mark as reverted
            await store.mark_reverted(
                user_id=str(ctx.user_id),
                action_id=action_id
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Audit log
            logger.info(
                f"Command reverted: {snapshot.tool_name}",
                extra={
                    "action_id": action_id,
                    "user_id": str(ctx.user_id),
                    "duration_ms": duration_ms
                }
            )
            
            return CommandResult(
                command_id=action_id,
                success=True,
                data={"reverted": True, "original_command": snapshot.tool_name},
                duration_ms=duration_ms,
                executed_at=datetime.utcnow()
            )
        
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Revert failed: {exc}", exc_info=True)
            
            return CommandResult(
                command_id=action_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
                executed_at=datetime.utcnow()
            )
    
    async def _default_revert(self, snapshot: ActionSnapshot, ctx: ToolContext):
        """
        Default revert logic using snapshot data.
        
        Supports:
        - note.create → soft delete note
        - note.update → restore prev fields
        - schedule.create → delete schedule
        - schedule.update → restore prev fields
        """
        from app.services.notes import NoteService
        from app.services.schedule_service import ScheduleService
        from uuid import UUID
        
        command_name = snapshot.tool_name
        prev_state = snapshot.snapshot
        
        if command_name == "note.create":
            # Soft delete created note
            note_id = prev_state.get("note_id")
            if note_id:
                service = NoteService(ctx._async_db)
                await service.delete_note(UUID(note_id), ctx.user_id)
        
        elif command_name == "note.update":
            # Restore previous fields
            # TODO: Implement restore logic
            logger.warning(f"Revert not fully implemented for: {command_name}")
        
        elif command_name == "schedule.create":
            # Delete created schedule
            schedule_id = prev_state.get("schedule_id")
            if schedule_id:
                service = ScheduleService(ctx.get_sync_db())
                service.delete_schedule(UUID(schedule_id))
        
        elif command_name == "schedule.update":
            # Restore previous fields
            logger.warning(f"Revert not fully implemented for: {command_name}")
        
        else:
            raise ValueError(f"No revert logic for command: {command_name}")
    
    def list_commands(self) -> list[dict]:
        """List all registered commands."""
        return [
            {
                "name": h.name,
                "description": h.description,
                "permission_scope": h.permission_scope.value,
                "revertable": h.revertable
            }
            for h in self._handlers.values()
        ]


# Global registry instance
_command_registry: Optional[CommandRegistry] = None


def get_command_registry() -> CommandRegistry:
    """Get global CommandRegistry instance."""
    global _command_registry
    if _command_registry is None:
        _command_registry = CommandRegistry()
    return _command_registry


def reset_command_registry():
    """Reset global registry (for testing)."""
    global _command_registry
    _command_registry = None
```

**Checklist:**
- [ ] CommandRegistry class với register/execute methods
- [ ] Permission checking logic (integration với WorkspacePermission)
- [ ] Snapshot creation (integration với ActionSnapshotStore)
- [ ] Audit logging (structured JSON)
- [ ] Event publishing (integration với EventBus)
- [ ] Revert command implementation
- [ ] Default revert logic cho 4 commands
- [ ] Error handling với proper exceptions
- [ ] Global registry singleton
- [ ] Documentation

---

### Task 1.5.2: Integration Tests

**Output:** `backend/tests/integration/test_command_registry.py`

```python
import pytest
from uuid import uuid4
from app.commands.registry import CommandRegistry, get_command_registry, reset_command_registry
from app.commands.schemas import Command, PermissionScope, CommandStatus
from app.commands.args import NoteCreateArgs
from app.ai.agents.tool_context import ToolContext


@pytest.fixture
def registry():
    """Fresh CommandRegistry for each test."""
    reset_command_registry()
    return get_command_registry()


@pytest.fixture
async def test_context(async_db, test_user, test_workspace):
    """ToolContext for testing."""
    return ToolContext(
        user_id=test_user.id,
        async_db=async_db,
        workspace_id=test_workspace.id
    )


async def dummy_note_create_handler(command: Command, ctx: ToolContext) -> dict:
    """Dummy handler for testing."""
    return {
        "note_id": str(uuid4()),
        "title": command.args["title"],
        "prev_state": {}  # For snapshot
    }


@pytest.mark.asyncio
async def test_register_command(registry):
    """Test command registration."""
    registry.register(
        name="note.create",
        description="Create a note",
        args_schema=NoteCreateArgs,
        handler=dummy_note_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True
    )
    
    commands = registry.list_commands()
    assert len(commands) == 1
    assert commands[0]["name"] == "note.create"
    assert commands[0]["revertable"] is True


@pytest.mark.asyncio
async def test_execute_command_success(registry, test_context):
    """Test successful command execution."""
    # Register handler
    registry.register(
        name="note.create",
        description="Create a note",
        args_schema=NoteCreateArgs,
        handler=dummy_note_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True
    )
    
    # Create command
    command = Command(
        command_name="note.create",
        args={
            "workspace_id": str(test_context.workspace_id),
            "title": "Test Note",
            "content": "Test content"
        },
        requested_by=test_context.user_id,
        workspace_id=test_context.workspace_id
    )
    
    # Execute
    result = await registry.execute(command, test_context)
    
    # Verify
    assert result.success is True
    assert result.data["title"] == "Test Note"
    assert result.action_id is not None  # Snapshot created
    assert result.duration_ms > 0
    assert result.revert_hint is not None


@pytest.mark.asyncio
async def test_execute_command_validation_error(registry, test_context):
    """Test command execution with invalid arguments."""
    registry.register(
        name="note.create",
        description="Create a note",
        args_schema=NoteCreateArgs,
        handler=dummy_note_create_handler
    )
    
    # Invalid args: missing required field
    command = Command(
        command_name="note.create",
        args={
            "workspace_id": str(test_context.workspace_id)
            # Missing title
        },
        requested_by=test_context.user_id
    )
    
    result = await registry.execute(command, test_context)
    
    assert result.success is False
    assert "Invalid arguments" in result.error


@pytest.mark.asyncio
async def test_execute_unknown_command(registry, test_context):
    """Test executing unknown command."""
    command = Command(
        command_name="unknown.command",
        args={},
        requested_by=test_context.user_id
    )
    
    result = await registry.execute(command, test_context)
    
    assert result.success is False
    assert "Unknown command" in result.error


@pytest.mark.asyncio
async def test_command_creates_snapshot(registry, test_context):
    """Test that revertable command creates snapshot."""
    registry.register(
        name="note.create",
        description="Create a note",
        args_schema=NoteCreateArgs,
        handler=dummy_note_create_handler,
        revertable=True
    )
    
    command = Command(
        command_name="note.create",
        args={
            "workspace_id": str(test_context.workspace_id),
            "title": "Test",
            "content": ""
        },
        requested_by=test_context.user_id
    )
    
    result = await registry.execute(command, test_context)
    
    assert result.success is True
    assert result.action_id is not None
    
    # Verify snapshot exists
    from app.ai.agents.action_snapshot_store import get_snapshot_store
    store = get_snapshot_store()
    snapshot = await store.get(str(test_context.user_id), result.action_id)
    assert snapshot is not None
    assert snapshot.tool_name == "note.create"


@pytest.mark.asyncio
async def test_audit_logging(registry, test_context, caplog):
    """Test audit logging."""
    registry.register(
        name="note.create",
        description="Create a note",
        args_schema=NoteCreateArgs,
        handler=dummy_note_create_handler
    )
    
    command = Command(
        command_name="note.create",
        args={
            "workspace_id": str(test_context.workspace_id),
            "title": "Test",
            "content": ""
        },
        requested_by=test_context.user_id
    )
    
    await registry.execute(command, test_context)
    
    # Verify audit log
    assert "Command executed: note.create" in caplog.text


@pytest.mark.asyncio
async def test_list_commands(registry):
    """Test listing registered commands."""
    registry.register(
        name="note.create",
        description="Create note",
        args_schema=NoteCreateArgs,
        handler=dummy_note_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True
    )
    
    registry.register(
        name="note.update",
        description="Update note",
        args_schema=NoteCreateArgs,  # Using same schema for test
        handler=dummy_note_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True
    )
    
    commands = registry.list_commands()
    
    assert len(commands) == 2
    command_names = [c["name"] for c in commands]
    assert "note.create" in command_names
    assert "note.update" in command_names
```

**Checklist:**
- [ ] Test command registration
- [ ] Test successful execution
- [ ] Test validation errors
- [ ] Test unknown command
- [ ] Test snapshot creation
- [ ] Test audit logging
- [ ] Test list_commands
- [ ] All tests pass

---

## ✅ Milestone 1.5 Definition of Done

- [ ] CommandRegistry implementation complete
- [ ] Permission checking integrated (basic)
- [ ] Snapshot creation/revert integrated
- [ ] Audit logging automatic
- [ ] Event publishing automatic
- [ ] Revert command implementation
- [ ] Default revert logic for 4 commands
- [ ] Global registry singleton
- [ ] Integration tests pass
- [ ] Documentation complete
- [ ] Performance: command execution < 50ms overhead vs direct service call

---

**Next Milestone:** [1.6 Tool→Command Migration](06_TOOL_MIGRATION.md)
