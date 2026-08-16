"""
"What should I do next?" — Milestone 3.5.

A single entry point over two signals that otherwise live in separate
services: 3.1's deterministic ranking (`TodayService`) and 6.8/4.4's
severity score (`risk_detection`). Bản 2 described the second half as
"3.4's pending re-plan proposal, sent through the Attention Gate as a
Recommend" — that delivery already happens on its own, the moment a task's
`compute_risk` score crosses the threshold (`task.at_risk`, published by
`StateEvaluator`, delivered by `notification_subscribers.handle_task_at_
risk`). Nothing in this codebase mutates a task's due date or priority on
the user's behalf without them asking, so this endpoint doesn't add a
second re-plan mechanism — it gives a caller (the agent, or a future
"Hôm nay" status line) one place to ask for both signals instead of
hitting `/today` and cross-referencing risk scores itself.

`at_risk` is additive to `now_actions`, not a competing ranking: 3.1 caps
`now_actions` at `MAX_NOW_ACTIONS`, so a severely at-risk task can still
miss the top-3 cut. This is the one place it stays visible regardless of
how many other overdue tasks are ranked above it.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas import NextActionAtRisk, NextActionResponse
from app.services.risk_detection import list_at_risk_tasks
from app.services.today import TodayService, _due_day, _plural_days, _today


class NextActionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._today_service = TodayService(session)

    async def get_next_action(self, user_id: UUID) -> NextActionResponse:
        today_response = await self._today_service.get_today(user_id)
        # Same bar `task.at_risk` uses to interrupt the user proactively
        # (settings.STATE_EVALUATOR_RISK_THRESHOLD) — not
        # `list_at_risk_tasks`'s own lower default, which is meant for a
        # generic "show me anything mildly late" query. "at_risk" here
        # should mean the same severity `at_risk` means everywhere else.
        at_risk_tasks = await list_at_risk_tasks(
            self.session, user_id, min_risk=settings.STATE_EVALUATOR_RISK_THRESHOLD
        )

        today = _today()
        at_risk = [
            NextActionAtRisk(
                task_id=task.id,
                title=task.title,
                risk_score=risk_score,
                impact=self._impact(task, today),
            )
            for task, risk_score in at_risk_tasks
        ]

        return NextActionResponse(
            state=today_response.state,
            now_actions=today_response.now_actions,
            suggestions=today_response.suggestions,
            needs_confirmation=today_response.needs_confirmation,
            at_risk=at_risk,
        )

    @staticmethod
    def _impact(task, today) -> str:
        overdue_days = (today - _due_day(task)).days
        return (
            f"Quá hạn {_plural_days(overdue_days)}, rủi ro đang tăng dần — "
            "cân nhắc dời hạn hoặc hạ ưu tiên việc khác để tập trung vào việc này."
        )
