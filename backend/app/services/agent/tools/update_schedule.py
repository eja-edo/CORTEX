"""Update schedule tool."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Schedule
from app.services.agent.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class UpdateScheduleInput(BaseModel):
    """Validation model for update_schedule tool."""
    schedule_id: str = Field(..., description="Schedule UUID to update")
    title: Optional[str] = Field(None, max_length=255, description="New title")
    start_time: Optional[str] = Field(None, description="New start time (ISO 8601)")
    end_time: Optional[str] = Field(None, description="New end time (ISO 8601)")
    description: Optional[str] = Field(None, max_length=1000, description="New notes")
    is_completed: Optional[bool] = Field(None, description="Mark as completed")


async def update_schedule_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Update an existing schedule.
    
    Security:
    - User must own the schedule
    """
    try:
        schedule_id = UUID(args["schedule_id"])
    except ValueError:
        raise ValueError(f"Invalid schedule_id format: {args['schedule_id']}")

    try:
        async with ctx.async_db() as db:
            # Get schedule (must own it)
            stmt = select(Schedule).where(
                Schedule.id == schedule_id,
                Schedule.user_id == ctx.user_id,
            )
            result = await db.execute(stmt)
            schedule = result.scalar_one_or_none()

            if not schedule:
                raise ValueError("Schedule not found or you don't have permission to update it")

            # Apply updates
            if "title" in args and args["title"] is not None:
                schedule.title = args["title"]

            if "start_time" in args and args["start_time"] is not None:
                try:
                    schedule.start_time = datetime.fromisoformat(args["start_time"])
                except ValueError:
                    raise ValueError(f"Invalid start_time format: {args['start_time']}")

            if "end_time" in args and args["end_time"] is not None:
                try:
                    schedule.end_time = datetime.fromisoformat(args["end_time"])
                except ValueError:
                    raise ValueError(f"Invalid end_time format: {args['end_time']}")

            if "description" in args and args["description"] is not None:
                schedule.description = args["description"]

            if "is_completed" in args and args["is_completed"] is not None:
                schedule.is_completed = args["is_completed"]

            # Validate start < end
            if schedule.start_time >= schedule.end_time:
                raise ValueError("start_time must be before end_time")

            await db.flush()

            return {
                "id": str(schedule.id),
                "title": schedule.title,
                "start_time": schedule.start_time.isoformat(),
                "end_time": schedule.end_time.isoformat(),
                "is_completed": schedule.is_completed,
                "updated_at": schedule.updated_at.isoformat() if schedule.updated_at else None,
                "success": True,
            }

    except Exception as exc:
        logger.error(f"update_schedule failed: {exc}", exc_info=True)
        raise


UPDATE_SCHEDULE_SCHEMA = {
    "type": "object",
    "properties": {
        "schedule_id": {
            "type": "string",
            "description": "UUID of schedule to update",
        },
        "title": {
            "type": "string",
            "description": "New title (optional)",
        },
        "start_time": {
            "type": "string",
            "description": "New start time in ISO 8601 format (optional)",
        },
        "end_time": {
            "type": "string",
            "description": "New end time in ISO 8601 format (optional)",
        },
        "description": {
            "type": "string",
            "description": "New notes (optional)",
        },
        "is_completed": {
            "type": "boolean",
            "description": "Mark as completed (optional)",
        },
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
