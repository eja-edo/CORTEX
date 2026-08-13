"""Create schedule tool — thin wrapper around the schedule.create command."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
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
    """Create schedule with optional recurrence and Google sync.

    Permission: schedule.create has no workspace_id on its Command (Schedule
    has no workspace concept — only user_id), so CommandRegistry falls back
    to its ownership-only check; matches this tool's pre-migration behavior,
    which never did a workspace-role check either.
    """
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    try:
        start_time = _parse_iso_with_tz(args["start_time"], "start_time")
        end_time = _parse_iso_with_tz(args["end_time"], "end_time")
    except ValueError as exc:
        raise ValueError(f"Invalid datetime format: {exc}")

    # Build recurrence dict with optional until-parsing (same strict
    # tz-offset validation as start_time/end_time — kept here rather than in
    # ScheduleCreateArgs since it's an AI-prompt-engineering concern, not a
    # domain rule other Command callers should be forced into).
    recurrence_data = None
    if args.get("recurrence_rule"):
        recurrence_input = args["recurrence_rule"]
        until = None
        if recurrence_input.get("until"):
            until = _parse_iso_with_tz(recurrence_input["until"], "recurrence_rule.until")
        recurrence_data = {
            "freq": recurrence_input["freq"],
            "interval": recurrence_input.get("interval", 1),
            "until": until.isoformat() if until else None,
            "count": recurrence_input.get("count"),
            "tzid": recurrence_input.get("tzid", "Asia/Ho_Chi_Minh"),
        }

    command = Command(
        command_name="schedule.create",
        args={
            "title": args["title"],
            "schedule_type": args["type"],
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "location": args.get("location"),
            "description": args.get("description"),
            "recurrence": recurrence_data,
        },
        requested_by=ctx.user_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )

    result = await get_command_registry().execute(command, ctx)

    if not result.success:
        raise ValueError(result.error)

    data = {k: v for k, v in result.data.items() if k != "prev_state"}  # internal-only, not for the LLM
    return {
        **data,
        "action_id": result.action_id,
        "revert_hint": "Bạn có thể hoàn tác tạo lịch này bằng action_id trên. Lưu ý: Google Calendar sync đã chạy, cần xóa thủ công trên Google.",
        "success": True,
    }



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
    "description": (
        "Create a SINGLE new schedule/event for the user, right now, immediately. "
        "Do NOT use this for a recurring practice/study/workout block that's part of "
        "a multi-phase plan you just proposed for a goal (\"tôi muốn học tiếng Anh\", "
        "\"tôi muốn giảm cân\", or anything broken into phases/milestones/checklist) — "
        "that whole plan (all its events AND tasks) must go through propose_plan "
        "instead, as one call, so the user reviews and approves every item — including "
        "the recurrence rule — before anything is booked. Calling create_schedule "
        "repeatedly for a plan's sessions skips that review entirely."
    ),
}