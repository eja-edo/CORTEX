"""Create schedule tool — dùng ScheduleService thay vì query DB trực tiếp."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field

from app.models import ScheduleType, SyncOperation
from app.ai.agents.action_snapshot_store import ActionSnapshot, get_snapshot_store
from app.ai.agents.tool_context import ToolContext
from app.services.schedule_service import ScheduleService
from app.schemas import ScheduleCreate, RecurrenceRuleInput
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RecurrenceRuleInputData(BaseModel):
    """Optional recurrence rule for repeating events."""
    freq: str = Field(..., pattern="^(NONE|DAILY|WEEKLY|MONTHLY)$", description="Frequency: NONE, DAILY, WEEKLY, MONTHLY")
    interval: int = Field(default=1, ge=1, le=365, description="Repeat every N days/weeks/months")
    until: Optional[str] = Field(None, description="ISO 8601 datetime with timezone offset (stop recurrence on this date)")
    count: Optional[int] = Field(None, ge=1, le=730, description="Number of occurrences")
    tzid: str = Field(default="Asia/Ho_Chi_Minh", description="Timezone ID")


class CreateScheduleInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern="^(CLASS|DEADLINE|EXAM|PERSONAL)$")
    start_time: str = Field(
        ...,
        description=(
            "ISO 8601 datetime with timezone offset (e.g. 2026-05-20T10:00:00+07:00). "
            "Do not use 'Z'."
        ),
    )
    end_time: str = Field(
        ...,
        description=(
            "ISO 8601 datetime with timezone offset (e.g. 2026-05-20T11:00:00+07:00). "
            "Do not use 'Z'."
        ),
    )
    location: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    recurrence_rule: Optional[RecurrenceRuleInputData] = Field(None, description="Optional recurrence rule for repeating events")



def _parse_iso_with_tz(value: str, field_name: str) -> datetime:
    if value.endswith("Z") or value.endswith("z"):
        raise ValueError(
            f"{field_name} must include a timezone offset like +07:00 (do not use 'Z')."
        )
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name} format: {exc}")

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(
            f"{field_name} must include a timezone offset like +07:00."
        )

    return dt.astimezone(timezone.utc)


async def create_schedule_handler(args: dict, ctx: ToolContext) -> dict:
    """Create schedule with optional recurrence and Google sync."""
    try:
        start_time = _parse_iso_with_tz(args["start_time"], "start_time")
        end_time = _parse_iso_with_tz(args["end_time"], "end_time")
    except ValueError as exc:
        raise ValueError(f"Invalid datetime format: {exc}")

    from app.database import SessionLocal
    from app.api.schedules import _enqueue_google_sync

    db = SessionLocal()
    result_data = {}
    schedule = None
    try:
        # Build ScheduleCreate input with optional recurrence
        recurrence_data = None
        if args.get("recurrence_rule"):
            recurrence_input = args["recurrence_rule"]
            # Parse until datetime if provided
            until = None
            if recurrence_input.get("until"):
                until = _parse_iso_with_tz(recurrence_input["until"], "recurrence_rule.until")

            recurrence_data = RecurrenceRuleInput(
                freq=recurrence_input["freq"],
                interval=recurrence_input.get("interval", 1),
                until=until,
                count=recurrence_input.get("count"),
                tzid=recurrence_input.get("tzid", "Asia/Ho_Chi_Minh"),
            )

        schedule_create = ScheduleCreate(
            title=args["title"],
            type=ScheduleType[args["type"]],
            start_time=start_time,
            end_time=end_time,
            location=args.get("location"),
            description=args.get("description"),
            recurrence=recurrence_data,
        )

        svc = ScheduleService(db)
        schedule = svc.create_schedule(user_id=ctx.user_id, data=schedule_create)

        # Sync with Google Calendar
        await _enqueue_google_sync(schedule, SyncOperation.UPSERT)

        result_data = {
            "id": str(schedule.id),
            "title": schedule.title,
            "start_time": schedule.start_time.isoformat(),
            "end_time": schedule.end_time.isoformat(),
            "recurrence": schedule.recurrence_rule,
            "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
        }
    except Exception as exc:
        logger.error("create_schedule failed: %s", exc, exc_info=True)
        raise
    finally:
        db.close()

    # --- REVERT SNAPSHOT (outside sync DB context) ---
    snapshot = ActionSnapshot(
        tool_name="create_schedule",
        user_id=str(ctx.user_id),
        conversation_id=str(getattr(ctx, "conversation_id", "")),
        snapshot={
            "op": "create_schedule",
            "schedule_id": str(schedule.id) if schedule else result_data.get("id", ""),
        },
    )
    action_id = await get_snapshot_store().save(snapshot)
    # --------------------------------------------------

    result_data["action_id"] = action_id
    result_data["revert_hint"] = "Bạn có thể hoàn tác tạo lịch này bằng action_id trên. Lưu ý: Google Calendar sync đã chạy, cần xóa thủ công trên Google."
    result_data["success"] = True
    return result_data



CREATE_SCHEDULE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Schedule title"},
        "type": {
            "type": "string",
            "enum": ["CLASS", "DEADLINE", "EXAM", "PERSONAL"],
            "description": "Schedule type",
        },
        "start_time": {
            "type": "string",
            "description": "ISO 8601 datetime with timezone offset (e.g. 2026-05-20T10:00:00+07:00). Do not use 'Z'.",
        },
        "end_time": {
            "type": "string",
            "description": "ISO 8601 datetime with timezone offset (e.g. 2026-05-20T11:00:00+07:00). Do not use 'Z'.",
        },
        "location": {"type": "string", "description": "Location or meeting link (optional)"},
        "description": {"type": "string", "description": "Additional notes (optional)"},
        "recurrence_rule": {
            "type": "object",
            "description": "Optional recurrence rule for repeating events",
            "properties": {
                "freq": {
                    "type": "string",
                    "enum": ["NONE", "DAILY", "WEEKLY", "MONTHLY"],
                    "description": "Frequency of recurrence"
                },
                "interval": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "default": 1,
                    "description": "Repeat every N days/weeks/months"
                },
                "until": {
                    "type": "string",
                    "description": "ISO 8601 datetime with timezone offset when recurrence should stop"
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 730,
                    "description": "Number of occurrences"
                },
                "tzid": {
                    "type": "string",
                    "default": "Asia/Ho_Chi_Minh",
                    "description": "Timezone ID"
                }
            },
            "required": ["freq"]
        }
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