"""Create task tool — thin wrapper around the task.create command.

Chat is the dominant way work gets created (2.5's entry-path table: "nói 1
câu"), and the "Hôm nay" screen (2.7) shows nothing until something exists.
Without this tool the agent can create notes and schedules but not the one
thing that screen is built to display, so the whole loop stays empty.
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CreateTaskInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    due_date: Optional[str] = Field(
        None,
        description=(
            "Calendar day the task must be done by, as YYYY-MM-DD. A task has "
            "a deadline, not a time slot — if the user is describing something "
            "that occupies a span of time (a meeting), use create_schedule."
        ),
    )
    priority: Optional[str] = Field(
        None, description="One of low, medium, high, urgent — only when the user signals it"
    )
    description: Optional[str] = Field(
        None, description="Extra detail beyond the title, if the user gave any"
    )
    related_event_id: Optional[str] = Field(
        None, description="UUID of an event this task belongs to (checklist item)"
    )
    parent_task_id: Optional[str] = Field(
        None, description="UUID of a parent task, if this is a sub-task/checklist item under another task"
    )


def _parse_due_date(value: Optional[str]) -> Optional[str]:
    """A due date is a day. Anything with a clock time in it is either a
    schedule in disguise or a guess, so take the date part only."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid due_date (expected YYYY-MM-DD): {exc}")


async def create_task_handler(args: dict, ctx: ToolContext) -> dict:
    """Create a task through the task.create command.

    Tasks are user-scoped, so the Command carries no workspace_id and
    CommandRegistry falls through to its ownership check — same shape as
    create_schedule.
    """
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    command = Command(
        command_name="task.create",
        args={
            "title": args["title"],
            "due_date": _parse_due_date(args.get("due_date")),
            "priority": args.get("priority"),
            "description": args.get("description"),
            "related_event_id": args.get("related_event_id"),
            "parent_task_id": args.get("parent_task_id"),
        },
        requested_by=ctx.user_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )

    result = await get_command_registry().execute(command, ctx)
    if not result.success:
        raise ValueError(result.error)

    data = {k: v for k, v in result.data.items() if k != "prev_state"}
    return {
        **data,
        "action_id": result.action_id,
        "revert_hint": "Bạn có thể hoàn tác việc vừa tạo bằng action_id trên.",
        "success": True,
    }


CREATE_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "What needs doing, in the user's own words",
        },
        "due_date": {
            "type": "string",
            "description": (
                "Day it must be done by, YYYY-MM-DD. **Extract it from what "
                "they said** — 'thứ 6 tôi phải gửi proposal' means due_date is "
                "this coming Friday. A date left in the title is invisible to "
                "every deadline calculation. Omit only when they genuinely "
                "gave no deadline; never invent one."
            ),
        },
        "priority": {
            "type": "string",
            "enum": ["low", "medium", "high", "urgent"],
            "description": (
                "Set only when the user signals urgency or importance explicitly "
                "('gấp', 'khẩn cấp', 'quan trọng') — never invent one. Omit for a "
                "plain task with no stated priority."
            ),
        },
        "description": {
            "type": "string",
            "description": "Extra detail beyond the title, if the user gave any",
        },
        "related_event_id": {
            "type": "string",
            "description": "UUID of the event this is a checklist item of",
        },
        "parent_task_id": {
            "type": "string",
            "description": "UUID of a parent task, if this is a sub-task under another task",
        },
    },
    "required": ["title"],
}

CREATE_TASK_DEFINITION = {
    "name": "create_task",
    "handler": create_task_handler,
    "input_model": CreateTaskInput,
    "schema": CREATE_TASK_SCHEMA,
    "description": (
        "Create a SINGLE task — something the user has to do by a deadline. Use this "
        "when the user says they need to do one specific thing ('thứ 6 tôi phải gửi "
        "proposal cho John', 'remind me to review the PR'). A task CONSUMES "
        "time; use create_schedule instead for anything that OCCUPIES a span "
        "of time, like a meeting. "
        "Do NOT use this for a milestone/checklist item that's part of a multi-phase "
        "plan you just proposed for a goal (\"tôi muốn học tiếng Anh\", \"tôi muốn giảm "
        "cân\", or anything broken into phases/milestones/checklist) — that whole plan "
        "must go through propose_plan instead, as one call, so the user reviews and "
        "approves every item before anything is created. Calling create_task repeatedly "
        "for a plan's items skips that review entirely."
    ),
}
