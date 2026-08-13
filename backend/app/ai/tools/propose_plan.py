"""Propose plan tool — thin wrapper around the plan.propose command (which
creates a reviewable proposal instead of creating tasks/schedules directly).

3.2 AI Planner: once a conversation has clarified scope/deadline/constraints
for a vague want ("tôi muốn học tiếng Anh"), this is how the `planning`
skill turns that into concrete Task/Event items — as a PROPOSAL the user
must approve in the UI, not as immediate create_task/create_schedule calls.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PlanItemRecurrenceInput(BaseModel):
    """Same shape as create_schedule's recurrence_rule — a repeating event
    item should carry ONE of these, not be proposed as N one-off events."""
    freq: str = Field(..., pattern="^(NONE|DAILY|WEEKLY|MONTHLY)$", description="Frequency: NONE, DAILY, WEEKLY, MONTHLY")
    interval: int = Field(default=1, ge=1, le=365, description="Repeat every N days/weeks/months")
    until: Optional[str] = Field(None, description="ISO 8601 datetime (stop recurrence on this date)")
    count: Optional[int] = Field(None, ge=1, le=730, description="Number of occurrences")
    tzid: str = Field(default="Asia/Ho_Chi_Minh", description="Timezone ID")


class PlanItemInput(BaseModel):
    key: str = Field(..., min_length=1, max_length=50, description="Local id you invent for this item, e.g. 't1' — used only by parent_key/related_event_key within this same call")
    type: Literal["task", "event"]
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None

    # Task-only
    due_date: Optional[str] = Field(None, description="YYYY-MM-DD, task items only")
    priority: Optional[str] = Field(None, description="low, medium, high, or urgent — task items only")
    parent_key: Optional[str] = Field(None, description="key of an earlier TASK item in this same call, to nest this as its sub-task")
    related_event_key: Optional[str] = Field(None, description="key of an EVENT item in this same call this task is a checklist item of — task items only")

    # Event-only
    start_time: Optional[str] = Field(None, description="ISO datetime, event items only")
    end_time: Optional[str] = Field(None, description="ISO datetime, event items only")
    location: Optional[str] = Field(None, description="event items only")
    recurrence: Optional[PlanItemRecurrenceInput] = Field(None, description="Set this instead of proposing multiple one-off events for something that repeats — event items only")


class ProposePlanInput(BaseModel):
    items: list[PlanItemInput] = Field(..., min_length=1, max_length=50)


async def propose_plan_handler(args: dict, ctx: ToolContext) -> dict:
    """Create a plan proposal through the plan.propose command.

    Does NOT create any Task/Schedule — returns a proposal_id the user
    reviews and approves (or edits/rejects) in the UI. Never call
    create_task/create_schedule directly as a substitute for this when
    proposing a multi-item plan; that would skip the review step entirely.
    """
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    command = Command(
        command_name="plan.propose",
        args={"items": args["items"]},
        requested_by=ctx.user_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )

    result = await get_command_registry().execute(command, ctx)
    if not result.success:
        raise ValueError(result.error)

    return {**result.data, "success": True}


PROPOSE_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": (
                "The full plan, as a flat list of task/event items. Call this tool "
                "ONCE with everything — phases/milestones as task items, checklist "
                "steps as task items with parent_key pointing at their milestone, "
                "recurring practice/study blocks as event items WITH a recurrence "
                "rule (never as several separate one-off events for the same repeating "
                "block — a WEEKLY recurrence with an until/count is one event item, not five). "
                "Nothing is created until the user approves in the UI."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Local id you invent, e.g. 't1' (never a real UUID)"},
                    "type": {"type": "string", "enum": ["task", "event"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "due_date": {"type": "string", "description": "YYYY-MM-DD — task items only"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "task items only"},
                    "parent_key": {"type": "string", "description": "key of an earlier task item, to nest this under it — task items only"},
                    "related_event_key": {
                        "type": "string",
                        "description": (
                            "key of an event item in this same call — use this when a task IS the "
                            "checklist for a specific recurring session (e.g. \"10 từ mới\" belongs to "
                            "the daily practice event), instead of parent_key. Task items only."
                        ),
                    },
                    "start_time": {"type": "string", "description": "ISO datetime — event items only"},
                    "end_time": {"type": "string", "description": "ISO datetime — event items only"},
                    "location": {"type": "string", "description": "event items only"},
                    "recurrence": {
                        "type": "object",
                        "description": (
                            "Repeat rule for this event — event items only. Use this for ANY block "
                            "that repeats (daily practice, weekly review); don't emit multiple event "
                            "items with different dates for the same repeating thing."
                        ),
                        "properties": {
                            "freq": {"type": "string", "enum": ["NONE", "DAILY", "WEEKLY", "MONTHLY"]},
                            "interval": {"type": "integer", "minimum": 1, "maximum": 365, "default": 1, "description": "Repeat every N days/weeks/months"},
                            "until": {"type": "string", "description": "ISO datetime when recurrence stops"},
                            "count": {"type": "integer", "minimum": 1, "maximum": 730, "description": "Number of occurrences (alternative to until)"},
                            "tzid": {"type": "string", "default": "Asia/Ho_Chi_Minh"},
                        },
                        "required": ["freq"],
                    },
                },
                "required": ["key", "type", "title"],
            },
        },
    },
    "required": ["items"],
}

PROPOSE_PLAN_DEFINITION = {
    "name": "propose_plan",
    "handler": propose_plan_handler,
    "input_model": ProposePlanInput,
    "schema": PROPOSE_PLAN_SCHEMA,
    "description": (
        "Propose a structured multi-item plan (tasks + events) for the user to review and "
        "approve — use this once scope/deadline/constraints are clear, instead of calling "
        "create_task/create_schedule directly. Nothing is created until the user approves; "
        "the UI shows each item for review/edit first. `key` is a short local id you invent "
        "per item; set `parent_key` on a task item to nest it under an earlier task item in "
        "the SAME call (e.g. a checklist step under its milestone). A block that repeats "
        "(daily practice, weekly review) is ONE event item with a `recurrence` rule, never "
        "several one-off event items — this tool has no follow-up step, so anything not set "
        "here (recurrence, event linkage) never gets added later. A checklist task tied to a "
        "specific recurring session uses `related_event_key`, not `parent_key`."
    ),
}
