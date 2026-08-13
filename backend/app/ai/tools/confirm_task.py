"""Confirm task tool — thin wrapper around the task.confirm command.

The user's "yes" to a suggested task. Replaces the former
`confirm_commitment` tool (Commitment folded into Task — see "Xoá bỏ
Commitment, gộp vào Task"): confirming used to also create a linked Task,
but here the task already *is* the task, so confirming just moves it from
`pending_confirm` to `todo`.
"""

from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConfirmTaskInput(BaseModel):
    task_id: str = Field(..., description="UUID of the suggested task to confirm")


async def confirm_task_handler(args: dict, ctx: ToolContext) -> dict:
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    command = Command(
        command_name="task.confirm",
        args={"task_id": args["task_id"]},
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
        "success": True,
    }


CONFIRM_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "UUID of the suggested task"},
    },
    "required": ["task_id"],
}

CONFIRM_TASK_DEFINITION = {
    "name": "confirm_task",
    "handler": confirm_task_handler,
    "input_model": ConfirmTaskInput,
    "schema": CONFIRM_TASK_SCHEMA,
    "description": (
        "Confirm a suggested task after the user says yes — moves it from "
        "pending_confirm to todo. Never confirm without the user's answer."
    ),
}
