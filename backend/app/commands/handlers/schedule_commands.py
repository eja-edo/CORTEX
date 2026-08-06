"""
Schedule command handlers.

Actual implementations invoked by CommandRegistry. Tool handlers in
app/ai/tools/ are thin wrappers — see create_schedule.py / update_schedule.py.
"""

from uuid import UUID

from app.commands.args import ScheduleCreateArgs, ScheduleDeleteArgs, ScheduleUpdateArgs
from app.commands.schemas import Command, PermissionScope
from app.ai.agents.tool_context import ToolContext
from app.models import SyncOperation
from app.schemas import RecurrenceRuleInput, ReminderConfig, ScheduleCreate
from app.services.schedule_service import ScheduleService
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def schedule_create_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Create schedule command handler.

    Includes the Google Calendar sync enqueue the real create_schedule tool
    already does (app/ai/tools/create_schedule.py) — it belongs here, not in
    the tool wrapper, so any future caller of schedule.create gets it too.
    """
    from app.api.schedules import _enqueue_google_sync

    args = ScheduleCreateArgs(**command.args)

    recurrence_data = RecurrenceRuleInput(**args.recurrence) if args.recurrence else None
    reminders_data = [ReminderConfig(**r) for r in args.reminders] if args.reminders else None

    with ctx:
        db = ctx.get_sync_db()
        service = ScheduleService(db)
        schedule = service.create_schedule(
            user_id=ctx.user_id,
            data=ScheduleCreate(
                title=args.title,
                type=args.schedule_type,
                start_time=args.start_time,
                end_time=args.end_time,
                location=args.location,
                description=args.description,
                recurrence=recurrence_data,
                reminders=reminders_data,
            ),
        )

    await _enqueue_google_sync(schedule, SyncOperation.UPSERT)

    logger.info(f"Schedule created: {schedule.id}")

    return {
        "id": str(schedule.id),
        "title": schedule.title,
        "start_time": schedule.start_time.isoformat(),
        "end_time": schedule.end_time.isoformat(),
        "recurrence": schedule.recurrence_rule,
        "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
        "prev_state": {"schedule_id": str(schedule.id)},  # For revert (delete)
    }


async def schedule_update_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Update schedule command handler.

    `location` is accepted by ScheduleUpdateArgs but not applied: the real
    ScheduleService.update_schedule_fields() has no location parameter and
    the existing update_schedule AI tool never exposed it either — same gap
    as before migration, not introduced here.
    """
    args = ScheduleUpdateArgs(**command.args)

    with ctx:
        db = ctx.get_sync_db()
        service = ScheduleService(db)

        current = service.get_schedule_by_id(args.schedule_id, ctx.user_id)
        if not current:
            raise ValueError(f"Schedule not found: {args.schedule_id}")

        prev_fields = {
            "schedule_id": str(args.schedule_id),
            "title": current.title,
            "start_time": current.start_time.isoformat(),
            "end_time": current.end_time.isoformat(),
            "description": current.description,
            "is_completed": current.is_completed,
        }

        updated = service.update_schedule_fields(
            schedule_id=args.schedule_id,
            user_id=ctx.user_id,
            title=args.title,
            start_time=args.start_time,
            end_time=args.end_time,
            description=args.description,
            is_completed=args.is_completed,
        )

        logger.info(f"Schedule updated: {updated.id}")

        return {
            "id": str(updated.id),
            "title": updated.title,
            "start_time": updated.start_time.isoformat(),
            "end_time": updated.end_time.isoformat(),
            "is_completed": updated.is_completed,
            "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
            # The existing update_schedule tool exposes prev_fields directly
            # in its response (backward-compat) — CommandRegistry separately
            # reads "prev_state" for the undo snapshot, so both keys carry
            # the same dict.
            "prev_fields": prev_fields,
            "prev_state": prev_fields,
        }


async def schedule_delete_handler(command: Command, ctx: ToolContext) -> dict:
    """Delete schedule command handler. No AI tool exposes this directly
    yet — registered for completeness/future use."""
    args = ScheduleDeleteArgs(**command.args)

    with ctx:
        db = ctx.get_sync_db()
        service = ScheduleService(db)

        schedule = service.get_schedule_by_id(args.schedule_id, ctx.user_id)
        if not schedule:
            raise ValueError(f"Schedule not found: {args.schedule_id}")

        prev_state = {
            "schedule_id": str(args.schedule_id),
            "title": schedule.title,
            "type": schedule.type.value,
            "start_time": schedule.start_time.isoformat(),
            "end_time": schedule.end_time.isoformat(),
            "location": schedule.location,
            "description": schedule.description,
        }

        service.delete_schedule(schedule_id=args.schedule_id, user_id=ctx.user_id)

        logger.info(f"Schedule deleted: {args.schedule_id}")

        return {
            "schedule_id": str(args.schedule_id),
            "deleted": True,
            "prev_state": prev_state,
        }


def register_schedule_commands() -> None:
    """Register all schedule commands with the global CommandRegistry."""
    from app.commands.registry import get_command_registry

    registry = get_command_registry()

    registry.register(
        name="schedule.create",
        description="Create a new schedule",
        args_schema=ScheduleCreateArgs,
        handler=schedule_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
    )

    registry.register(
        name="schedule.update",
        description="Update an existing schedule",
        args_schema=ScheduleUpdateArgs,
        handler=schedule_update_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
    )

    registry.register(
        name="schedule.delete",
        description="Delete schedule",
        args_schema=ScheduleDeleteArgs,
        handler=schedule_delete_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
    )

    logger.info("Schedule commands registered")
