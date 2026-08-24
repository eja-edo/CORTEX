"""
The "Hôm nay" screen's data (Milestone 2.7).

This is the product's main surface, and it answers four questions: where am
I, what should I do, did I miss anything, what can Cortex do about it.

Two rules shape everything here:

**It serves decisions, not numbers.** "progress 33%" is a number the user has
to interpret; "MVP còn 12 ngày, đang chậm 2 ngày" is a conclusion they can
act on. Progress still exists as an internal metric (2.2) — it just doesn't
reach this screen as a percentage.

**Every suggested action carries its reason, and the reason states impact.**
"priority: high" is a label; "Quá hạn 3 ngày — MVP còn 12 ngày và còn 4 việc
chưa xong" is a consequence. The reason is composed here rather than in the
client, because it is the product's actual output; a client that formatted
its own sentence could show one that isn't true.

Scope note: this is not the ranking engine. 3.1 owns real prioritisation
(and 3.3 the free-slot half of the status line). What's here is a
deterministic, explainable ordering over the facts Phase 2 actually has —
deadlines, a user-set priority, task suggestions awaiting confirmation —
with no scoring model and nothing inferred.
"""

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Task,
    TaskPriority,
    TaskStatus,
)
from app.schemas import (
    TodayNeedsConfirmationItem,
    TodayNowAction,
    TodayReason,
    TodayResponse,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How many cards the screen offers at once. Deliberately small: the point of
# a single attention surface is that it forces ranking (design decision 3).
# A list of twenty "you should do this" cards is a backlog, not a decision.
MAX_NOW_ACTIONS = 3

# For the "nothing urgent" state — things the user *could* pick up. Never
# presented as urgent, and never padded out to look like work.
MAX_SUGGESTIONS = 2

OPEN_STATUSES = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)

