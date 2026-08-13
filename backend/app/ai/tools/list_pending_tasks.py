"""List pending tasks tool — read-only view over tasks awaiting confirmation.

Replaces the former `list_commitments` tool (Commitment folded into Task —
see "Xoá bỏ Commitment, gộp vào Task"). Gives the agent a way to find the
suggestion a user is replying about before calling confirm_task/reject_task,
without the old direction/counterparty framing.
"""

from pydantic import BaseModel

from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ListPendingTasksInput(BaseModel):
    pass


async def list_pending_tasks_handler(args: dict, ctx: ToolContext) -> dict:
    """Read-only, so it goes straight to the service rather than through
    CommandRegistry — there is no mutation to permission-check, audit or
    revert."""
    from app.models import TaskStatus
    from app.services.tasks import TaskService

    async with ctx.async_db() as db:
        tasks = await TaskService(db).get_tasks(ctx.user_id, status=TaskStatus.PENDING_CONFIRM)

        return {
            "tasks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                }
                for t in tasks
            ],
            "count": len(tasks),
            "success": True,
        }


LIST_PENDING_TASKS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}

LIST_PENDING_TASKS_DEFINITION = {
    "name": "list_pending_tasks",
    "handler": list_pending_tasks_handler,
    "input_model": ListPendingTasksInput,
    "schema": LIST_PENDING_TASKS_SCHEMA,
    "description": (
        "List tasks the extraction pipeline suggested that are still "
        "awaiting the user's yes/no. Use to find the task a user is "
        "answering about before calling confirm_task or reject_task."
    ),
}
