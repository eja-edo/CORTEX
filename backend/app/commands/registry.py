"""
CommandRegistry: central command execution with built-in validation,
permission checking, audit logging, undo snapshots, and event publishing.

Architecture:
  Command → CommandRegistry.execute() → Handler → Result
              ├─ Validate args (Pydantic)
              ├─ Check permission (project membership, or ownership for
              │  domains without a container — see _check_permission)
              ├─ Execute handler
              ├─ Create snapshot (if revertable)
              ├─ Log audit trail
              └─ Publish event (command.{name})
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.ai.agents.action_snapshot_store import ActionSnapshot, ActionSnapshotStore
from app.ai.agents.tool_context import ToolContext
from app.commands.schemas import Command, CommandResult, CommandStatus, PermissionScope
from app.events.event_bus import get_event_bus
from app.events.schemas import EventEnvelope
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CommandHandler:
    """
    Registered command definition. Plain dataclass (not a Pydantic model) —
    this is an internal registry entry, never serialized/validated itself;
    the `handler` callable and `args_schema` class are Python objects, not
    JSON-safe data.
    """
    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Callable  # async (command: Command, ctx: ToolContext) -> dict
    permission_scope: PermissionScope
    revertable: bool = False
    revert_handler: Optional[Callable] = None  # async (snapshot: ActionSnapshot, ctx: ToolContext) -> None


class CommandRegistry:
    """
    Central registry for command execution.

    Unlike ToolRegistry (global singleton for AI-facing tool schemas),
    CommandRegistry enforces permission checks, auto-creates audit logs and
    undo snapshots, and publishes events automatically for every mutation.
    """

    def __init__(self, snapshot_store: Optional[ActionSnapshotStore] = None):
        self._handlers: dict[str, CommandHandler] = {}
        self._snapshot_store = snapshot_store
        self._event_bus = None  # Lazy init

    async def _get_event_bus(self):
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus

    def _get_snapshot_store(self) -> ActionSnapshotStore:
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
        revert_handler: Optional[Callable] = None,
    ) -> None:
        """
        Register a command handler.

        Raises:
            ValueError: if `name` is already registered.
        """
        if name in self._handlers:
            raise ValueError(f"Command already registered: {name}")

        self._handlers[name] = CommandHandler(
            name=name,
            description=description,
            args_schema=args_schema,
            handler=handler,
            permission_scope=permission_scope,
            revertable=revertable,
            revert_handler=revert_handler,
        )

        logger.info(
            f"Command registered: {name}",
            extra={"command": name, "permission": permission_scope.value, "revertable": revertable},
        )

    async def execute(self, command: Command, ctx: ToolContext) -> CommandResult:
        """
        Execute a command through the full validation/permission/audit pipeline.

        Never raises — failures are reported via `CommandResult(success=False, error=...)`.
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

            # 3. Check permissions (raises PermissionError on denial)
            await self._check_permission(command, handler_def, ctx)

            # 4. Execute handler with validated (coerced/defaulted) args.
            #    `command` itself keeps the original raw args for the audit trail.
            command_for_handler = command.model_copy(update={"args": validated_args.model_dump(mode="json")})
            result_data = await handler_def.handler(command_for_handler, ctx)

            # 5. Create snapshot (if revertable) — after successful execution
            snapshot_id = None
            if handler_def.revertable:
                snapshot_id = await self._create_snapshot(command, result_data, ctx)

            # 6. Mark success
            duration_ms = int((time.time() - start_time) * 1000)
            command.status = CommandStatus.COMPLETED
            command.executed_at = datetime.now(timezone.utc)
            command.duration_ms = duration_ms
            command.snapshot_id = snapshot_id

            # 7. Audit log
            await self._log_audit(command)

            # 8. Publish event
            await self._publish_event(command, result_data)

            return CommandResult(
                command_id=command.command_id,
                success=True,
                data=result_data,
                action_id=snapshot_id,
                duration_ms=duration_ms,
                executed_at=command.executed_at,
                revert_hint=self._generate_revert_hint(snapshot_id) if snapshot_id else None,
            )

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            command.status = CommandStatus.FAILED
            command.error = str(exc)
            command.executed_at = datetime.now(timezone.utc)
            command.duration_ms = duration_ms

            logger.error(
                f"Command execution failed: {command.command_name}",
                exc_info=True,
                extra={
                    "command_id": command.command_id,
                    "command_name": command.command_name,
                    "user_id": str(command.requested_by),
                    "error": str(exc),
                },
            )

            await self._log_audit(command)

            return CommandResult(
                command_id=command.command_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
                executed_at=command.executed_at,
            )

    async def _check_permission(self, command: Command, handler_def: CommandHandler, ctx: ToolContext) -> None:
        """
        Check if the requesting user may execute this command.

        - READ: always allowed.
        - WRITE/ADMIN + `command.project_id` set: membership check via
          `ProjectPermission`. Không có bậc vai: `ProjectMember` cố ý không
          có `role` (QĐ-1) vì "ai được đọc tài liệu" và "ai chịu trách
          nhiệm việc" là hai câu hỏi khác nhau — xem `project_permission.py`.
        - WRITE/ADMIN + no scope at all (domains without a container,
          e.g. Schedule — the model only has `user_id`): `command.requested_by`
          is a required field on `Command` (always populated from
          `ctx.user_id`, never from LLM/tool args), so there is always an
          authenticated principal here. Resource-level ownership is enforced
          by the handler/service itself (e.g. ScheduleService methods filter
          `WHERE user_id = :user_id`), not at this layer.

        Raises:
            PermissionError: if the check fails.
        """
        from app.database import SessionLocal
        from app.services.project_permission import ProjectPermission

        if handler_def.permission_scope == PermissionScope.READ:
            return

        if command.project_id is not None:
            with SessionLocal() as sync_db:
                if not ProjectPermission.is_member(command.project_id, command.requested_by, sync_db):
                    raise PermissionError(
                        f"Permission denied: user {command.requested_by} is not a member of "
                        f"project {command.project_id}"
                    )
        logger.debug(f"Permission granted: {command.command_name}", extra={"user_id": str(command.requested_by)})

    async def _create_snapshot(self, command: Command, result_data: dict, ctx: ToolContext) -> str:
        """
        Create an undo snapshot for a revertable command.

        The snapshot's `action_id` is the command's own `command_id`, so the
        returned action_id both identifies the command in the audit trail and
        is what `revert_command()` expects.
        """
        snapshot = ActionSnapshot(
            tool_name=command.command_name,
            user_id=str(command.requested_by),
            conversation_id=str(command.conversation_id) if command.conversation_id else None,
            snapshot=result_data.get("prev_state", {}),
            action_id=command.command_id,
        )

        store = self._get_snapshot_store()
        async with ctx.async_db() as db:
            action_id = await store.save(snapshot, db_session=db)

        logger.info(f"Snapshot created: {action_id}", extra={"command": command.command_name, "action_id": action_id})
        return action_id

    async def _log_audit(self, command: Command) -> None:
        """Structured audit log entry for every command execution attempt."""
        logger.info(
            f"Command {command.status.value}: {command.command_name}",
            extra={
                "command_id": command.command_id,
                "command_name": command.command_name,
                "user_id": str(command.requested_by),
                "project_id": str(command.project_id) if command.project_id else None,
                "conversation_id": str(command.conversation_id) if command.conversation_id else None,
                "status": command.status.value,
                "duration_ms": command.duration_ms,
                "success": command.status == CommandStatus.COMPLETED,
                "error": command.error,
                "source": command.source,
                "action_id": command.snapshot_id,
            },
        )

    async def _publish_event(self, command: Command, result: Optional[dict]) -> None:
        """Publish `command.{name}` event for a successfully completed command."""
        if command.status != CommandStatus.COMPLETED:
            return

        try:
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type=f"command.{command.command_name}",
                source="CommandRegistry",
                user_id=command.requested_by,
                conversation_id=command.conversation_id,
                correlation_id=command.correlation_id,
                payload={
                    "command_id": command.command_id,
                    "command_name": command.command_name,
                    "action_id": command.snapshot_id,
                    "duration_ms": command.duration_ms,
                    **(result or {}),
                },
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish command event: {exc}", extra={"command_id": command.command_id})

    def _generate_revert_hint(self, snapshot_id: str) -> str:
        return f"To undo this action, use: revert_action(action_id='{snapshot_id}')"

    async def revert_command(self, action_id: str, ctx: ToolContext) -> CommandResult:
        """
        Revert a previously executed, revertable command.

        Flow: fetch snapshot (scoped to ctx.user_id — a mismatched owner is
        indistinguishable from "not found") → check not already reverted →
        check the originating command is still registered and revertable →
        run the revert (custom `revert_handler` or `_default_revert`) → mark
        the snapshot reverted.
        """
        start_time = time.time()

        try:
            store = self._get_snapshot_store()
            snapshot = await store.get(user_id=str(ctx.user_id), action_id=action_id)

            if not snapshot:
                raise ValueError(f"Snapshot not found: {action_id}")

            if snapshot.reverted_at:
                raise ValueError(f"Action already reverted: {action_id}")

            handler_def = self._handlers.get(snapshot.tool_name)
            if not handler_def:
                raise ValueError(f"Unknown command: {snapshot.tool_name}")

            if not handler_def.revertable:
                raise ValueError(f"Command is not revertable: {snapshot.tool_name}")

            if handler_def.revert_handler:
                await handler_def.revert_handler(snapshot, ctx)
            else:
                await self._default_revert(snapshot, ctx)

            async with ctx.async_db() as db:
                await store.mark_reverted(user_id=str(ctx.user_id), action_id=action_id, db_session=db)

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"Command reverted: {snapshot.tool_name}",
                extra={"action_id": action_id, "user_id": str(ctx.user_id), "duration_ms": duration_ms},
            )

            return CommandResult(
                command_id=action_id,
                success=True,
                data={"reverted": True, "original_command": snapshot.tool_name},
                duration_ms=duration_ms,
                executed_at=datetime.now(timezone.utc),
            )

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Revert failed: {exc}", exc_info=True)

            return CommandResult(
                command_id=action_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
                executed_at=datetime.now(timezone.utc),
            )

    async def _default_revert(self, snapshot: ActionSnapshot, ctx: ToolContext) -> None:
        """
        Default revert logic using the snapshot's `prev_state`, mirroring the
        proven logic in `app/ai/tools/revert_action.py`.

        Supports: note.create (soft-delete), note.delete (un-delete),
        schedule.create (delete), schedule.update (restore previous fields).
        note.update is intentionally excluded — see its docstring in
        app/commands/args.py.
        """
        from sqlalchemy import select

        from app.database import SessionLocal
        from app.models import Note
        from app.services.schedule_service import ScheduleService

        command_name = snapshot.tool_name
        prev_state = snapshot.snapshot

        if command_name == "note.create":
            note_id = prev_state.get("note_id")
            if not note_id:
                raise ValueError(f"Cannot revert {command_name}: snapshot missing note_id")
            # Deliberately not NoteService.soft_delete(): it opens its own
            # `async with self.session.begin()`, which raises "A transaction
            # is already begun on this Session" here — ctx._async_db is a
            # long-lived, request-scoped session that may already have an
            # implicit transaction open from earlier work in the same
            # request. Query + flush directly instead (the pre-Milestone-1.6
            # manual revert logic in revert_action.py hit the same
            # constraint and used this same workaround).
            async with ctx.async_db() as db:
                stmt = select(Note).where(Note.id == UUID(note_id), Note.user_id == ctx.user_id)
                note = (await db.execute(stmt)).scalar_one_or_none()
                if not note:
                    raise ValueError(f"Note {note_id} not found")
                if not note.is_deleted:
                    note.is_deleted = True
                    # Must commit, not just flush: mark_reverted() below reuses
                    # this same session for its own (best-effort) PG audit
                    # write and rolls back on failure if that table/insert is
                    # unavailable — an uncommitted flush() here would be
                    # wiped out by that unrelated rollback.
                    await db.commit()

        elif command_name == "note.delete":
            note_id = prev_state.get("note_id")
            if not note_id:
                raise ValueError(f"Cannot revert {command_name}: snapshot missing note_id")
            # Soft-delete only flips a flag — content/title were never
            # destroyed, so un-delete is just the mirror of note.create's
            # revert above (same session-transaction constraint applies).
            async with ctx.async_db() as db:
                stmt = select(Note).where(Note.id == UUID(note_id), Note.user_id == ctx.user_id)
                note = (await db.execute(stmt)).scalar_one_or_none()
                if not note:
                    raise ValueError(f"Note {note_id} not found")
                if note.is_deleted:
                    note.is_deleted = False
                    await db.commit()

        elif command_name == "note.update":
            raise ValueError(
                f"{command_name} is not revertable via CommandRegistry — it only creates a "
                f"Proposal (nothing to restore). Reject the proposal instead."
            )

        elif command_name == "schedule.create":
            schedule_id = prev_state.get("schedule_id")
            if not schedule_id:
                raise ValueError(f"Cannot revert {command_name}: snapshot missing schedule_id")
            db = SessionLocal()
            try:
                ScheduleService(db).delete_schedule(schedule_id=UUID(schedule_id), user_id=ctx.user_id)
            finally:
                db.close()

        elif command_name == "schedule.update":
            schedule_id = prev_state.get("schedule_id")
            if not schedule_id:
                raise ValueError(f"Cannot revert {command_name}: snapshot missing schedule_id")
            db = SessionLocal()
            try:
                ScheduleService(db).update_schedule_fields(
                    schedule_id=UUID(schedule_id),
                    user_id=ctx.user_id,
                    title=prev_state.get("title"),
                    start_time=datetime.fromisoformat(prev_state["start_time"]) if prev_state.get("start_time") else None,
                    end_time=datetime.fromisoformat(prev_state["end_time"]) if prev_state.get("end_time") else None,
                    description=prev_state.get("description"),
                    is_completed=prev_state.get("is_completed"),
                )
            finally:
                db.close()

        elif command_name == "schedule.delete":
            schedule_id = prev_state.get("schedule_id")
            if not schedule_id:
                raise ValueError(f"Cannot revert {command_name}: snapshot missing schedule_id")
            # Hard delete — there's no row left to flip a flag on, so revert
            # means recreate. The new row gets a fresh id (returned in the
            # revert CommandResult's data), not the original schedule_id.
            db = SessionLocal()
            try:
                from app.models import ScheduleType

                ScheduleService(db).create_schedule_simple(
                    user_id=ctx.user_id,
                    title=prev_state.get("title") or "Untitled",
                    schedule_type=ScheduleType(prev_state["type"]) if prev_state.get("type") else ScheduleType.PERSONAL,
                    start_time=datetime.fromisoformat(prev_state["start_time"]),
                    end_time=datetime.fromisoformat(prev_state["end_time"]),
                    location=prev_state.get("location"),
                    description=prev_state.get("description"),
                )
            finally:
                db.close()

        else:
            raise ValueError(f"No revert logic for command: {command_name}")

    def list_commands(self) -> list[dict]:
        """List all registered commands (name, description, permission, revertable)."""
        return [
            {
                "name": h.name,
                "description": h.description,
                "permission_scope": h.permission_scope.value,
                "revertable": h.revertable,
            }
            for h in self._handlers.values()
        ]


# Global registry instance
_command_registry: Optional[CommandRegistry] = None


def get_command_registry() -> CommandRegistry:
    """Get or create the global CommandRegistry instance."""
    global _command_registry
    if _command_registry is None:
        _command_registry = CommandRegistry()
    return _command_registry


def reset_command_registry() -> None:
    """Reset the global registry (for testing)."""
    global _command_registry
    _command_registry = None
