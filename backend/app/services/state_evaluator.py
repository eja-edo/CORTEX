"""State Evaluator (Milestone 4.6, predicates expanded in A1).

Turns state that changes with the clock, not with a write, into an event on
the Event Bus — "task overdue 3 days" isn't something that *happened*, so
nothing publishes it from a mutation (see the comment in
app.events.payloads next to TaskOverduePayload). Something has to go ask.

A1 grows this from the original single predicate (`task.overdue`) to six:
`task.overdue`, `task.due_soon`, `task.stale`, `task.blocked_cascade`,
`schedule.starts_soon`, `day.review`. See `docs/planning-v3.md` section
VI/A1 for why each one exists — the short version is Detection had almost
nothing for the Attention Gate to gate, so this is where content comes
from before more Delivery machinery gets built.

`task.at_risk` (6.8/4.4) is a seventh, added later: `risk_detection.
compute_risk` scores every overdue task, and this publishes when that
score crosses `settings.STATE_EVALUATOR_RISK_THRESHOLD` — an escalation
layered on top of `task.overdue`, not a new independent condition (see
that predicate's own docstring).

`goal.at_risk`/`commitment.*` from the old planning doc's example set
still don't exist as their own predicates: neither Goal nor Commitment is
a model in this codebase (Task absorbed both — see Task's own docstring in
app.models). `task.blocked_cascade` is A1's replacement for "goal
blocked" — same idea, expressed through `parent_task_id` instead.

"Overdue" itself is not redefined here — it reuses the day-granular,
UTC definition already live in app.services.today (`_today`/`_due_day`,
the "Hôm nay" screen), including the precedent that `"task.overdue"` is
already the reason key `today.py` uses for the same condition.

Idempotency: one `StateEvaluatorFlag` row per (item, flag_key) means "this
condition is currently true for this item". Each tick computes the current
set for each predicate and diffs it against existing flags — new members
publish + get a flag row, members that dropped out get their flag row
deleted. That's what makes a *second* transition into the same condition
(resolved, then true again) publish again instead of being suppressed
forever. `day.review` uses the same mechanism for a per-user condition
instead of a per-item one — see `_evaluate_day_review`'s own docstring.
"""

import asyncio
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database_async import make_async_sessionmaker
from app.events.event_bus import get_event_bus
from app.events.payloads import (
    DayPlanPayload,
    ProjectSlippingPayload,
    ProjectWillMissPayload,
    DayReviewPayload,
    ScheduleDigestItem,
    ScheduleStartsSoonPayload,
    TaskAtRiskPayload,
    TaskBlockedCascadePayload,
    TaskDigestItem,
    TaskDueSoonPayload,
    TaskOverduePayload,
    TaskStalePayload,
)
from app.events.schemas import EventEnvelope
from app.models import (
    AttentionItemType,
    Project,
    ProjectOrigin,
    ProjectSnapshot,
    ProjectStatus,
    Schedule,
    StateEvaluatorFlag,
    Task,
    TaskPriority,
    TaskStatus,
)
from app.services.risk_detection import compute_risk
from app.services.today import OPEN_STATUSES, _due_day, _today
from app.utils.logger import get_logger

logger = get_logger(__name__)

OVERDUE_FLAG_KEY = "overdue"
DUE_SOON_FLAG_KEY = "due_soon"
STALE_FLAG_KEY = "stale"
BLOCKED_CASCADE_FLAG_KEY = "blocked_cascade"
STARTS_SOON_FLAG_KEY = "starts_soon"
DAY_REVIEW_FLAG_KEY = "day_review"
DAY_PLAN_FLAG_KEY = "day_plan"
AT_RISK_FLAG_KEY = "at_risk"
PROJECT_SLIPPING_FLAG_KEY = "project_slipping"
PROJECT_WILL_MISS_FLAG_KEY = "project_will_miss"
# Cờ trung gian của bộ chống rung ở `_publish_will_miss` — "đã vượt ngưỡng
# một lần", chưa phát. Là một `flag_key` riêng chứ không phải cột thêm nên
# nó thừa hưởng nguyên bộ diff/idempotency đã có.
PROJECT_WILL_MISS_PENDING_FLAG_KEY = "project_will_miss_pending"

# Chân trời của `project.slipping` (DESIGN 6.1): xa hơn thế thì việc mở tăng
# là chuyện bình thường của một dự án đang chạy, không phải tín hiệu trượt.
PROJECT_SLIPPING_HORIZON_DAYS = 14
# Cửa sổ tính tốc độ của `project.will_miss` (DESIGN 6.2). Hệ quả đã biết và
# chấp nhận: dự án mới im trong hai tuần đầu vì chưa có dữ liệu tốc độ.
PROJECT_VELOCITY_WINDOW_DAYS = 14

# The two per-user daily digests reset by calendar day rather than by their
# condition going false — see `_clear_stale_daily_flags`.
DAILY_FLAG_KEYS = (DAY_REVIEW_FLAG_KEY, DAY_PLAN_FLAG_KEY)

# How many items a digest event carries. The notification only prints
# `notification_format.MAX_LISTED_ITEMS` of them, but the event is also read
# by workflow_service, so it carries a little more than one renderer needs.
MAX_DIGEST_ITEMS = 10


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _rank_key(task: Task, today) -> tuple:
    """Ordering for digest lists: soonest deadline first, then higher
    priority. Matches how `today.py` ranks the "Hôm nay" screen — a digest
    that ordered by primary key would bury the thing that matters."""
    due_day = _due_day(task)
    return (
        due_day if due_day is not None else today + timedelta(days=3650),
        -_PRIORITY_RANK.get(task.priority, -1),
        task.title or "",
    )


