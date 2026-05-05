"""Get schedules tool."""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Schedule, ScheduleType
from app.services.agent.tool_context import ToolContext
from app.services.recurrence import RecurrenceService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GetSchedulesInput(BaseModel):
    """Validation model for get_schedules tool."""
    start_date: str = Field(..., description="ISO 8601 datetime (e.g., 2025-05-05T00:00:00)")
    end_date: str = Field(..., description="ISO 8601 datetime (e.g., 2025-05-12T23:59:59)")
    type_filter: Optional[str] = Field(
        None,
        pattern="^(CLASS|DEADLINE|EXAM|PERSONAL)?$",
        description="Optional schedule type filter"
    )
    limit: int = Field(default=50, ge=1, le=200, description="Max results")


async def get_schedules_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Get user's schedules within a date range.
    
    Security:
    - Always filtered by ctx.user_id (from authenticated session)
    """
    try:
        start_date = datetime.fromisoformat(args["start_date"])
        end_date = datetime.fromisoformat(args["end_date"])
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {exc}")

    type_filter = args.get("type_filter")
    limit = args.get("limit", 50)

    if start_date > end_date:
        raise ValueError("start_date must be before end_date")

    try:
        async with ctx.async_db() as db:
            # Get root schedules for the user
            stmt = select(Schedule).where(
                Schedule.user_id == ctx.user_id,
                Schedule.is_cancelled.is_(False),
            )

            if type_filter:
                stmt = stmt.where(Schedule.type == type_filter)

            result = await db.execute(stmt)
            root_schedules = result.scalars().all()

            # Generate instances using RecurrenceService
            # Note: RecurrenceService requires sync db, so we need to get one
            recurrence_service = RecurrenceService()

            # Convert async_db to sync context for recurrence service
            from app.database import SessionLocal
            sync_db = SessionLocal()
            try:
                all_instances = []
                for root in root_schedules:
                    instances = recurrence_service.generate_instances(
                        root, start_date, end_date, sync_db
                    )
                    all_instances.extend(instances)

                # Sort by start_time and limit
                all_instances.sort(key=lambda x: x["start_time"])
                all_instances = all_instances[:limit]

                return {
                    "count": len(all_instances),
                    "schedules": all_instances,
                }

            finally:
                sync_db.close()

    except Exception as exc:
        logger.error(f"get_schedules failed: {exc}", exc_info=True)
        raise


GET_SCHEDULES_SCHEMA = {
    "type": "object",
    "properties": {
        "start_date": {
            "type": "string",
            "description": "Start date in ISO 8601 format",
        },
        "end_date": {
            "type": "string",
            "description": "End date in ISO 8601 format",
        },
        "type_filter": {
            "type": "string",
            "enum": ["CLASS", "DEADLINE", "EXAM", "PERSONAL"],
            "description": "Optional schedule type filter",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of schedules to return",
        },
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
