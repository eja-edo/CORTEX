"""Get schedules tool — dùng ScheduleService thay vì query DB trực tiếp."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.services.agent.tool_context import ToolContext
from app.services.schedule_service import ScheduleService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GetSchedulesInput(BaseModel):
    start_date: str = Field(..., description="ISO 8601 datetime")
    end_date: str = Field(..., description="ISO 8601 datetime")
    type_filter: Optional[str] = Field(
        None, pattern="^(CLASS|DEADLINE|EXAM|PERSONAL)?$"
    )
    limit: int = Field(default=50, ge=1, le=200)


async def get_schedules_handler(args: dict, ctx: ToolContext) -> dict:
    try:
        start_date = datetime.fromisoformat(args["start_date"])
        end_date = datetime.fromisoformat(args["end_date"])
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {exc}")

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return ScheduleService(db).list_schedules_for_agent(
            user_id=ctx.user_id,
            start_date=start_date,
            end_date=end_date,
            type_filter=args.get("type_filter"),
            limit=args.get("limit", 50),
        )
    except Exception as exc:
        logger.error("get_schedules failed: %s", exc, exc_info=True)
        raise
    finally:
        db.close()


GET_SCHEDULES_SCHEMA = {
    "type": "object",
    "properties": {
        "start_date": {"type": "string", "description": "ISO 8601 start date"},
        "end_date": {"type": "string", "description": "ISO 8601 end date"},
        "type_filter": {
            "type": "string",
            "enum": ["CLASS", "DEADLINE", "EXAM", "PERSONAL"],
            "description": "Optional schedule type filter",
        },
        "limit": {"type": "integer", "description": "Max results (default 50)"},
    },
    "required": ["start_date", "end_date"],
}

GET_SCHEDULES_DEFINITION = {
    "name": "get_schedules",
    "handler": get_schedules_handler,
    "input_model": GetSchedulesInput,
    "schema": GET_SCHEDULES_SCHEMA,
    "description": "Get user's schedules within a date range. Returns both single and recurring events.",
}