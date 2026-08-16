"""
Integration tests for Milestone 4.6 — State Evaluator: the original
`task.overdue` predicate plus the five A1 added it (`task.due_soon`,
`task.stale`, `task.blocked_cascade`, `schedule.starts_soon`,
`day.review`). See app/services/state_evaluator.py's module docstring for
why `goal.at_risk`/`commitment.*` are still out of scope: neither model
exists.

Runs against the real dev Postgres + Redis, reusing the seeded user (same
pattern as tests/integration/test_tasks.py). Every row created here is
titled with TITLE_PREFIX and hard-deleted in teardown, including any
state_evaluator_flags left over for those tasks/schedules, plus any
`day.review` flag left over for TEST_USER_ID itself.
"""

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.config import settings
from app.database_async import make_async_sessionmaker
from app.events.event_bus import EventBus, reset_event_bus
from app.events.schemas import EventEnvelope
from app.models import AttentionItemType, Schedule, ScheduleType, StateEvaluatorFlag, Task, TaskPriority, TaskStatus
from app.services.state_evaluator import StateEvaluator

TEST_USER_ID = UUID("73552833-a6de-40a1-bb69-6e034ca75460")
TITLE_PREFIX = "[test-4.6] "

YESTERDAY = datetime.combine(date.today() - timedelta(days=1), time(9, 0))
TWO_DAYS_AGO = datetime.combine(date.today() - timedelta(days=2), time(9, 0))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def async_db():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        task_ids = (
            await db.execute(select(Task.id).where(Task.title.startswith(TITLE_PREFIX)))
        ).scalars().all()
        schedule_ids = (
            await db.execute(select(Schedule.id).where(Schedule.title.startswith(TITLE_PREFIX)))
        ).scalars().all()
        stale_ids = list(task_ids) + list(schedule_ids)
        if stale_ids:
            await db.execute(delete(StateEvaluatorFlag).where(StateEvaluatorFlag.item_id.in_(stale_ids)))
        await db.execute(
            delete(StateEvaluatorFlag).where(
                StateEvaluatorFlag.item_type == AttentionItemType.USER,
                StateEvaluatorFlag.item_id == TEST_USER_ID,
                StateEvaluatorFlag.flag_key == "day_review",
            )
        )
        await db.execute(delete(Schedule).where(Schedule.title.startswith(TITLE_PREFIX)))
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


ALL_EVENT_TYPES = (
    "task.overdue",
    "task.due_soon",
    "task.stale",
    "task.blocked_cascade",
    "task.at_risk",
    "schedule.starts_soon",
    "day.review",
)


@pytest_asyncio.fixture
async def event_subscriber():
    reset_event_bus()
    bus = EventBus()
    await bus.connect()

    received: list[EventEnvelope] = []

    async def collector(event: EventEnvelope):
        received.append(event)

    for event_type in ALL_EVENT_TYPES:
        bus.subscribe(event_type, collector)

    import app.events.event_bus as event_bus_module
    event_bus_module._event_bus = bus

    yield received

    for event_type in ALL_EVENT_TYPES:
        bus.unsubscribe(event_type, collector)
    event_bus_module._event_bus = None
    await bus.disconnect()


def _events_of_type(received: list[EventEnvelope], event_type: str) -> list[EventEnvelope]:
    return [e for e in received if e.type == event_type]


