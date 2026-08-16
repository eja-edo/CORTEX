"""Get today's ranked actions tool — the agent's window onto `NextActionService`
(Milestone 3.1 M4, extended to include 3.5's `at_risk` signal).

Before this tool existed the agent had no way to ask "what should the user
do today" except reasoning it out itself from whatever tasks it happened to
have loaded — re-deriving, in natural language and per-conversation, the
same overdue/priority/due-date ranking `TodayService._rank_actions` already
computes deterministically and consistently for the "Hôm nay" screen. That
duplication is the actual bug: the agent's answer could silently disagree
with what the screen shows. This tool removes the reason to guess.

Calls `NextActionService` rather than `TodayService` directly (3.5 M2: "AI
skill dùng endpoint này thay vì gọi rời rạc nhiều tool") — one tool call
gets both the ranking and the risk signal instead of the agent needing a
second tool to ask "is anything at risk of slipping further". `state`/
`now_actions`/`suggestions`/`needs_confirmation` are unchanged from before;
`at_risk` is additive.

Read-only, so — like `list_pending_tasks` — it calls the service directly
rather than going through `CommandRegistry`: there is no mutation to
permission-check, audit or revert.
"""

from pydantic import BaseModel

from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GetTodayInput(BaseModel):
    pass


async def get_today_handler(args: dict, ctx: ToolContext) -> dict:
    from app.services.next_action import NextActionService

    async with ctx.async_db() as db:
        next_action = await NextActionService(db).get_next_action(ctx.user_id)

        return {
            "state": next_action.state,
            "now_actions": [
                {
                    "task_id": str(a.task_id),
                    "title": a.title,
                    "reason": a.reason.impact,
                    "due_date": a.due_date.isoformat() if a.due_date else None,
                }
                for a in next_action.now_actions
            ],
            "suggestions": [
                {
                    "task_id": str(a.task_id),
                    "title": a.title,
                    "reason": a.reason.impact,
                    "due_date": a.due_date.isoformat() if a.due_date else None,
                }
                for a in next_action.suggestions
            ],
            "needs_confirmation": [
                {
                    "task_id": str(c.task_id),
                    "title": c.title,
                    "due_date": c.due_date.isoformat() if c.due_date else None,
                }
                for c in next_action.needs_confirmation
            ],
            "at_risk": [
                {
                    "task_id": str(r.task_id),
                    "title": r.title,
                    "risk_score": r.risk_score,
                    "reason": r.impact,
                }
                for r in next_action.at_risk
            ],
            "success": True,
        }


GET_TODAY_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}

GET_TODAY_DEFINITION = {
    "name": "get_today",
    "handler": get_today_handler,
    "input_model": GetTodayInput,
    "schema": GET_TODAY_SCHEMA,
    "description": (
        "Get the user's ranked list of what to do today — the same "
        "deterministic ordering (overdue, priority, due date) the 'Hôm nay' "
        "screen shows, each with the reason it's being suggested. Use this "
        "instead of inferring priority yourself from a list of tasks — the "
        "ranking is a product answer, not a judgement call the agent should "
        "make on its own. `now_actions` is what to surface as urgent, "
        "`suggestions` is lower-stakes work to offer only when nothing is "
        "urgent, `needs_confirmation` is extraction candidates still "
        "awaiting a yes/no, `at_risk` is tasks whose combined priority, "
        "lateness, and blocked subtasks make them worth flagging even if "
        "they didn't make the top of `now_actions` — mention these when "
        "suggesting the user reschedule or reprioritize."
    ),
}
