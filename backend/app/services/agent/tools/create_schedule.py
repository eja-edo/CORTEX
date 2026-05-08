"""Create schedule tool — dùng ScheduleService thay vì query DB trực tiếp."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models import ScheduleType
from app.services.agent.tool_context import ToolContext
from app.services.schedule_service import ScheduleService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CreateScheduleInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern="^(CLASS|DEADLINE|EXAM|PERSONAL)$")
    start_time: str = Field(..., description="ISO 8601 datetime")
    end_time: str = Field(..., description="ISO 8601 datetime")
    location: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)


async def create_schedule_handler(args: dict, ctx: ToolContext) -> dict:
    try:
        start_time = datetime.fromisoformat(args["start_time"])
        end_time = datetime.fromisoformat(args["end_time"])
    except ValueError as exc:
        raise ValueError(f"Invalid datetime format: {exc}")

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        schedule = ScheduleService(db).create_schedule_simple(
            user_id=ctx.user_id,
            title=args["title"],
            schedule_type=ScheduleType[args["type"]],
            start_time=start_time,
            end_time=end_time,
            location=args.get("location"),
            description=args.get("description"),
        )
        return {
            "id": str(schedule.id),
            "title": schedule.title,
            "start_time": schedule.start_time.isoformat(),
            "end_time": schedule.end_time.isoformat(),
            "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
            "success": True,
        }
    except Exception as exc:
        logger.error("create_schedule failed: %s", exc, exc_info=True)
        raise
    finally:
        db.close()


CREATE_SCHEDULE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Schedule title"},
        "type": {
            "type": "string",
            "enum": ["CLASS", "DEADLINE", "EXAM", "PERSONAL"],
            "description": "Schedule type",
        },
        "start_time": {"type": "string", "description": "ISO 8601 start time"},
        "end_time": {"type": "string", "description": "ISO 8601 end time"},
        "location": {"type": "string", "description": "Location or meeting link (optional)"},
        "description": {"type": "string", "description": "Additional notes (optional)"},
    },
    "required": ["title", "type", "start_time", "end_time"],
}

CREATE_SCHEDULE_DEFINITION = {
    "name": "create_schedule",
    "handler": create_schedule_handler,
    "input_model": CreateScheduleInput,
    "schema": CREATE_SCHEDULE_SCHEMA,
    "description": "Create a new schedule/event for the user.",
}