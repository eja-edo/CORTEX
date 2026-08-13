"""State Evaluator (Milestone 4.6).

Turns state that changes with the clock, not with a write, into an event on
the Event Bus — "task overdue 3 days" isn't something that *happened*, so
nothing publishes it from a mutation (see the comment in
app.events.payloads next to TaskOverduePayload). Something has to go ask.

Scope: `task.overdue` only. The planning doc's example set also includes
`goal.at_risk` and `commitment.due_soon`/`commitment.overdue`, but neither
Goal nor Commitment exists as a model in this codebase (Task absorbed both —
see Task's own docstring in app.models). Seeding events for entities that
don't exist would be a hollow implementation, so those wait for Phase 2 to
actually build them.

"Overdue" itself is not redefined here — it reuses the day-granular,
UTC definition already live in app.services.today (`_today`/`_due_day`,
the "Hôm nay" screen), including the precedent that `"task.overdue"` is
already the reason key `today.py` uses for the same condition.

Idempotency: a StateEvaluatorFlag row means "this task is currently
flagged overdue". Each tick computes the current overdue set and diffs it
against existing flags — new members publish + get a flag row, members
that dropped out (task completed/cancelled/reopened past its due date got
pushed out, or the task was deleted) get their flag row deleted. That last
step is what makes a *second* overdue transition (resolved, then overdue
again) publish again instead of being suppressed forever.
"""

import asyncio
from datetime import datetime, time
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import make_async_sessionmaker
from app.events.event_bus import get_event_bus
from app.events.payloads import TaskOverduePayload
from app.events.schemas import EventEnvelope
from app.models import AttentionItemType, StateEvaluatorFlag, Task
from app.services.today import OPEN_STATUSES, _due_day, _today
from app.utils.logger import get_logger

logger = get_logger(__name__)

OVERDUE_FLAG_KEY = "overdue"


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
        try:
            while self._running:
                try:
                    await self._evaluate_task_overdue()
                except Exception as e:
                    logger.exception("Error in state evaluator loop: %s", e)

                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("StateEvaluator: run loop cancelled, exiting cleanly")
            raise

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

            existing_flags_result = await db.execute(
                select(StateEvaluatorFlag).where(
                    StateEvaluatorFlag.item_type == AttentionItemType.TASK,
                    StateEvaluatorFlag.flag_key == OVERDUE_FLAG_KEY,
                )
            )
            existing_flags = {f.item_id: f for f in existing_flags_result.scalars().all()}

            to_publish = set(overdue_tasks) - set(existing_flags)
            to_clear = set(existing_flags) - set(overdue_tasks)

            for task_id in to_clear:
                await db.delete(existing_flags[task_id])

            for task_id in to_publish:
                db.add(StateEvaluatorFlag(
                    user_id=overdue_tasks[task_id].user_id,
                    item_type=AttentionItemType.TASK,
                    item_id=task_id,
                    flag_key=OVERDUE_FLAG_KEY,
                ))

            await db.commit()

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