async def _make_task(
    db, *, title_suffix: str, status: TaskStatus, due_date, priority=None, parent_task_id=None
) -> Task:
    task = Task(
        user_id=TEST_USER_ID,
        title=f"{TITLE_PREFIX}{title_suffix}",
        status=status,
        due_date=due_date,
        priority=priority,
        parent_task_id=parent_task_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _make_schedule(db, *, title_suffix: str, start_time, end_time, is_cancelled=False) -> Schedule:
    schedule = Schedule(
        user_id=TEST_USER_ID,
        title=f"{TITLE_PREFIX}{title_suffix}",
        type=ScheduleType.PERSONAL,
        start_time=start_time,
        end_time=end_time,
        is_cancelled=is_cancelled,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


async def _flag(db, item_id, *, item_type=AttentionItemType.TASK, flag_key="overdue") -> StateEvaluatorFlag | None:
    result = await db.execute(
        select(StateEvaluatorFlag).where(
            StateEvaluatorFlag.item_type == item_type,
            StateEvaluatorFlag.item_id == item_id,
            StateEvaluatorFlag.flag_key == flag_key,
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


# ---------------------------------------------------------------------------
# task.due_soon (A1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_due_soon_lifecycle_publishes_once_per_transition(async_db, evaluator, event_subscriber):
    soon = _utcnow().replace(tzinfo=None) + timedelta(hours=2)
    task = await _make_task(async_db, title_suffix="due_soon", status=TaskStatus.TODO, due_date=soon)

    await evaluator._evaluate_task_due_soon()
    events = _events_of_type(event_subscriber, "task.due_soon")
    assert len(events) == 1
    assert events[0].payload["task_id"] == task.id
    assert await _flag(async_db, task.id, flag_key="due_soon") is not None

    # Second scan, nothing changed: must not republish.
    await evaluator._evaluate_task_due_soon()
    assert len(_events_of_type(event_subscriber, "task.due_soon")) == 1

    # Moved to in_progress: no longer needs the nudge, flag clears.
    task.status = TaskStatus.IN_PROGRESS
    async_db.add(task)
    await async_db.commit()
    await evaluator._evaluate_task_due_soon()
    assert await _flag(async_db, task.id, flag_key="due_soon") is None

    # Back to todo, still due soon: a genuine second transition -> republishes.
    task.status = TaskStatus.TODO
    async_db.add(task)
    await async_db.commit()
    await evaluator._evaluate_task_due_soon()
    assert len(_events_of_type(event_subscriber, "task.due_soon")) == 2


@pytest.mark.asyncio
async def test_due_soon_excludes_due_date_far_in_the_future(async_db, evaluator, event_subscriber):
    far_future = _utcnow().replace(tzinfo=None) + timedelta(hours=settings.STATE_EVALUATOR_DUE_SOON_HOURS + 24)
    task = await _make_task(async_db, title_suffix="due_far", status=TaskStatus.TODO, due_date=far_future)

    await evaluator._evaluate_task_due_soon()

    assert len(_events_of_type(event_subscriber, "task.due_soon")) == 0
    assert await _flag(async_db, task.id, flag_key="due_soon") is None


# ---------------------------------------------------------------------------
# task.stale (A1)
# ---------------------------------------------------------------------------


async def _backdate_updated_at(db, task_id, updated_at: datetime) -> None:
    from sqlalchemy import update
    await db.execute(update(Task).where(Task.id == task_id).values(updated_at=updated_at))
    await db.commit()


@pytest.mark.asyncio
async def test_stale_lifecycle_publishes_once_per_transition(async_db, evaluator, event_subscriber):
    task = await _make_task(async_db, title_suffix="stale", status=TaskStatus.TODO, due_date=None)
    old = _utcnow().replace(tzinfo=None) - timedelta(days=settings.STATE_EVALUATOR_STALE_DAYS + 1)
    await _backdate_updated_at(async_db, task.id, old)

    await evaluator._evaluate_task_stale()
    events = _events_of_type(event_subscriber, "task.stale")
    assert len(events) == 1
    assert events[0].payload["task_id"] == task.id
    assert await _flag(async_db, task.id, flag_key="stale") is not None

    # Second scan, nothing changed: must not republish.
    await evaluator._evaluate_task_stale()
    assert len(_events_of_type(event_subscriber, "task.stale")) == 1

    # Touched again (updated_at moves to now): flag clears.
    await _backdate_updated_at(async_db, task.id, _utcnow().replace(tzinfo=None))
    await evaluator._evaluate_task_stale()
    assert await _flag(async_db, task.id, flag_key="stale") is None

    # Goes untouched again: a genuine second transition -> republishes.
    await _backdate_updated_at(async_db, task.id, old)
    await evaluator._evaluate_task_stale()
    assert len(_events_of_type(event_subscriber, "task.stale")) == 2


@pytest.mark.asyncio
async def test_stale_excludes_tasks_with_a_due_date(async_db, evaluator, event_subscriber):
    task = await _make_task(async_db, title_suffix="stale_but_dated", status=TaskStatus.TODO, due_date=YESTERDAY)
    old = _utcnow().replace(tzinfo=None) - timedelta(days=settings.STATE_EVALUATOR_STALE_DAYS + 1)
    await _backdate_updated_at(async_db, task.id, old)

    await evaluator._evaluate_task_stale()

    assert len(_events_of_type(event_subscriber, "task.stale")) == 0
    assert await _flag(async_db, task.id, flag_key="stale") is None


# ---------------------------------------------------------------------------
# task.blocked_cascade (A1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_cascade_publishes_when_parent_overdue_with_open_subtask(async_db, evaluator, event_subscriber):
    parent = await _make_task(async_db, title_suffix="cascade_parent", status=TaskStatus.TODO, due_date=YESTERDAY)
    child = await _make_task(
        async_db, title_suffix="cascade_child", status=TaskStatus.TODO, due_date=None, parent_task_id=parent.id,
    )

    await evaluator._evaluate_task_blocked_cascade()
    events = _events_of_type(event_subscriber, "task.blocked_cascade")
    assert len(events) == 1
    assert events[0].payload["task_id"] == parent.id
    assert events[0].payload["open_subtask_count"] == 1
    assert await _flag(async_db, parent.id, flag_key="blocked_cascade") is not None

    # Second scan, nothing changed: must not republish.
    await evaluator._evaluate_task_blocked_cascade()
    assert len(_events_of_type(event_subscriber, "task.blocked_cascade")) == 1

    # Subtask finished: no longer blocked, flag clears.
    child.status = TaskStatus.DONE
    async_db.add(child)
    await async_db.commit()
    await evaluator._evaluate_task_blocked_cascade()
    assert await _flag(async_db, parent.id, flag_key="blocked_cascade") is None


@pytest.mark.asyncio
async def test_blocked_cascade_requires_an_open_subtask(async_db, evaluator, event_subscriber):
    parent = await _make_task(async_db, title_suffix="cascade_no_child", status=TaskStatus.TODO, due_date=YESTERDAY)

    await evaluator._evaluate_task_blocked_cascade()

    assert len(_events_of_type(event_subscriber, "task.blocked_cascade")) == 0
    assert await _flag(async_db, parent.id, flag_key="blocked_cascade") is None


# ---------------------------------------------------------------------------
# task.at_risk (6.8/4.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_at_risk_publishes_when_score_crosses_threshold(async_db, evaluator, event_subscriber):
    # HIGH weight (3) * 2 days overdue * (1 + 0 subtasks) = 6.0, at the
    # default STATE_EVALUATOR_RISK_THRESHOLD.
    task = await _make_task(
        async_db, title_suffix="at_risk", status=TaskStatus.TODO, due_date=TWO_DAYS_AGO, priority=TaskPriority.HIGH,
    )

    await evaluator._evaluate_task_at_risk()

    events = _events_of_type(event_subscriber, "task.at_risk")
    assert len(events) == 1
    assert events[0].payload["task_id"] == task.id
    assert events[0].payload["risk_score"] == 6.0
    assert await _flag(async_db, task.id, flag_key="at_risk") is not None

    # Second scan, nothing changed: must not republish.
    await evaluator._evaluate_task_at_risk()
    assert len(_events_of_type(event_subscriber, "task.at_risk")) == 1


@pytest.mark.asyncio
async def test_at_risk_not_published_below_threshold(async_db, evaluator, event_subscriber):
    # LOW weight (1) * 1 day overdue * (1 + 0) = 1.0 — well under threshold.
    task = await _make_task(
        async_db, title_suffix="mild", status=TaskStatus.TODO, due_date=YESTERDAY, priority=TaskPriority.LOW,
    )

    await evaluator._evaluate_task_at_risk()

    assert len(_events_of_type(event_subscriber, "task.at_risk")) == 0
    assert await _flag(async_db, task.id, flag_key="at_risk") is None


@pytest.mark.asyncio
async def test_at_risk_clears_when_score_drops_back_below_threshold(async_db, evaluator, event_subscriber):
    # MEDIUM weight (2) * 1 day * (1 + 2 open subtasks) = 6.0 — crosses via
    # the cascade term, not lateness alone.
    parent = await _make_task(
        async_db, title_suffix="at_risk_parent", status=TaskStatus.TODO, due_date=YESTERDAY, priority=TaskPriority.MEDIUM,
    )
    child_a = await _make_task(
        async_db, title_suffix="at_risk_child_a", status=TaskStatus.TODO, due_date=None, parent_task_id=parent.id,
    )
    child_b = await _make_task(
        async_db, title_suffix="at_risk_child_b", status=TaskStatus.TODO, due_date=None, parent_task_id=parent.id,
    )

    await evaluator._evaluate_task_at_risk()
    assert await _flag(async_db, parent.id, flag_key="at_risk") is not None

    # Both subtasks finish: (1 + 0) drops the score to 2.0, under threshold.
    child_a.status = TaskStatus.DONE
    child_b.status = TaskStatus.DONE
    async_db.add(child_a)
    async_db.add(child_b)
    await async_db.commit()

    await evaluator._evaluate_task_at_risk()
    assert await _flag(async_db, parent.id, flag_key="at_risk") is None


# ---------------------------------------------------------------------------
# schedule.starts_soon (A1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_starts_soon_lifecycle_publishes_once_per_transition(async_db, evaluator, event_subscriber):
    now = _utcnow()
    minutes = (
        settings.STATE_EVALUATOR_SCHEDULE_STARTS_SOON_MIN_MINUTES
        + settings.STATE_EVALUATOR_SCHEDULE_STARTS_SOON_MAX_MINUTES
    ) // 2
    start = now + timedelta(minutes=minutes)
    schedule = await _make_schedule(
        async_db, title_suffix="starts_soon", start_time=start, end_time=start + timedelta(hours=1),
    )

    await evaluator._evaluate_schedule_starts_soon()
    events = _events_of_type(event_subscriber, "schedule.starts_soon")
    assert len(events) == 1
    assert events[0].payload["schedule_id"] == schedule.id
    assert await _flag(async_db, schedule.id, item_type=AttentionItemType.SCHEDULE, flag_key="starts_soon") is not None

    # Second scan, nothing changed: must not republish.
    await evaluator._evaluate_schedule_starts_soon()
    assert len(_events_of_type(event_subscriber, "schedule.starts_soon")) == 1

    # Cancelled: flag clears.
    schedule.is_cancelled = True
    async_db.add(schedule)
    await async_db.commit()
    await evaluator._evaluate_schedule_starts_soon()
    assert await _flag(async_db, schedule.id, item_type=AttentionItemType.SCHEDULE, flag_key="starts_soon") is None


@pytest.mark.asyncio
async def test_schedule_starts_soon_excludes_cancelled(async_db, evaluator, event_subscriber):
    now = _utcnow()
    start = now + timedelta(minutes=20)
    schedule = await _make_schedule(
        async_db, title_suffix="cancelled", start_time=start, end_time=start + timedelta(hours=1), is_cancelled=True,
    )

    await evaluator._evaluate_schedule_starts_soon()

    assert len(_events_of_type(event_subscriber, "schedule.starts_soon")) == 0
    assert await _flag(async_db, schedule.id, item_type=AttentionItemType.SCHEDULE, flag_key="starts_soon") is None


@pytest.mark.asyncio
async def test_schedule_starts_soon_excludes_outside_window(async_db, evaluator, event_subscriber):
    now = _utcnow()
    start = now + timedelta(minutes=settings.STATE_EVALUATOR_SCHEDULE_STARTS_SOON_MAX_MINUTES + 30)
    schedule = await _make_schedule(
        async_db, title_suffix="too_far", start_time=start, end_time=start + timedelta(hours=1),
    )

    await evaluator._evaluate_schedule_starts_soon()

    assert len(_events_of_type(event_subscriber, "schedule.starts_soon")) == 0
    assert await _flag(async_db, schedule.id, item_type=AttentionItemType.SCHEDULE, flag_key="starts_soon") is None


# ---------------------------------------------------------------------------
# day.review (A1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_day_review_lifecycle_publishes_once_per_transition(async_db, evaluator, event_subscriber, monkeypatch):
    task = await _make_task(async_db, title_suffix="day_review_open", status=TaskStatus.TODO, due_date=None)

    try:
        # Force "past the review hour" so the condition only depends on
        # open work existing, regardless of wall-clock time the test runs at.
        monkeypatch.setattr(settings, "STATE_EVALUATOR_DAY_REVIEW_HOUR_UTC", 0)
        await evaluator._evaluate_day_review()
        events = [e for e in _events_of_type(event_subscriber, "day.review") if e.user_id == TEST_USER_ID]
        assert len(events) == 1
        assert events[0].payload["open_task_count"] >= 1
        assert await _flag(async_db, TEST_USER_ID, item_type=AttentionItemType.USER, flag_key="day_review") is not None

        # Second scan, nothing changed: must not republish.
        await evaluator._evaluate_day_review()
        events = [e for e in _events_of_type(event_subscriber, "day.review") if e.user_id == TEST_USER_ID]
        assert len(events) == 1

        # Force "before the review hour": condition false for everyone, flag clears.
        monkeypatch.setattr(settings, "STATE_EVALUATOR_DAY_REVIEW_HOUR_UTC", 24)
        await evaluator._evaluate_day_review()
        assert await _flag(async_db, TEST_USER_ID, item_type=AttentionItemType.USER, flag_key="day_review") is None

        # Past the review hour again with the task still open: genuine
        # second transition -> republishes.
        monkeypatch.setattr(settings, "STATE_EVALUATOR_DAY_REVIEW_HOUR_UTC", 0)
        await evaluator._evaluate_day_review()
        events = [e for e in _events_of_type(event_subscriber, "day.review") if e.user_id == TEST_USER_ID]
        assert len(events) == 2
    finally:
        # Belt-and-braces cleanup: flipping the threshold to 0 above also
        # flags every other dev user with open work, not just TEST_USER_ID.
        await async_db.execute(
            delete(StateEvaluatorFlag).where(
                StateEvaluatorFlag.item_type == AttentionItemType.USER,
                StateEvaluatorFlag.flag_key == "day_review",
            )
        )
        await async_db.commit()