# Higher wins ties among tasks with the same overdue/due-date standing.
# Unset (None) ranks below every explicit value — it is not the same as LOW.
_PRIORITY_WEIGHT: dict[TaskPriority | None, int] = {
    TaskPriority.URGENT: 3,
    TaskPriority.HIGH: 2,
    TaskPriority.MEDIUM: 1,
    TaskPriority.LOW: 0,
    None: -1,
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _due_day(task: Task) -> date | None:
    """The calendar day a task is due, ignoring any time-of-day it carries.

    Ranking and "overdue"/"due today" reasoning stay day-granular even
    though `due_date` can now hold a real time (2.6's event checklist) —
    a task due at 23:00 today is "due today", not "overdue in -9 hours".
    """
    return task.due_date.date() if task.due_date else None


def _plural_days(count: int) -> str:
    return f"{count} ngày"


class TodayService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def get_today(self, user_id: UUID) -> TodayResponse:
        open_tasks = await self._open_tasks(user_id)
        pending_tasks = await self._pending_confirmation_tasks(user_id)

        actions = self._rank_actions(open_tasks)
        now_actions = actions[:MAX_NOW_ACTIONS]

        needs_confirmation = self._build_needs_confirmation(pending_tasks)

        state = self._screen_state(
            has_any_task=await self._has_any_task(user_id),
            has_open_work=bool(open_tasks),
            has_now_actions=bool(now_actions),
        )

        suggestions: list[TodayNowAction] = []
        if state == "nothing_urgent":
            # Things they *could* start — offered, never dressed up as
            # urgent. Inventing urgency to fill the screen is the one thing
            # this state must not do.
            suggestions = self._suggestions(open_tasks)

        return TodayResponse(
            state=state,
            status_line=None,
            now_actions=now_actions,
            suggestions=suggestions,
            needs_confirmation=needs_confirmation,
        )

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def _open_tasks(self, user_id: UUID) -> list[Task]:
        # `recurrence_id.is_(None)` excludes occurrence-exception rows (a
        # recurring event's checklist task, overridden for one occurrence —
        # see `Task.recurrence_id`): those are resolved per-occurrence by
        # `CalendarItemService.get_event_checklist`, not ranked here as if
        # they were independent top-level tasks.
        stmt = (
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.status.in_(OPEN_STATUSES),
                Task.recurrence_id.is_(None),
            )
            .order_by(Task.due_date.asc().nullslast(), Task.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _pending_confirmation_tasks(self, user_id: UUID) -> list[Task]:
        """`pending_confirm` only — a suggestion the extraction pipeline
        made that the user hasn't answered yet. Kept off `now_actions`
        (`_open_tasks` below never includes this status): an unconfirmed
        guess hasn't earned a place among validated, ranked work."""
        stmt = (
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.status == TaskStatus.PENDING_CONFIRM,
                Task.recurrence_id.is_(None),
            )
            .order_by(Task.due_date.asc().nullslast(), Task.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # Ranking + reasons
    # ------------------------------------------------------------------

    def _rank_actions(self, tasks: list[Task]) -> list[TodayNowAction]:
        """Order by how much it costs to not do the thing today.

        Deterministic and explainable by construction: the sort key is the
        same fact the reason sentence quotes, so the order can always be
        justified by what the card already says.
        """
        scored: list[tuple[tuple, TodayNowAction]] = []
        today = _today()

        for task in tasks:
            reason = self._reason_for(task, today)
            if reason is None:
                # No honest reason to raise it today. Silence is a valid
                # answer here, exactly as it is for the Attention Gate.
                continue

            due_day = _due_day(task)
            overdue_days = (today - due_day).days if due_day and due_day < today else 0
            days_to_due = (due_day - today).days if due_day else 9_999

            # Most overdue first, then higher priority, then soonest due.
            sort_key = (-overdue_days, -_PRIORITY_WEIGHT[task.priority], days_to_due)
            scored.append((sort_key, self._to_action(task, reason)))

        scored.sort(key=lambda pair: pair[0])
        return [action for _, action in scored]

    def _reason_for(self, task: Task, today: date) -> TodayReason | None:
        """Why this task, today — as a consequence, never as a label.

        Returns None when nothing true can be said, which is what keeps the
        screen from manufacturing urgency.
        """
        due_day = _due_day(task)

        if due_day and due_day < today:
            overdue = (today - due_day).days
            impact = f"Quá hạn {_plural_days(overdue)}. Càng để lâu càng khó bắt đầu lại."
            return TodayReason(key="task.overdue", impact=impact)

        if due_day == today:
            return TodayReason(key="task.due_today", impact="Hạn hôm nay — hết hôm nay là trễ.")

        if task.priority in (TaskPriority.URGENT, TaskPriority.HIGH):
            impact = (
                "Được đánh dấu khẩn cấp."
                if task.priority is TaskPriority.URGENT
                else "Được đánh dấu ưu tiên cao."
            )
            return TodayReason(key="task.high_priority", impact=impact)

        if due_day and (due_day - today).days <= 2:
            days = (due_day - today).days
            when = "ngày mai" if days == 1 else f"sau {_plural_days(days)}"
            return TodayReason(
                key="task.due_soon",
                impact=f"Hạn {when} — làm hôm nay thì vẫn kịp thong thả.",
            )

        return None

    def _to_action(self, task: Task, reason: TodayReason) -> TodayNowAction:
        return TodayNowAction(
            task_id=task.id,
            title=task.title,
            reason=reason,
            due_date=task.due_date,
            priority=task.priority,
        )

    def _suggestions(self, tasks: list[Task]) -> list[TodayNowAction]:
        """Things worth starting when nothing is pressing.

        Framed as an option, not a deadline — the reason says "chưa gấp"
        explicitly so the card can't read as manufactured urgency. Ordered
        by priority so a marked-important-but-undated task still surfaces
        first among equals.
        """
        today = _today()
        candidates = sorted(
            (t for t in tasks if not t.due_date or _due_day(t) > today),
            key=lambda t: -_PRIORITY_WEIGHT[t.priority],
        )
        picked: list[TodayNowAction] = []

        for task in candidates[:MAX_SUGGESTIONS]:
            impact = "Chưa gấp — nhưng đang rảnh thì đây là việc dễ bắt đầu."
            picked.append(
                self._to_action(task, TodayReason(key="task.could_start", impact=impact))
            )
        return picked

    # ------------------------------------------------------------------
    # Needs confirmation
    # ------------------------------------------------------------------

    def _build_needs_confirmation(self, tasks: list[Task]) -> list[TodayNeedsConfirmationItem]:
        """Suggestions from conversation extraction, waiting on a yes/no.

        Replaces the former "Đang chờ" (`_build_waiting`) — that section
        existed to show commitments; now that a chat-extracted suggestion
        *is* a task, this is just "what's still unconfirmed", not a second
        product concept.
        """
        return [
            TodayNeedsConfirmationItem(task_id=task.id, title=task.title, due_date=task.due_date)
            for task in tasks
        ]

    async def _has_any_task(self, user_id: UUID) -> bool:
        """Any task at all, in any status and attached to anything."""
        stmt = select(func.count()).select_from(Task).where(Task.user_id == user_id)
        return bool((await self.session.execute(stmt)).scalar_one())

    def _screen_state(
        self,
        has_any_task: bool,
        has_open_work: bool,
        has_now_actions: bool,
    ) -> str:
        """Which design the screen shows.

        Decided here rather than in the client so the screen can't end up
        showing a default empty table — each state has its own design, and
        the server says which one it is.

        No separate "only unconfirmed suggestions" branch: `has_any_task`
        (via `_has_any_task`, unfiltered by status) is already true for a
        user who has nothing but `pending_confirm` tasks, so they land on
        `all_clear` same as anyone whose real work is done — correct, since
        nothing here is *actionable* yet. `needs_confirmation` still carries
        the suggestions themselves regardless of which state this returns.
        """
        if not has_any_task:
            return "onboarding"        # nothing has ever existed
        if has_open_work:
            return "has_actions" if has_now_actions else "nothing_urgent"
        return "all_clear"             # there was work, and it is finished
