"""Create schedule tool."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.models import Schedule, ScheduleType
from app.services.agent.tool_context import ToolContext
from app.services.workspace_permission import WorkspacePermission
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CreateScheduleInput(BaseModel):
    """Validation model for create_schedule tool."""
    title: str = Field(..., min_length=1, max_length=255, description="Schedule title")
    type: str = Field(
        ...,
        pattern="^(CLASS|DEADLINE|EXAM|PERSONAL)$",
        description="Schedule type"
    )
    start_time: str = Field(..., description="ISO 8601 datetime")
    end_time: str = Field(..., description="ISO 8601 datetime")
    location: Optional[str] = Field(None, max_length=255, description="Location or link")
    description: Optional[str] = Field(None, max_length=1000, description="Notes")
    workspace_id: Optional[str] = Field(None, description="Optional workspace UUID")


async def create_schedule_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Create a new schedule/event for the user.
    
    Security:
    - Optional workspace context
    - If workspace specified, user must be editor
    """
    try:
        start_time = datetime.fromisoformat(args["start_time"])
        end_time = datetime.fromisoformat(args["end_time"])
    except ValueError as exc:
        raise ValueError(f"Invalid datetime format: {exc}")

    if start_time >= end_time:
        raise ValueError("start_time must be before end_time")

    title = args["title"]
    schedule_type = args["type"]
    location = args.get("location")
    description = args.get("description")
    workspace_id_str = args.get("workspace_id")

    workspace_id = None
    if workspace_id_str:
        try:
            workspace_id = UUID(workspace_id_str)
            # Check workspace permission
            with ctx.get_sync_db() as sync_db:
                member = WorkspacePermission.require_member(workspace_id, ctx.user_id, sync_db)
                WorkspacePermission.require_editor(member)
        except ValueError:
            raise ValueError(f"Invalid workspace_id format: {workspace_id_str}")

    try:
        async with ctx.async_db() as db:
            schedule = Schedule(
                user_id=ctx.user_id,
                workspace_id=workspace_id,
                title=title,
                type=ScheduleType[schedule_type],  # Convert string to enum
                start_time=start_time,
                end_time=end_time,
                location=location,
                description=description,
            )
            db.add(schedule)
            await db.flush()

            return {
                "id": str(schedule.id),
                "title": schedule.title,
                "start_time": schedule.start_time.isoformat(),
                "end_time": schedule.end_time.isoformat(),
                "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
                "success": True,
            }

    except Exception as exc:
        logger.error(f"create_schedule failed: {exc}", exc_info=True)
        raise


CREATE_SCHEDULE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Schedule title",
        },
        "type": {
            "type": "string",
            "enum": ["CLASS", "DEADLINE", "EXAM", "PERSONAL"],
            "description": "Schedule type",
        },
        "start_time": {
            "type": "string",
            "description": "Start time in ISO 8601 format",
        },
        "end_time": {
            "type": "string",
            "description": "End time in ISO 8601 format",
        },
        "location": {
            "type": "string",
            "description": "Location or meeting link (optional)",
        },
        "description": {
            "type": "string",
            "description": "Additional notes (optional)",
        },
        "workspace_id": {
            "type": "string",
            "description": "Optional workspace UUID to associate schedule",
        },
    },
    "required": ["title", "type", "start_time", "end_time"],
}

CREATE_SCHEDULE_DEFINITION = {
    "name": "create_schedule",
    "handler": create_schedule_handler,
    "input_model": CreateScheduleInput,
    "schema": CREATE_SCHEDULE_SCHEMA,
    "description": "Create a new schedule/event. User must be editor in workspace if specified.",
}
