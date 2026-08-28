"""
Task command handlers (Milestone 2.5).

Implementations invoked by CommandRegistry, going through TaskService — the
same path app/api/tasks.py uses. That's what keeps the status state machine
and the `task.*` events identical whether the write came from a person, the
chat agent, conversation extraction (`app.services.task_extraction`), or a
workflow (4.3).
"""

from datetime import datetime
from uuid import UUID

from app.ai.agents.action_snapshot_store import ActionSnapshot
from app.ai.agents.tool_context import ToolContext
from app.commands.args import (
    TaskCompleteArgs,
    TaskConfirmArgs,
    TaskCreateArgs,
    TaskDeleteArgs,
    TaskRejectArgs,
    TaskUpdateArgs,
)
from app.commands.schemas import Command, PermissionScope
from app.models import Task, TaskStatus
from app.schemas import TaskCreate, TaskUpdate
from app.services.tasks import InvalidTaskTransition, TaskService
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _task_snapshot(task) -> dict:
    """`prev_state` for revert: the fields a task command can change."""
    return {
        "task_id": str(task.id),
        "title": task.title,
        "status": task.status.value,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "priority": task.priority.value if task.priority else None,
        "description": task.description,
        "related_event_id": str(task.related_event_id) if task.related_event_id else None,
    }


async def task_create_handler(command: Command, ctx: ToolContext) -> dict:
    """Create task command handler. Tasks are user-scoped, so there's no
    workspace role check — ownership is enforced by TaskService filtering
    on `user_id`."""
    args = TaskCreateArgs(**command.args)

    async with ctx.async_db() as db:
        service = TaskService(db)
        task = await service.create_task(
            payload=TaskCreate(
                title=args.title,
                status=args.status,
                due_date=args.due_date,
                priority=args.priority,
                description=args.description,
                # `None` ở đây không phải "không có dự án" mà là "người gọi
                # không có ý kiến" — `TaskService.create_task` khi đó chạy
                # thang 3.5: dự án của sự kiện liên quan, rồi dự án cá nhân.
                project_id=args.project_id,
                related_event_id=args.related_event_id,
                parent_task_id=args.parent_task_id,
            ),
            user_id=ctx.user_id,
        )

        logger.info(f"Task created: {task.id}")

        return {
            "id": str(task.id),
            "title": task.title,
            "status": task.status.value,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "priority": task.priority.value if task.priority else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "prev_state": {"task_id": str(task.id)},  # For revert (delete)
        }