_PRIORITY_RANK: dict = {
    TaskPriority.URGENT: 3,
    TaskPriority.HIGH: 2,
    TaskPriority.MEDIUM: 1,
    TaskPriority.LOW: 0,
    None: -1,
}


def _task_item(task: Task) -> TaskDigestItem:
    return TaskDigestItem(
        task_id=task.id,
        title=task.title,
        due_date=task.due_date,
        priority=task.priority.value if task.priority else None,
    )


def _schedule_item(schedule: Schedule) -> ScheduleDigestItem:
    return ScheduleDigestItem(
        schedule_id=schedule.id,
        title=schedule.title,
        start_time=schedule.start_time,
        location=schedule.location,
    )


class StateEvaluator:
    """Background worker that polls for state-derived conditions and
    publishes the corresponding event, exactly once per transition."""

    POLL_INTERVAL_SECONDS = 300

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._db_engine = None
        self._session_maker = None
        self._event_bus = None

    async def _get_event_bus(self):
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus

    async def start(self):
        # Per-worker async DB engine, same reasoning as ReminderWorker
        # (app/services/reminder_worker.py): bound to this worker thread's
        # own event loop, not the FastAPI request loop.
        self._db_engine, self._session_maker = make_async_sessionmaker()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("StateEvaluator started with poll interval=%ds", self.POLL_INTERVAL_SECONDS)
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("StateEvaluator: task cancelled during shutdown")
            raise
        finally:
            # Runs inside the same task run_until_complete is awaiting, so
            # cleanup is guaranteed to finish before WorkerThread closes the
            # loop — see WorkerThread._run()/stop() in app/__init__.py for
            # why doing this from stop() instead used to race the shutdown.
            await self._cleanup()

    async def stop(self):
        """Signal the evaluator to stop. Cleanup runs in start()'s finally
        block, not here — see the comment there."""
        self._running = False
        logger.info("StateEvaluator stopping...")
        if self._task and not self._task.done():
            self._task.cancel()

    async def _cleanup(self):
        if self._db_engine is not None:
            try:
                await self._db_engine.dispose()
            except Exception as exc:
                logger.warning("StateEvaluator: DB engine dispose failed: %s", exc)
            self._db_engine = None
            self._session_maker = None

    async def _run_loop(self):
        # Each predicate runs independently — one raising must not stop the
        # others from being evaluated this tick, and must not stall the
        # tick forever.
        #
        # **Order is load-bearing for the first three.** `task.at_risk` and
        # `task.blocked_cascade` are strict subsets of `task.overdue`, so a
        # late, risky task with open subtasks satisfies all three on the
        # same tick. The Gate collapses them via
        # `attention_reason_catalog.SUPERSEDES`, but it can only do that by
        # looking *backwards* at what already reached the user — so the
        # strongest reason has to go first, or the user gets the weak
        # version before the strong one has had a chance to suppress it.
        # `test_state_evaluator.py` pins this ordering.
        evaluators = (
            self._evaluate_task_at_risk,
            self._evaluate_task_blocked_cascade,
            self._evaluate_task_overdue,
            self._evaluate_task_due_soon,
            self._evaluate_task_stale,
            self._evaluate_schedule_starts_soon,
            self._evaluate_day_plan,
            self._evaluate_day_review,
            # Sau cùng: hai predicate này đọc `tasks` của cả dự án, nên chạy
            # sau khi các predicate cấp task đã ổn định trong cùng một tick
            # giữ cho số liệu chúng phát ra khớp với thứ vừa được nhắc.
            self._evaluate_projects,
        )
        try:
            while self._running:
                for evaluate in evaluators:
                    try:
                        await evaluate()
                    except Exception as e:
                        logger.exception("Error in state evaluator loop (%s): %s", evaluate.__name__, e)

                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("StateEvaluator: run loop cancelled, exiting cleanly")
            raise

    # ------------------------------------------------------------------
    # Shared flag-diffing helper
    # ------------------------------------------------------------------

    async def _diff_flags(
        self,
        db: AsyncSession,
        *,
        item_type: AttentionItemType,
        flag_key: str,
        current_ids: set[UUID],
        user_id_by_item: dict[UUID, UUID],
    ) -> tuple[set[UUID], set[UUID]]:
        """Compares `current_ids` (items where the condition holds right
        now) against existing flag rows for `(item_type, flag_key)`.
        Creates/deletes flag rows to match, commits, and returns
        `(to_publish, to_clear)` item ids. Shared by every predicate below
        so the idempotency rule (see module docstring) only lives once."""
        existing_result = await db.execute(
            select(StateEvaluatorFlag).where(
                StateEvaluatorFlag.item_type == item_type,
                StateEvaluatorFlag.flag_key == flag_key,
            )
        )
        existing_flags = {f.item_id: f for f in existing_result.scalars().all()}

        to_publish = current_ids - set(existing_flags)
        to_clear = set(existing_flags) - current_ids

        for item_id in to_clear:
            await db.delete(existing_flags[item_id])

        for item_id in to_publish:
            db.add(StateEvaluatorFlag(
                user_id=user_id_by_item[item_id],
                item_type=item_type,
                item_id=item_id,
                flag_key=flag_key,
            ))

        await db.commit()
        return to_publish, to_clear

    async def _clear_stale_daily_flags(self, db: AsyncSession, flag_key: str, today_start: datetime) -> None:
        """Drop yesterday's flag rows for a once-a-day digest.

        `day.review` relied purely on its condition going false to reset:
        the hour drops back below the threshold after midnight UTC, the
        flag clears, and the next crossing publishes again. That works, but
        only if the evaluator happens to be running during the window where
        the condition is false — for `day.review` (hour 14) that window is
        fourteen hours, for `day.plan` (hour 1) it is one. A restart across
        that hour would leave the flag set and the user would silently get
        no plan the next day, or any day after.

        Clearing by calendar day instead makes the reset independent of
        uptime: a flag first detected before today is stale by definition,
        because these conditions are evaluated once per day.
        """
        stale = await db.execute(
            select(StateEvaluatorFlag).where(
                StateEvaluatorFlag.flag_key == flag_key,
                StateEvaluatorFlag.first_detected_at < today_start,
            )
        )
        rows = list(stale.scalars().all())
        for row in rows:
            await db.delete(row)
        if rows:
            await db.commit()
            logger.info("Cleared %d stale %r flag(s) from a previous day", len(rows), flag_key)

    # ------------------------------------------------------------------
    # task.overdue
    # ------------------------------------------------------------------

    async def _evaluate_task_overdue(self):
        async with self._session_maker() as db:
            today = _today()
            today_start = datetime.combine(today, time.min)

            overdue_tasks_result = await db.execute(
                select(Task).where(
                    Task.status.in_(OPEN_STATUSES),
                    Task.due_date.isnot(None),
                    Task.due_date < today_start,
                )
            )
            overdue_tasks = {t.id: t for t in overdue_tasks_result.scalars().all()}

            to_publish, _ = await self._diff_flags(
                db,
                item_type=AttentionItemType.TASK,
                flag_key=OVERDUE_FLAG_KEY,
                current_ids=set(overdue_tasks),
                user_id_by_item={tid: t.user_id for tid, t in overdue_tasks.items()},
            )

            for task_id in to_publish:
                await self._publish_task_overdue(overdue_tasks[task_id], today)

    async def _publish_task_overdue(self, task: Task, today) -> None:
        try:
            due_day = _due_day(task)
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="task.overdue",
                source="StateEvaluator",
                user_id=task.user_id,
                payload=TaskOverduePayload(
                    task_id=task.id,
                    title=task.title,
                    due_date=task.due_date,
                    priority=task.priority.value if task.priority else None,
                    overdue_days=(today - due_day).days,
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish task.overdue event for task {task.id}: {exc}")

    # ------------------------------------------------------------------
    # task.due_soon — hạn trong ≤N giờ, chưa in_progress
    # ------------------------------------------------------------------

    async def _evaluate_task_due_soon(self):
        async with self._session_maker() as db:
            now = _utcnow().replace(tzinfo=None)
            horizon = now + timedelta(hours=settings.STATE_EVALUATOR_DUE_SOON_HOURS)

            result = await db.execute(
                select(Task).where(
                    # Only TODO, not IN_PROGRESS — a task already being
                    # worked on doesn't need a "starting soon" nudge.
                    Task.status == TaskStatus.TODO,
                    Task.due_date.isnot(None),
                    Task.due_date > now,
                    Task.due_date <= horizon,
                )
            )
            due_soon_tasks = {t.id: t for t in result.scalars().all()}

            to_publish, _ = await self._diff_flags(
                db,
                item_type=AttentionItemType.TASK,
                flag_key=DUE_SOON_FLAG_KEY,
                current_ids=set(due_soon_tasks),
                user_id_by_item={tid: t.user_id for tid, t in due_soon_tasks.items()},
            )

            for task_id in to_publish:
                await self._publish_task_due_soon(due_soon_tasks[task_id], now)

    async def _publish_task_due_soon(self, task: Task, now: datetime) -> None:
        try:
            hours_until_due = max(0, int((task.due_date - now).total_seconds() // 3600))
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="task.due_soon",
                source="StateEvaluator",
                user_id=task.user_id,
                payload=TaskDueSoonPayload(
                    task_id=task.id,
                    title=task.title,
                    due_date=task.due_date,
                    priority=task.priority.value if task.priority else None,
                    hours_until_due=hours_until_due,
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish task.due_soon event for task {task.id}: {exc}")

    # ------------------------------------------------------------------
    # task.stale — tạo/động >N ngày, không hạn
    # ------------------------------------------------------------------

    async def _evaluate_task_stale(self):
        async with self._session_maker() as db:
            now = _utcnow().replace(tzinfo=None)
            cutoff = now - timedelta(days=settings.STATE_EVALUATOR_STALE_DAYS)

            result = await db.execute(
                select(Task).where(
                    Task.status.in_(OPEN_STATUSES),
                    Task.due_date.is_(None),
                    Task.updated_at < cutoff,
                )
            )
            stale_tasks = {t.id: t for t in result.scalars().all()}

            to_publish, _ = await self._diff_flags(
                db,
                item_type=AttentionItemType.TASK,
                flag_key=STALE_FLAG_KEY,
                current_ids=set(stale_tasks),
                user_id_by_item={tid: t.user_id for tid, t in stale_tasks.items()},
            )

            for task_id in to_publish:
                await self._publish_task_stale(stale_tasks[task_id], now)

    async def _publish_task_stale(self, task: Task, now: datetime) -> None:
        try:
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="task.stale",
                source="StateEvaluator",
                user_id=task.user_id,
                payload=TaskStalePayload(
                    task_id=task.id,
                    title=task.title,
                    created_at=task.created_at,
                    days_since_update=(now - task.updated_at).days,
                    priority=task.priority.value if task.priority else None,
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish task.stale event for task {task.id}: {exc}")

    # ------------------------------------------------------------------
    # Shared: which work is stuck under which overdue parent
    # ------------------------------------------------------------------

    async def _open_subtasks_by_parent(
        self, db: AsyncSession, parent_ids
    ) -> dict[UUID, list[Task]]:
        """Open subtasks grouped by parent, for the two reasons that are
        *about* the cascade (`task.blocked_cascade`, `task.at_risk`).

        Both used to `count(*)` instead, which is all the risk formula
        needs but not what a notification needs: "còn 2 việc con chưa xong"
        names nothing the user can go do. Fetching the rows once here keeps
        the two predicates reading the same list.
        """
        if not parent_ids:
            return {}
        result = await db.execute(
            select(Task).where(
                Task.parent_task_id.in_(parent_ids),
                Task.status.in_(OPEN_STATUSES),
            )
        )
        grouped: dict[UUID, list[Task]] = {}
        for subtask in result.scalars().all():
            grouped.setdefault(subtask.parent_task_id, []).append(subtask)
        return grouped

    # ------------------------------------------------------------------
    # task.blocked_cascade — task cha trễ, còn ≥1 subtask chưa xong
    # ------------------------------------------------------------------

    async def _evaluate_task_blocked_cascade(self):
        async with self._session_maker() as db:
            today = _today()
            today_start = datetime.combine(today, time.min)

            overdue_parents_result = await db.execute(
                select(Task).where(
                    Task.status.in_(OPEN_STATUSES),
                    Task.due_date.isnot(None),
                    Task.due_date < today_start,
                )
            )
            overdue_parents = {t.id: t for t in overdue_parents_result.scalars().all()}
            blocked_parents = await self._open_subtasks_by_parent(db, set(overdue_parents))

            to_publish, _ = await self._diff_flags(
                db,
                item_type=AttentionItemType.TASK,
                flag_key=BLOCKED_CASCADE_FLAG_KEY,
                current_ids=set(blocked_parents),
                user_id_by_item={pid: overdue_parents[pid].user_id for pid in blocked_parents},
            )

            for parent_id in to_publish:
                await self._publish_task_blocked_cascade(
                    overdue_parents[parent_id], today, blocked_parents[parent_id]
                )

    async def _publish_task_blocked_cascade(self, parent: Task, today, open_subtasks: list[Task]) -> None:
        try:
            due_day = _due_day(parent)
            ordered = sorted(open_subtasks, key=lambda t: _rank_key(t, today))
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="task.blocked_cascade",
                source="StateEvaluator",
                user_id=parent.user_id,
                payload=TaskBlockedCascadePayload(
                    task_id=parent.id,
                    title=parent.title,
                    overdue_days=(today - due_day).days,
                    open_subtask_count=len(open_subtasks),
                    due_date=parent.due_date,
                    priority=parent.priority.value if parent.priority else None,
                    open_subtasks=[_task_item(t) for t in ordered[:MAX_DIGEST_ITEMS]],
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish task.blocked_cascade event for task {parent.id}: {exc}")

    # ------------------------------------------------------------------
    # task.at_risk — compute_risk(priority, overdue_days, cascade) vượt
    # ngưỡng (6.8/4.4)
    # ------------------------------------------------------------------

    async def _evaluate_task_at_risk(self):
        """Escalation on top of `task.overdue`, not a replacement for it —
        every `at_risk` task is also `overdue`, but most overdue tasks
        never cross `STATE_EVALUATOR_RISK_THRESHOLD`. Reuses the same
        overdue-parent + open-subtask-count query `_evaluate_task_blocked_
        cascade` already runs (same cascade input, per `risk_detection`'s
        module docstring), then scores every overdue task — not just ones
        with subtasks — through `compute_risk`."""
        async with self._session_maker() as db:
            today = _today()
            today_start = datetime.combine(today, time.min)

            overdue_result = await db.execute(
                select(Task).where(
                    Task.status.in_(OPEN_STATUSES),
                    Task.due_date.isnot(None),
                    Task.due_date < today_start,
                )
            )
            overdue_tasks = {t.id: t for t in overdue_result.scalars().all()}

            at_risk: dict[UUID, tuple[float, list[Task]]] = {}
            if overdue_tasks:
                subtasks_by_parent = await self._open_subtasks_by_parent(db, set(overdue_tasks))

                for task_id, task in overdue_tasks.items():
                    overdue_days = (today - _due_day(task)).days
                    open_subtasks = subtasks_by_parent.get(task_id, [])
                    risk = compute_risk(task.priority, overdue_days, len(open_subtasks))
                    if risk >= settings.STATE_EVALUATOR_RISK_THRESHOLD:
                        at_risk[task_id] = (risk, open_subtasks)

            to_publish, _ = await self._diff_flags(
                db,
                item_type=AttentionItemType.TASK,
                flag_key=AT_RISK_FLAG_KEY,
                current_ids=set(at_risk),
                user_id_by_item={tid: overdue_tasks[tid].user_id for tid in at_risk},
            )

            for task_id in to_publish:
                risk_score, open_subtasks = at_risk[task_id]
                await self._publish_task_at_risk(
                    overdue_tasks[task_id], today, risk_score, open_subtasks
                )

    async def _publish_task_at_risk(
        self, task: Task, today, risk_score: float, open_subtasks: list[Task]
    ) -> None:
        try:
            due_day = _due_day(task)
            ordered = sorted(open_subtasks, key=lambda t: _rank_key(t, today))
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="task.at_risk",
                source="StateEvaluator",
                user_id=task.user_id,
                payload=TaskAtRiskPayload(
                    task_id=task.id,
                    title=task.title,
                    risk_score=risk_score,
                    overdue_days=(today - due_day).days,
                    open_subtask_count=len(open_subtasks),
                    priority=task.priority.value if task.priority else None,
                    due_date=task.due_date,
                    open_subtasks=[_task_item(t) for t in ordered[:MAX_DIGEST_ITEMS]],
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish task.at_risk event for task {task.id}: {exc}")

    # ------------------------------------------------------------------
    # Predicate cấp dự án — DESIGN 6
    # ------------------------------------------------------------------
    #
    # Cả hai chạy **một lần mỗi ngày cho mỗi dự án**, không phải mỗi tick.
    # Đó là yêu cầu của DESIGN 4.3 chứ không phải tối ưu: `deadline` suy ra
    # từ `max(due_date)` nhảy mỗi lần thêm task, và nếu đánh giá theo tick
    # thì `project.slipping` bật/tắt theo từng lần ghi. Mốc "đã đánh giá
    # hôm nay chưa" đọc từ `project_snapshots`, nên nó sống sót qua restart
    # — khác với một biến trong bộ nhớ.

    async def _evaluate_projects(self):
        """Một lượt cho cả hai predicate dự án, vì cả hai dùng chung số liệu.

        Tách làm hai vòng lặp nghĩa là quét `tasks` hai lần cho cùng một tập
        dự án và có nguy cơ hai lần đọc ra hai con số khác nhau — rồi phát
        `slipping` theo số này và `will_miss` theo số kia.
        """
        async with self._session_maker() as db:
            today = _today()
            today_start = datetime.combine(today, time.min)

            projects = list(
                (
                    await db.execute(
                        select(Project).where(Project.status == ProjectStatus.ACTIVE)
                    )
                )
                .scalars()
                .all()
            )
            if not projects:
                return

            due_today = [
                p
                for p in projects
                if not await self._already_evaluated_today(db, p.id, today_start)
            ]
            if not due_today:
                return

            slipping: dict[UUID, ProjectSlippingPayload] = {}
            will_miss: dict[UUID, ProjectWillMissPayload] = {}
            owner_by_project: dict[UUID, UUID] = {}

            for project in due_today:
                owner_by_project[project.id] = project.owner_id
                metrics = await self._project_metrics(db, project, today, today_start)

                previous = await self._latest_snapshot(db, project.id)
                db.add(
                    ProjectSnapshot(
                        project_id=project.id,
                        open_count=metrics["open_count"],
                        completed_last_14d=metrics["completed_last_14d"],
                    )
                )

                # `deadline IS NULL` là cổng chung của cả hai predicate và là
                # bất biến chịu lực của DESIGN 3.4: dự án cá nhân không bao
                # giờ có deadline, nên nó không bao giờ sinh nhắc cấp dự án
                # dù có bao nhiêu việc quá hạn. Không có nhánh này thì sớm
                # muộn xuất hiện câu "Cá nhân có 47 việc quá hạn" — đúng
                # loại nhiễu P5 cấm.
                if project.deadline is None:
                    continue

                days_left = (project.deadline.date() - today).days

                if (
                    previous is not None
                    and metrics["open_count"] > previous.open_count
                    and days_left <= PROJECT_SLIPPING_HORIZON_DAYS
                ):
                    slipping[project.id] = ProjectSlippingPayload(
                        project_id=project.id,
                        name=project.name,
                        open_count=metrics["open_count"],
                        previous_open_count=previous.open_count,
                        days_to_deadline=days_left,
                        deadline=project.deadline,
                        source_channel_id=project.source_channel_id,
                        top_tasks=metrics["top_tasks"],
                    )

                payload = self._will_miss_payload(project, metrics, days_left, today)
                if payload is not None:
                    will_miss[project.id] = payload

            await db.commit()

            await self._publish_project_predicate(
                db,
                flag_key=PROJECT_SLIPPING_FLAG_KEY,
                event_type="project.slipping",
                payloads=slipping,
                owner_by_project=owner_by_project,
            )
            await self._publish_will_miss(db, will_miss, owner_by_project)

    async def _already_evaluated_today(
        self, db: AsyncSession, project_id: UUID, today_start: datetime
    ) -> bool:
        return bool(
            await db.scalar(
                select(func.count())
                .select_from(ProjectSnapshot)
                .where(
                    ProjectSnapshot.project_id == project_id,
                    ProjectSnapshot.evaluated_at >= today_start,
                )
            )
        )

    async def _latest_snapshot(
        self, db: AsyncSession, project_id: UUID
    ) -> ProjectSnapshot | None:
        return await db.scalar(
            select(ProjectSnapshot)
            .where(ProjectSnapshot.project_id == project_id)
            .order_by(ProjectSnapshot.evaluated_at.desc())
            .limit(1)
        )

    async def _project_metrics(
        self,
        db: AsyncSession,
        project: Project,
        today,
        today_start: datetime,
    ) -> dict:
        """Số liệu của một dự án, và nơi duy nhất `deadline` được suy ra.

        **Chỉ đếm Task.** Không bao giờ tính tiến độ từ số cuộc họp đã diễn
        ra (DESIGN 6.3) — đó là kiểu hỏng kinh điển làm dự án nhiều họp
        trông như đang chạy tốt. `CalendarItemService` trộn Task và Schedule
        để *hiển thị*; đó là chuyện khác và không được chảy vào đây.
        """
        open_tasks = list(
            (
                await db.execute(
                    select(Task).where(
                        Task.project_id == project.id,
                        Task.status.in_(OPEN_STATUSES),
                        Task.recurrence_id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

        window_start = today_start - timedelta(days=PROJECT_VELOCITY_WINDOW_DAYS)
        completed_last_14d = int(
            await db.scalar(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.project_id == project.id,
                    Task.status == TaskStatus.DONE,
                    Task.completed_at.isnot(None),
                    Task.completed_at >= window_start,
                )
            )
            or 0
        )

        # DESIGN 4.3 — `deadline := max(due_date)`, tính lại mỗi ngày một
        # lần ở đây và không ở đâu khác. `deadline_is_manual` khoá lại lựa
        # chọn của người dùng: suy ra là mặc định, không phải phán quyết.
        #
        # Dự án cá nhân bị loại **trước** cả cờ manual, và đây là chỗ suýt
        # hỏng: suy ra deadline từ `max(due_date)` sẽ cấp cho dự án cá nhân
        # một deadline ngay khi người dùng có một việc lẻ có hạn — và cùng
        # lúc đó bất biến `deadline IS NULL` của DESIGN 3.4 sụp, kéo theo cả
        # hai predicate cấp dự án bắt đầu nói về "Cá nhân". Bất biến đó
        # không tự giữ mình; đây là nơi nó được giữ.
        if project.origin is ProjectOrigin.PERSONAL:
            pass
        elif not project.deadline_is_manual:
            derived = max((t.due_date for t in open_tasks if t.due_date), default=None)
            if derived != project.deadline:
                project.deadline = derived

        ordered = sorted(open_tasks, key=lambda t: _rank_key(t, today))
        return {
            "open_count": len(open_tasks),
            "completed_last_14d": completed_last_14d,
            "top_tasks": [_task_item(t) for t in ordered[:MAX_DIGEST_ITEMS]],
        }

    def _will_miss_payload(
        self, project: Project, metrics: dict, days_left: int, today
    ) -> ProjectWillMissPayload | None:
        """DESIGN 6.2 — số học thuần, không ML, không token.

            tốc_độ  := completed trong 14 ngày qua / 14
            ngày_cần := việc_mở / tốc_độ
            phát khi now + ngày_cần > deadline

        Im khi không còn việc mở: một dự án đã xong không "sẽ trễ". Tốc độ 0
        **với** việc mở còn lại thì ngược lại là tín hiệu mạnh nhất có thể —
        hai tuần không hoàn thành gì thì theo bất kỳ phép ngoại suy nào cũng
        không kịp.
        """
        open_count = metrics["open_count"]
        if open_count == 0:
            return None

        velocity = metrics["completed_last_14d"] / PROJECT_VELOCITY_WINDOW_DAYS
        days_needed = float("inf") if velocity == 0 else open_count / velocity
        if days_needed <= days_left:
            return None

        return ProjectWillMissPayload(
            project_id=project.id,
            name=project.name,
            open_count=open_count,
            completed_last_14d=metrics["completed_last_14d"],
            velocity_per_day=velocity,
            # `inf` không serialise được sang JSON. Trần hoá bằng một số
            # lớn-nhưng-thật: "cần hơn một năm" nói đúng điều cần nói và
            # vẫn đi qua được mọi tầng.
            days_needed=min(days_needed, 3650.0),
            days_to_deadline=days_left,
            deadline=project.deadline,
            source_channel_id=project.source_channel_id,
            top_tasks=metrics["top_tasks"],
        )

    async def _publish_project_predicate(
        self,
        db: AsyncSession,
        *,
        flag_key: str,
        event_type: str,
        payloads: dict[UUID, "BaseModel"],
        owner_by_project: dict[UUID, UUID],
    ) -> None:
        to_publish, _ = await self._diff_flags(
            db,
            item_type=AttentionItemType.PROJECT,
            flag_key=flag_key,
            current_ids=set(payloads),
            user_id_by_item=owner_by_project,
        )
        for project_id in to_publish:
            try:
                event_bus = await self._get_event_bus()
                await event_bus.publish(
                    EventEnvelope(
                        type=event_type,
                        source="StateEvaluator",
                        user_id=owner_by_project[project_id],
                        payload=payloads[project_id].model_dump(),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to publish %s for project %s: %s", event_type, project_id, exc
                )

    async def _publish_will_miss(
        self,
        db: AsyncSession,
        payloads: dict[UUID, ProjectWillMissPayload],
        owner_by_project: dict[UUID, UUID],
    ) -> None:
        """Chống rung: chỉ phát khi vượt ngưỡng **hai lần đánh giá liên tiếp**.

        DESIGN 4.3 yêu cầu điều này vì `deadline` suy ra từ `max(due_date)`,
        nên một task mới có hạn xa đẩy deadline ra và một task hoàn thành
        kéo nó về — `will_miss` sẽ bật/tắt theo nếu phát ngay lần đầu.

        Cơ chế dùng lại đúng bảng cờ: lần vượt đầu tiên chỉ đặt cờ *pending*,
        lần thứ hai mới phát. Cờ nằm trong DB nên nó sống sót qua restart,
        khác với việc nhớ trong bộ nhớ tiến trình.
        """
        pending_now = set(payloads)
        previously_pending, _ = await self._diff_flags(
            db,
            item_type=AttentionItemType.PROJECT,
            flag_key=PROJECT_WILL_MISS_PENDING_FLAG_KEY,
            current_ids=pending_now,
            user_id_by_item=owner_by_project,
        )
        # `_diff_flags` trả về những cái *mới* vượt ngưỡng lần này. Cái đủ
        # điều kiện phát là phần còn lại: đã pending từ lần trước và vẫn
        # vượt lần này.
        confirmed = {
            pid: payload
            for pid, payload in payloads.items()
            if pid not in previously_pending
        }
        await self._publish_project_predicate(
            db,
            flag_key=PROJECT_WILL_MISS_FLAG_KEY,
            event_type="project.will_miss",
            payloads=confirmed,
            owner_by_project=owner_by_project,
        )

    # ------------------------------------------------------------------
    # schedule.starts_soon — event bắt đầu trong [MIN, MAX] phút
    # ------------------------------------------------------------------

    async def _evaluate_schedule_starts_soon(self):
        async with self._session_maker() as db:
            now = _utcnow()
            window_start = now + timedelta(minutes=settings.STATE_EVALUATOR_SCHEDULE_STARTS_SOON_MIN_MINUTES)
            window_end = now + timedelta(minutes=settings.STATE_EVALUATOR_SCHEDULE_STARTS_SOON_MAX_MINUTES)

            result = await db.execute(
                select(Schedule).where(
                    Schedule.is_cancelled.is_(False),
                    Schedule.start_time >= window_start,
                    Schedule.start_time <= window_end,
                )
            )
            starting_soon = {s.id: s for s in result.scalars().all()}

            to_publish, _ = await self._diff_flags(
                db,
                item_type=AttentionItemType.SCHEDULE,
                flag_key=STARTS_SOON_FLAG_KEY,
                current_ids=set(starting_soon),
                user_id_by_item={sid: s.user_id for sid, s in starting_soon.items()},
            )

            for schedule_id in to_publish:
                await self._publish_schedule_starts_soon(starting_soon[schedule_id], now)

    async def _publish_schedule_starts_soon(self, schedule: Schedule, now: datetime) -> None:
        try:
            minutes_until_start = max(0, int((schedule.start_time - now).total_seconds() // 60))
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="schedule.starts_soon",
                source="StateEvaluator",
                user_id=schedule.user_id,
                payload=ScheduleStartsSoonPayload(
                    schedule_id=schedule.id,
                    title=schedule.title,
                    start_time=schedule.start_time,
                    minutes_until_start=minutes_until_start,
                    location=schedule.location,
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish schedule.starts_soon event for schedule {schedule.id}: {exc}")

    # ------------------------------------------------------------------
    # day.review — cuối ngày, còn việc chưa xong
    # ------------------------------------------------------------------

    async def _evaluate_day_review(self):
        """Per-user, not per-item: the condition is "has open work and it's
        past the review hour", so `item_type=USER`/`item_id=user_id` (see
        AttentionItemType's docstring). The idempotency trick still works
        unmodified — once the UTC hour crosses the threshold the condition
        stays true for the rest of that day (no re-publish), then flips
        false at midnight when the hour resets, clearing the flag so the
        next day's crossing publishes again. No per-user timezone exists in
        this schema (see UserPreferences' docstring) — this is a fixed UTC
        hour, the same known limitation quiet hours already accepted.
        """
        now = _utcnow()
        if now.hour < settings.STATE_EVALUATOR_DAY_REVIEW_HOUR_UTC:
            users_with_open_work: dict[UUID, int] = {}
        else:
            async with self._session_maker() as db:
                # Điều kiện phát dùng **cùng thước** với nội dung: ai có
                # việc đến hạn hôm nay thì có gì để tổng kết. Đếm cả backlog
                # ở đây sẽ bắn bản tổng kết cho người hôm nay không có việc
                # nào — và thẻ của họ hiện "Xong 0/0".
                #
                # Vẫn là một truy vấn gộp theo user thay vì gọi
                # `get_tasks_in_range` cho từng người: đây là vòng quét toàn
                # hệ thống, và N truy vấn cho N người dùng là N+1 ở đúng chỗ
                # chạy mỗi năm phút.
                day_start = datetime.combine(_today(), time.min)
                day_end = datetime.combine(_today(), time.max)
                counts_result = await db.execute(
                    select(Task.user_id, func.count(Task.id))
                    .where(
                        Task.status.in_(OPEN_STATUSES),
                        Task.recurrence_id.is_(None),
                        Task.due_date.isnot(None),
                        Task.due_date >= day_start,
                        Task.due_date <= day_end,
                    )
                    .group_by(Task.user_id)
                )
                users_with_open_work = dict(counts_result.all())

        async with self._session_maker() as db:
            await self._clear_stale_daily_flags(
                db, DAY_REVIEW_FLAG_KEY, datetime.combine(_today(), time.min)
            )
            to_publish, _ = await self._diff_flags(
                db,
                item_type=AttentionItemType.USER,
                flag_key=DAY_REVIEW_FLAG_KEY,
                current_ids=set(users_with_open_work),
                user_id_by_item={uid: uid for uid in users_with_open_work},
            )

            for user_id in to_publish:
                await self._publish_day_review(db, user_id, users_with_open_work[user_id])

    async def _publish_day_review(self, db: AsyncSession, user_id: UUID, open_task_count: int) -> None:
        try:
            today = _today()
            today_start = datetime.combine(today, time.min)

            # **Dùng chung định nghĩa "việc của ngày X" với lưới lịch.**
            #
            # `CalendarItemService.get_tasks_in_range` là nơi câu hỏi đó
            # được trả lời cho màn Lịch và màn Việc; gọi lại nó ở đây là
            # thứ duy nhất đảm bảo bản tổng kết và màn hình của cùng một
            # ngày không thể nói hai con số khác nhau. Chúng đã từng: bản
            # tổng kết tự viết truy vấn riêng, chọn *mọi* việc đang mở, và
            # báo "còn 10 việc chưa xong" trong khi chỉ 1 việc đến hạn hôm
            # nay — chín việc còn lại có hạn từ tuần sau tới tháng 2/2027.
            #
            # Hàm đó **không lọc trạng thái**, nên nó trả về cả hai nửa mà
            # một bản tổng kết cần: đã xong và chưa xong.
            from app.services.calendar_items import CalendarItemService

            todays_tasks = await CalendarItemService(db).get_tasks_in_range(
                user_id, today, today
            )
            open_tasks = [t for t in todays_tasks if t.status in OPEN_STATUSES]
            completed_tasks = [t for t in todays_tasks if t.status is TaskStatus.DONE]

            # Quá hạn đếm riêng và **không vào mẫu số của tỷ lệ**: việc quá
            # hạn từ tuần trước là thứ cần cảnh báo, nhưng nó không phải
            # thứ hôm nay có cơ hội làm xong. Trộn vào tỷ lệ sẽ làm một
            # ngày làm việc tốt đọc như một ngày tệ.
            overdue_task_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(Task)
                    .where(
                        Task.user_id == user_id,
                        Task.status.in_(OPEN_STATUSES),
                        Task.recurrence_id.is_(None),
                        Task.due_date.isnot(None),
                        Task.due_date < today_start,
                    )
                )
                or 0
            )

            ordered_open = sorted(open_tasks, key=lambda t: _rank_key(t, today))
            ordered_done = sorted(
                completed_tasks, key=lambda t: t.completed_at or today_start, reverse=True
            )

            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="day.review",
                source="StateEvaluator",
                user_id=user_id,
                payload=DayReviewPayload(
                    open_task_count=len(open_tasks),
                    overdue_task_count=overdue_task_count,
                    completed_today_count=len(completed_tasks),
                    completed_today=[_task_item(t) for t in ordered_done[:MAX_DIGEST_ITEMS]],
                    still_open=[_task_item(t) for t in ordered_open[:MAX_DIGEST_ITEMS]],
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish day.review event for user {user_id}: {exc}")

    # ------------------------------------------------------------------
    # day.plan — đầu ngày làm việc, việc cần làm hôm nay
    # ------------------------------------------------------------------

    async def _evaluate_day_plan(self):
        """The morning counterpart to `day.review`, and the only predicate
        here that fires before anything has gone wrong.

        Every other task reason is triggered by a deadline that is already
        close (`task.due_soon`) or already missed (`task.overdue`,
        `task.blocked_cascade`, `task.at_risk`) — so until this existed the
        first thing Cortex said about a day's work was a warning about it.

        Same per-user shape as `day.review` (`item_type=USER`), same fixed
        UTC hour with the same known timezone limitation, and the same flag
        idempotency — with the daily reset made explicit rather than relying
        on the hour dropping back below the threshold; see
        `_clear_stale_daily_flags`.
        """
        now = _utcnow()
        today = _today()
        today_start = datetime.combine(today, time.min)
        tomorrow_start = today_start + timedelta(days=1)

        users: dict[UUID, tuple[list[Task], list[Task], list[Schedule]]] = {}
        if now.hour >= settings.STATE_EVALUATOR_DAY_PLAN_HOUR_UTC:
            async with self._session_maker() as db:
                task_result = await db.execute(
                    select(Task).where(
                        Task.status.in_(OPEN_STATUSES),
                        Task.due_date.isnot(None),
                        Task.due_date < tomorrow_start,
                    )
                )
                for task in task_result.scalars().all():
                    due_today, carried, events = users.setdefault(task.user_id, ([], [], []))
                    (carried if task.due_date < today_start else due_today).append(task)

                schedule_result = await db.execute(
                    select(Schedule).where(
                        Schedule.is_cancelled.is_(False),
                        Schedule.start_time >= today_start.replace(tzinfo=timezone.utc),
                        Schedule.start_time < tomorrow_start.replace(tzinfo=timezone.utc),
                    )
                )
                for schedule in schedule_result.scalars().all():
                    # A day with only meetings still deserves a plan, so a
                    # schedule can put a user on this list by itself.
                    users.setdefault(schedule.user_id, ([], [], []))[2].append(schedule)

        async with self._session_maker() as db:
            await self._clear_stale_daily_flags(db, DAY_PLAN_FLAG_KEY, today_start)
            to_publish, _ = await self._diff_flags(
                db,
                item_type=AttentionItemType.USER,
                flag_key=DAY_PLAN_FLAG_KEY,
                current_ids=set(users),
                user_id_by_item={uid: uid for uid in users},
            )

            for user_id in to_publish:
                await self._publish_day_plan(user_id, today, *users[user_id])

    async def _publish_day_plan(
        self,
        user_id: UUID,
        today,
        due_today: list[Task],
        carried_over: list[Task],
        schedules: list[Schedule],
    ) -> None:
        try:
            ordered_today = sorted(due_today, key=lambda t: _rank_key(t, today))
            ordered_carried = sorted(carried_over, key=lambda t: _rank_key(t, today))
            ordered_schedules = sorted(schedules, key=lambda s: s.start_time)

            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="day.plan",
                source="StateEvaluator",
                user_id=user_id,
                payload=DayPlanPayload(
                    due_today_count=len(due_today),
                    carried_over_count=len(carried_over),
                    schedule_count=len(schedules),
                    due_today=[_task_item(t) for t in ordered_today[:MAX_DIGEST_ITEMS]],
                    carried_over=[_task_item(t) for t in ordered_carried[:MAX_DIGEST_ITEMS]],
                    schedules=[_schedule_item(s) for s in ordered_schedules[:MAX_DIGEST_ITEMS]],
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish day.plan event for user {user_id}: {exc}")
