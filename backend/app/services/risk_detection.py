"""
Risk score for a task — Milestone 6.8, rewritten after Goal was dropped
from the schema (see planning-v3.md's mục IX — Goal Progress Tracking is
dead, but the product question it served ("what's quietly at risk of
slipping") is still real).

Bản 2's Risk Detection scored a *goal* from its progress vs. time
remaining. That input no longer exists. The replacement stays on `Task`
alone: `priority × overdue_days × (1 + open_subtask_count)`.

- **priority** weights how much missing this particular thing costs.
- **overdue_days** is the actual signal — a task not yet due carries no
  risk under this formula, same as `state_evaluator`'s `task.blocked_cascade`
  only ever looks at overdue parents.
- **`1 + open_subtask_count`** is the cascade term, replacing "blocks goal
  progress": every unfinished subtask under a late parent is other work
  stuck behind it, so risk compounds instead of just adding. `+1` keeps a
  childless overdue task at its priority-weighted baseline instead of
  falling to zero — no subtasks doesn't mean no risk.

Deliberately a flat per-task score, not a dependency graph — the plan
explicitly rejected modelling this as one ("không vẽ thành graph"): a
grandparent task's risk doesn't recurse through its children's children
here, because nothing in the product surfaces multi-level cascades yet and
a graph nobody reads is just unverifiable complexity.

Scope: this computes the score. Turning it into something the Attention
Gate acts on is 4.4 ("chuyển công thức thành action"), a separate step —
see planning-v3.md's Khối D.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskPriority
from app.services.today import OPEN_STATUSES, _due_day, _today

# Never zero — an unset priority still carries baseline risk from being
# overdue at all, same reasoning `today.py`'s `_PRIORITY_WEIGHT` uses for
# ranking (there, unset ranks lowest but still present; here, unset must
# not multiply the whole score away).
_PRIORITY_WEIGHT: dict[TaskPriority | None, int] = {
    TaskPriority.URGENT: 4,
    TaskPriority.HIGH: 3,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 1,
    None: 1,
}


def compute_risk(
    priority: TaskPriority | None,
    overdue_days: int,
    open_subtask_count: int = 0,
) -> float:
    """The formula, pure and DB-free — the part worth unit-testing directly.

    `overdue_days <= 0` (not due yet, or due today) always scores 0: this
    formula answers "how much is this slipping", not "how important is
    this", and nothing has slipped yet.
    """
    if overdue_days <= 0:
        return 0.0
    return _PRIORITY_WEIGHT.get(priority, 1) * overdue_days * (1 + max(open_subtask_count, 0))


async def list_at_risk_tasks(
    session: AsyncSession,
    user_id: UUID,
    min_risk: float = 1.0,
) -> list[tuple[Task, float]]:
    """Open, overdue tasks for `user_id`, scored and sorted highest-risk
    first. `min_risk` filters out the barely-late — a LOW-priority task
    one day overdue with no subtasks scores 1 and is rarely worth
    surfacing; the default keeps everything above that floor.
    """
    today = _today()
    today_start = datetime.combine(today, time.min)

    overdue_result = await session.execute(
        select(Task).where(
            Task.user_id == user_id,
            Task.status.in_(OPEN_STATUSES),
            Task.due_date.isnot(None),
            Task.due_date < today_start,
        )
    )
    overdue = {t.id: t for t in overdue_result.scalars().all()}
    if not overdue:
        return []

    subtask_counts_result = await session.execute(
        select(Task.parent_task_id, func.count(Task.id))
        .where(
            Task.parent_task_id.in_(overdue),
            Task.status.in_(OPEN_STATUSES),
        )
        .group_by(Task.parent_task_id)
    )
    subtask_counts = dict(subtask_counts_result.all())

    scored: list[tuple[Task, float]] = []
    for task in overdue.values():
        overdue_days = (today - _due_day(task)).days
        risk = compute_risk(task.priority, overdue_days, subtask_counts.get(task.id, 0))
        if risk >= min_risk:
            scored.append((task, risk))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


# ============================================================================
# Project-level risk — DESIGN 7.1
# ============================================================================


def project_risk(
    deadline: datetime | None,
    tasks: Sequence[Task],
    open_subtask_counts: Mapping[UUID, int] | None = None,
    today: date | None = None,
) -> float:
    """How much trouble a whole project is in, on the same scale as a task.

    Reuses `compute_risk` rather than inventing a second formula: the worst
    task in a project *is* the project's floor, and multiplying by how close
    the deadline is expresses the one thing a per-task score can never
    say — that the same slippage costs more with five days left than with
    fifty.

        urgency = 1 + 2 / (1 + days_left)     # 1.0 khi còn xa, 3.0 khi tới hạn

    **`deadline is None` returns 0.0, and that is load-bearing.** Dự án cá
    nhân không bao giờ có deadline (DESIGN 3.4), nên mọi việc lẻ nhận điểm
    0 ở tầng một và giữ nguyên thứ tự cũ ở tầng hai. Không có nhánh này thì
    việc lẻ và việc dự án trộn vào nhau, và hành vi hiện tại của màn Hôm nay
    đổi cho những người chưa có dự án nào — chính là điều 7.1 cấm.

    Thuần và không chạm DB, cùng lý do `compute_risk` là: thứ đáng test
    trực tiếp là công thức, không phải cách lấy dữ liệu cho nó.
    """
    if deadline is None:
        return 0.0

    day = today or _today()
    counts = open_subtask_counts or {}

    base = max(
        (
            compute_risk(
                task.priority,
                (day - _due_day(task)).days if _due_day(task) else 0,
                counts.get(task.id, 0),
            )
            for task in tasks
        ),
        default=0.0,
    )
    if base == 0.0:
        # Chưa có việc nào trượt thì dự án chưa trượt — nhân với urgency ở
        # đây chỉ biến 0 thành 0, nhưng viết rõ ra để không ai đọc nhầm
        # rằng deadline gần tự nó là rủi ro.
        return 0.0

    days_left = max((deadline.date() - day).days, 0)
    urgency = 1.0 + 2.0 / (1.0 + days_left)
    return base * urgency
