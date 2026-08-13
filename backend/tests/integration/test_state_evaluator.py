"""
Integration tests for Milestone 4.6 — State Evaluator, scoped to
`task.overdue` (see app/services/state_evaluator.py's module docstring for
why `goal.at_risk`/`commitment.*` are out of scope: neither model exists).

Runs against the real dev Postgres + Redis, reusing the seeded user (same
pattern as tests/integration/test_tasks.py). Every row created here is
titled with TITLE_PREFIX and hard-deleted in teardown, including any
state_evaluator_flags left over for those tasks.
"""

from datetime import date, datetime, time, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database_async import make_async_sessionmaker
from app.events.event_bus import EventBus, reset_event_bus
from app.events.schemas import EventEnvelope
from app.models import AttentionItemType, StateEvaluatorFlag, Task, TaskPriority, TaskStatus
from app.services.state_evaluator import StateEvaluator

TEST_USER_ID = UUID("73552833-a6de-40a1-bb69-6e034ca75460")
TITLE_PREFIX = "[test-4.6] "

YESTERDAY = datetime.combine(date.today() - timedelta(days=1), time(9, 0))


@pytest_asyncio.fixture
async def async_db():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        task_ids = (
            await db.execute(select(Task.id).where(Task.title.startswith(TITLE_PREFIX)))
        ).scalars().all()
        if task_ids:
            await db.execute(delete(StateEvaluatorFlag).where(StateEvaluatorFlag.item_id.in_(task_ids)))
        await db.execute(delete(Task).where(Task.title.startswith(TITLE_PREFIX)))
        await db.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def evaluator():
    ev = StateEvaluator()
    ev._db_engine, ev._session_maker = make_async_sessionmaker()
    yield ev
    await ev._db_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _reset_event_bus_between_tests():
    reset_event_bus()
    yield
    import app.events.event_bus as event_bus_module
    if event_bus_module._event_bus is not None:
        try:
            await event_bus_module._event_bus.disconnect()
        except Exception:
            pass
        event_bus_module._event_bus = None


@pytest_asyncio.fixture
async def event_subscriber():
    reset_event_bus()
    bus = EventBus()
    await bus.connect()

    received: list[EventEnvelope] = []

    async def collector(event: EventEnvelope):
        received.append(event)

    bus.subscribe("task.overdue", collector)

    import app.events.event_bus as event_bus_module
    event_bus_module._event_bus = bus

    yield received

    bus.unsubscribe("task.overdue", collector)
    event_bus_module._event_bus = None
    await bus.disconnect()


async def _make_task(db, *, title_suffix: str, status: TaskStatus, due_date, priority=None) -> Task:
    task = Task(
        user_id=TEST_USER_ID,
        title=f"{TITLE_PREFIX}{title_suffix}",
        status=status,
        due_date=due_date,
        priority=priority,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _flag(db, task_id) -> StateEvaluatorFlag | None:
    result = await db.execute(
        select(StateEvaluatorFlag).where(
            StateEvaluatorFlag.item_type == AttentionItemType.TASK,
            StateEvaluatorFlag.item_id == task_id,
            StateEvaluatorFlag.flag_key == "overdue",
        )
    )
    return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_overdue_lifecycle_publishes_once_per_transition(async_db, evaluator, event_subscriber):
    task = await _make_task(
        async_db, title_suffix="lifecycle", status=TaskStatus.TODO,
        due_date=YESTERDAY, priority=TaskPriority.HIGH,
    )

    # First scan: newly overdue -> publish once, flag row created.
    await evaluator._evaluate_task_overdue()
    assert len(event_subscriber) == 1
    event = event_subscriber[0]
    assert event.type == "task.overdue"
    assert event.payload["task_id"] == task.id
    assert event.payload["priority"] == "high"
    assert await _flag(async_db, task.id) is not None

    # Second scan, nothing changed: must not republish.
    await evaluator._evaluate_task_overdue()
    assert len(event_subscriber) == 1

    # Task completed: flag must clear, no new publish for the clear itself.
    task.status = TaskStatus.DONE
    async_db.add(task)
    await async_db.commit()
    await evaluator._evaluate_task_overdue()
    assert len(event_subscriber) == 1
    assert await _flag(async_db, task.id) is None

    # Reopened, still overdue: a genuine second transition -> publishes again.
    task.status = TaskStatus.TODO
    async_db.add(task)
    await async_db.commit()
    await evaluator._evaluate_task_overdue()
    assert len(event_subscriber) == 2
    assert event_subscriber[1].payload["task_id"] == task.id
    assert await _flag(async_db, task.id) is not None


@pytest.mark.asyncio
async def test_pending_confirm_task_is_not_published(async_db, evaluator, event_subscriber):
    task = await _make_task(
        async_db, title_suffix="pending_confirm", status=TaskStatus.PENDING_CONFIRM, due_date=YESTERDAY,
    )

    await evaluator._evaluate_task_overdue()

    assert len(event_subscriber) == 0
    assert await _flag(async_db, task.id) is None


@pytest.mark.asyncio
async def test_task_without_due_date_is_not_published(async_db, evaluator, event_subscriber):
    task = await _make_task(
        async_db, title_suffix="no_due_date", status=TaskStatus.TODO, due_date=None,
    )

    await evaluator._evaluate_task_overdue()

    assert len(event_subscriber) == 0
    assert await _flag(async_db, task.id) is None
