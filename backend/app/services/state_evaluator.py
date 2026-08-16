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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database_async import make_async_sessionmaker
from app.events.event_bus import get_event_bus
from app.events.payloads import (
    DayReviewPayload,
    ScheduleStartsSoonPayload,
    TaskAtRiskPayload,
    TaskBlockedCascadePayload,
    TaskDueSoonPayload,
    TaskOverduePayload,
    TaskStalePayload,
)
from app.events.schemas import EventEnvelope
from app.models import AttentionItemType, Schedule, StateEvaluatorFlag, Task, TaskStatus
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
AT_RISK_FLAG_KEY = "at_risk"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
        evaluators = (
            self._evaluate_task_overdue,
            self._evaluate_task_due_soon,
            self._evaluate_task_stale,
            self._evaluate_task_blocked_cascade,
            self._evaluate_task_at_risk,
            self._evaluate_schedule_starts_soon,
            self._evaluate_day_review,
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
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish task.stale event for task {task.id}: {exc}")

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
            if not overdue_parents:
                blocked_parents: dict[UUID, int] = {}
            else:
                open_subtask_counts_result = await db.execute(
                    select(Task.parent_task_id, func.count(Task.id))
                    .where(
                        Task.parent_task_id.in_(overdue_parents),
                        Task.status.in_(OPEN_STATUSES),
                    )
                    .group_by(Task.parent_task_id)
                )
                blocked_parents = dict(open_subtask_counts_result.all())

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

    async def _publish_task_blocked_cascade(self, parent: Task, today, open_subtask_count: int) -> None:
        try:
            due_day = _due_day(parent)
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="task.blocked_cascade",
                source="StateEvaluator",
                user_id=parent.user_id,
                payload=TaskBlockedCascadePayload(
                    task_id=parent.id,
                    title=parent.title,
                    overdue_days=(today - due_day).days,
                    open_subtask_count=open_subtask_count,
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

            at_risk: dict[UUID, tuple[float, int]] = {}
            if overdue_tasks:
                subtask_counts_result = await db.execute(
                    select(Task.parent_task_id, func.count(Task.id))
                    .where(
                        Task.parent_task_id.in_(overdue_tasks),
                        Task.status.in_(OPEN_STATUSES),
                    )
                    .group_by(Task.parent_task_id)
                )
                subtask_counts = dict(subtask_counts_result.all())

                for task_id, task in overdue_tasks.items():
                    overdue_days = (today - _due_day(task)).days
                    open_subtask_count = subtask_counts.get(task_id, 0)
                    risk = compute_risk(task.priority, overdue_days, open_subtask_count)
                    if risk >= settings.STATE_EVALUATOR_RISK_THRESHOLD:
                        at_risk[task_id] = (risk, open_subtask_count)

            to_publish, _ = await self._diff_flags(
                db,
                item_type=AttentionItemType.TASK,
                flag_key=AT_RISK_FLAG_KEY,
                current_ids=set(at_risk),
                user_id_by_item={tid: overdue_tasks[tid].user_id for tid in at_risk},
            )

            for task_id in to_publish:
                risk_score, open_subtask_count = at_risk[task_id]
                await self._publish_task_at_risk(
                    overdue_tasks[task_id], today, risk_score, open_subtask_count
                )

    async def _publish_task_at_risk(
        self, task: Task, today, risk_score: float, open_subtask_count: int
    ) -> None:
        try:
            due_day = _due_day(task)
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
                    open_subtask_count=open_subtask_count,
                    priority=task.priority.value if task.priority else None,
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish task.at_risk event for task {task.id}: {exc}")

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
                counts_result = await db.execute(
                    select(Task.user_id, func.count(Task.id))
                    .where(Task.status.in_(OPEN_STATUSES))
                    .group_by(Task.user_id)
                )
                users_with_open_work = dict(counts_result.all())

        async with self._session_maker() as db:
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
            overdue_count_result = await db.execute(
                select(func.count(Task.id)).where(
                    Task.user_id == user_id,
                    Task.status.in_(OPEN_STATUSES),
                    Task.due_date.isnot(None),
                    Task.due_date < today_start,
                )
            )
            overdue_task_count = overdue_count_result.scalar_one()

            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="day.review",
                source="StateEvaluator",
                user_id=user_id,
                payload=DayReviewPayload(
                    open_task_count=open_task_count,
                    overdue_task_count=overdue_task_count,
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish day.review event for user {user_id}: {exc}")