async def task_update_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Update task command handler.

    Only fields the caller actually supplied are applied — see TaskUpdateArgs
    for why `None` reads as "unchanged" on the command path. An illegal
    status transition surfaces as a failed CommandResult (TaskService raises
    InvalidTaskTransition, a ValueError).
    """
    args = TaskUpdateArgs(**command.args)

    changes = {
        field: value
        for field, value in (
            ("title", args.title),
            ("status", args.status),
            ("due_date", args.due_date),
            ("priority", args.priority),
            ("description", args.description),
            ("related_event_id", args.related_event_id),
        )
        if value is not None
    }

    async with ctx.async_db() as db:
        service = TaskService(db)

        current = await service.get_task(args.task_id, ctx.user_id)
        if current is None:
            raise ValueError(f"Task not found: {args.task_id}")

        prev_state = _task_snapshot(current)

        if not changes:
            return {
                "id": str(current.id),
                "status": current.status.value,
                "updated": False,
                "fields_changed": [],
                "prev_state": prev_state,
            }

        if await service.is_linked_to_recurring_event(current):
            # Toggling done/todo (status the only field changing) is always
            # scoped to the one occurrence being acted on — never a choice,
            # so it never needs edit_scope from the caller. Any other field
            # still requires it explicitly.
            is_pure_completion_toggle = set(changes) == {"status"}
            if is_pure_completion_toggle and args.occurrence_start_time and not args.edit_scope:
                args.edit_scope = "this_only"

            if not args.occurrence_start_time or not args.edit_scope:
                raise ValueError(
                    "This task is a checklist item on a recurring event — "
                    "specify occurrence_start_time and edit_scope (this_only "
                    "or all) so the update targets the right occurrence."
                )
            updated = await service.update_task_occurrence(
                task_id=args.task_id,
                user_id=ctx.user_id,
                occurrence_start_time=args.occurrence_start_time,
                edit_scope=args.edit_scope,
                payload=TaskUpdate(**changes),
            )
        else:
            updated = await service.update_task(
                task_id=args.task_id,
                user_id=ctx.user_id,
                payload=TaskUpdate(**changes),
            )
        if updated is None:
            raise ValueError(f"Task not found: {args.task_id}")

        logger.info(f"Task updated: {updated.id} (fields={sorted(changes)})")

        return {
            "id": str(updated.id),
            "title": updated.title,
            "status": updated.status.value,
            "due_date": updated.due_date.isoformat() if updated.due_date else None,
            "priority": updated.priority.value if updated.priority else None,
            "updated": True,
            "fields_changed": sorted(changes.keys()),
            "prev_state": prev_state,
        }


async def task_complete_handler(command: Command, ctx: ToolContext) -> dict:
    """Complete task command handler — the `tick the box` path (2.6).

    Goes through the state machine like any other transition: completing a
    cancelled task fails, completing an already-done one is a no-op.
    """
    args = TaskCompleteArgs(**command.args)

    async with ctx.async_db() as db:
        service = TaskService(db)

        current = await service.get_task(args.task_id, ctx.user_id)
        if current is None:
            raise ValueError(f"Task not found: {args.task_id}")

        prev_state = _task_snapshot(current)
        already_done = current.status is TaskStatus.DONE

        if await service.is_linked_to_recurring_event(current):
            # This endpoint only ever completes — it's always scoped to the
            # one occurrence being acted on, never a series-wide choice, so
            # it never needs edit_scope from the caller.
            if args.occurrence_start_time and not args.edit_scope:
                args.edit_scope = "this_only"

            if not args.occurrence_start_time or not args.edit_scope:
                raise ValueError(
                    "This task is a checklist item on a recurring event — "
                    "specify occurrence_start_time so completing it targets "
                    "the right occurrence."
                )
            completed = await service.complete_task_occurrence(
                task_id=args.task_id,
                user_id=ctx.user_id,
                occurrence_start_time=args.occurrence_start_time,
                edit_scope=args.edit_scope,
            )
        else:
            completed = await service.complete_task(task_id=args.task_id, user_id=ctx.user_id)
        if completed is None:
            raise ValueError(f"Task not found: {args.task_id}")

        logger.info(f"Task completed: {completed.id}")

        return {
            "id": str(completed.id),
            "title": completed.title,
            "status": completed.status.value,
            "completed": not already_done,
            "prev_state": prev_state,
        }


async def task_confirm_handler(command: Command, ctx: ToolContext) -> dict:
    """Confirm task command handler — approving a suggestion the extraction
    pipeline made: pending_confirm → todo."""
    args = TaskConfirmArgs(**command.args)

    async with ctx.async_db() as db:
        service = TaskService(db)

        current = await service.get_task(args.task_id, ctx.user_id)
        if current is None:
            raise ValueError(f"Task not found: {args.task_id}")

        prev_state = _task_snapshot(current)

        try:
            confirmed = await service.confirm_task(task_id=args.task_id, user_id=ctx.user_id)
        except InvalidTaskTransition as exc:
            raise ValueError(str(exc)) from exc
        if confirmed is None:
            raise ValueError(f"Task not found: {args.task_id}")

        logger.info(f"Task confirmed: {confirmed.id}")

        return {
            "id": str(confirmed.id),
            "title": confirmed.title,
            "status": confirmed.status.value,
            "prev_state": prev_state,
        }


async def task_reject_handler(command: Command, ctx: ToolContext) -> dict:
    """Reject task command handler. The row stays — it's what stops the
    extractor proposing this same suggestion again."""
    args = TaskRejectArgs(**command.args)

    async with ctx.async_db() as db:
        service = TaskService(db)

        current = await service.get_task(args.task_id, ctx.user_id)
        if current is None:
            raise ValueError(f"Task not found: {args.task_id}")

        prev_state = _task_snapshot(current)

        try:
            rejected = await service.reject_task(task_id=args.task_id, user_id=ctx.user_id)
        except InvalidTaskTransition as exc:
            raise ValueError(str(exc)) from exc
        if rejected is None:
            raise ValueError(f"Task not found: {args.task_id}")

        logger.info(f"Task rejected: {rejected.id}")

        return {
            "id": str(rejected.id),
            "title": rejected.title,
            "status": rejected.status.value,
            "prev_state": prev_state,
        }


async def task_delete_handler(command: Command, ctx: ToolContext) -> dict:
    """Delete task command handler — the checklist's "remove this line" (2.6).

    A hard delete: `cancelled` is the "not doing this, but keep the record"
    state, so an actual delete means the line shouldn't exist at all.
    """
    args = TaskDeleteArgs(**command.args)

    async with ctx.async_db() as db:
        service = TaskService(db)

        current = await service.get_task(args.task_id, ctx.user_id)
        if current is None:
            raise ValueError(f"Task not found: {args.task_id}")

        prev_state = _task_snapshot(current)

        deleted = await service.delete_task(args.task_id, ctx.user_id)
        if not deleted:
            raise ValueError(f"Task not found: {args.task_id}")

        logger.info(f"Task deleted: {args.task_id}")

        return {
            "task_id": str(args.task_id),
            "deleted": True,
            "prev_state": prev_state,
        }


async def task_create_revert_handler(snapshot: ActionSnapshot, ctx: ToolContext) -> None:
    """Revert task.create — delete the task.

    Registered explicitly: CommandRegistry._default_revert is a hardcoded
    if-chain over note.*/schedule.* and raises for anything else, so a
    revertable command without its own handler only fails at revert time.
    """
    task_id = snapshot.snapshot.get("task_id")
    if not task_id:
        raise ValueError("Cannot revert task.create: snapshot missing task_id")

    async with ctx.async_db() as db:
        deleted = await TaskService(db).delete_task(UUID(task_id), ctx.user_id)
        if not deleted:
            raise ValueError(f"Task {task_id} not found")


async def task_restore_revert_handler(snapshot: ActionSnapshot, ctx: ToolContext) -> None:
    """Revert task.update / task.complete — restore every field from
    `prev_state`.

    Restoring the old status is itself a transition, and it may be one the
    state machine forbids (completing a task from `todo` is legal;
    `done → todo` is legal, so the common cases work — but `cancelled → done`
    is not, so reverting is not universally possible). The restore therefore
    reports the transition error as-is rather than bypassing the rules: an
    undo that puts a task into a state the app otherwise refuses would be a
    worse outcome than a failed undo.
    """
    prev_state = snapshot.snapshot
    task_id = prev_state.get("task_id")
    if not task_id:
        raise ValueError("Cannot revert task update: snapshot missing task_id")

    async with ctx.async_db() as db:
        restored = await TaskService(db).update_task(
            task_id=UUID(task_id),
            user_id=ctx.user_id,
            payload=TaskUpdate(
                title=prev_state.get("title"),
                status=prev_state.get("status"),
                due_date=prev_state.get("due_date"),
                priority=prev_state.get("priority"),
                description=prev_state.get("description"),
                related_event_id=prev_state.get("related_event_id"),
            ),
        )
        if restored is None:
            raise ValueError(f"Task {task_id} not found")


async def task_delete_revert_handler(snapshot: ActionSnapshot, ctx: ToolContext) -> None:
    """Revert task.delete — recreate the task from the snapshot.

    A hard delete leaves no row to flip a flag on, so undo means recreate.
    The new task gets a **fresh id** (same caveat as schedule.delete's
    revert): anything holding the old id — an open checklist widget — will
    not be re-pointed at it.
    """
    prev_state = snapshot.snapshot
    if not prev_state.get("task_id"):
        raise ValueError("Cannot revert task.delete: snapshot missing task_id")

    async with ctx.async_db() as db:
        # Snapshot cũ (ghi trước khi `projects` tồn tại) không có trường
        # này. Rơi về dự án cá nhân thay vì fail — khôi phục một việc vào
        # đúng chỗ mặc định tốt hơn là không khôi phục được.
        from app.services.projects import ProjectService

        raw_project_id = prev_state.get("project_id")
        project_id = (
            UUID(raw_project_id)
            if raw_project_id
            else (await ProjectService(db).get_or_create_personal(ctx.user_id)).id
        )
        task = Task(
            user_id=ctx.user_id,
            project_id=project_id,
            title=prev_state.get("title") or "Untitled",
            status=TaskStatus(prev_state["status"]) if prev_state.get("status") else TaskStatus.TODO,
            due_date=datetime.fromisoformat(prev_state["due_date"]) if prev_state.get("due_date") else None,
            priority=prev_state.get("priority"),
            description=prev_state.get("description"),
            related_event_id=UUID(prev_state["related_event_id"]) if prev_state.get("related_event_id") else None,
        )
        db.add(task)
        await db.commit()


def register_task_commands() -> None:
    """Register all task commands with the global CommandRegistry."""
    from app.commands.registry import get_command_registry

    registry = get_command_registry()

    registry.register(
        name="task.create",
        description="Create a task (a unit of work with an optional deadline, priority, or event)",
        args_schema=TaskCreateArgs,
        handler=task_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_create_revert_handler,
    )

    registry.register(
        name="task.update",
        description="Update a task (title, status, due date, or what it relates to)",
        args_schema=TaskUpdateArgs,
        handler=task_update_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_restore_revert_handler,
    )

    registry.register(
        name="task.complete",
        description="Mark a task as done",
        args_schema=TaskCompleteArgs,
        handler=task_complete_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_restore_revert_handler,
    )

    registry.register(
        name="task.confirm",
        description="Confirm a suggested task (pending_confirm → todo)",
        args_schema=TaskConfirmArgs,
        handler=task_confirm_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_restore_revert_handler,
    )

    registry.register(
        name="task.reject",
        description="Reject a suggested task (pending_confirm → rejected)",
        args_schema=TaskRejectArgs,
        handler=task_reject_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_restore_revert_handler,
    )

    registry.register(
        name="task.delete",
        description="Delete a task (removes a line from an event's checklist)",
        args_schema=TaskDeleteArgs,
        handler=task_delete_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_delete_revert_handler,
    )

    logger.info("Task commands registered")
