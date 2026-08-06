"""Update schedule tool — thin wrapper around the schedule.update command."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class UpdateScheduleInput(BaseModel):
    schedule_id: str = Field(..., description="Schedule UUID to update")
    title: Optional[str] = Field(None, max_length=255)
    start_time: Optional[str] = Field(None, description="ISO 8601")
    end_time: Optional[str] = Field(None, description="ISO 8601")
    description: Optional[str] = Field(None, max_length=1000)
    is_completed: Optional[bool] = None


async def update_schedule_handler(args: dict, ctx: ToolContext) -> dict:
    """Update a schedule.

    Permission: schedule.update has no workspace_id on its Command (Schedule
    has no workspace concept — only user_id) — same ownership-only check as
    before migration.
    """
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    try:
        schedule_id = UUID(args["schedule_id"])
    except ValueError:
        raise ValueError(f"Invalid schedule_id: {args['schedule_id']}")

    if args.get("start_time"):
        try:
            datetime.fromisoformat(args["start_time"])
        except ValueError:
            raise ValueError(f"Invalid start_time: {args['start_time']}")

    if args.get("end_time"):
        try:
            datetime.fromisoformat(args["end_time"])
        except ValueError:
            raise ValueError(f"Invalid end_time: {args['end_time']}")

    command = Command(
        command_name="schedule.update",
        args={
            "schedule_id": str(schedule_id),
            "title": args.get("title"),
            "start_time": args.get("start_time"),
            "end_time": args.get("end_time"),
            "description": args.get("description"),
            "is_completed": args.get("is_completed"),
        },
        requested_by=ctx.user_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )

    result = await get_command_registry().execute(command, ctx)

    if not result.success:
        raise ValueError(result.error)

    data = {k: v for k, v in result.data.items() if k != "prev_state"}  # internal-only, prev_fields stays
    return {
        **data,
        "action_id": result.action_id,
        "revert_hint": "Bạn có thể hoàn tác cập nhật lịch này bằng action_id trên.",
        "success": True,
    }


UPDATE_SCHEDULE_SCHEMA = {
    "type": "object",
    "properties": {
        "schedule_id": {"type": "string", "description": "UUID of schedule to update"},
        "title": {"type": "string", "description": "New title (optional)"},
        "start_time": {"type": "string", "description": "ISO 8601 (optional)"},
        "end_time": {"type": "string", "description": "ISO 8601 (optional)"},
        "description": {"type": "string", "description": "New notes (optional)"},
        "is_completed": {"type": "boolean", "description": "Mark as completed (optional)"},
    },
    "required": ["schedule_id"],
}

UPDATE_SCHEDULE_DEFINITION = {
    "name": "update_schedule",
    "handler": update_schedule_handler,
    "input_model": UpdateScheduleInput,
    "schema": UPDATE_SCHEDULE_SCHEMA,
    "description": "Update an existing schedule. User must own the schedule.",
}