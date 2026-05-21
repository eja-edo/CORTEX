"""Update schedule tool — dùng ScheduleService thay vì query DB trực tiếp."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.services.agent.tool_context import ToolContext
from app.services.schedule_service import ScheduleService
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
    try:
        schedule_id = UUID(args["schedule_id"])
    except ValueError:
        raise ValueError(f"Invalid schedule_id: {args['schedule_id']}")

    start_time = None
    if args.get("start_time"):
        try:
            start_time = datetime.fromisoformat(args["start_time"])
        except ValueError:
            raise ValueError(f"Invalid start_time: {args['start_time']}")

    end_time = None
    if args.get("end_time"):
        try:
            end_time = datetime.fromisoformat(args["end_time"])
        except ValueError:
            raise ValueError(f"Invalid end_time: {args['end_time']}")

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        schedule = ScheduleService(db).update_schedule_fields(
            schedule_id=schedule_id,
            user_id=ctx.user_id,
            title=args.get("title"),
            start_time=start_time,
            end_time=end_time,
            description=args.get("description"),
            is_completed=args.get("is_completed"),
        )
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
        logger.error("update_schedule failed: %s", exc, exc_info=True)
        raise
    finally:
        db.close()


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