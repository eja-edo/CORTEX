"""
Integration test for `list_at_risk_tasks` (Milestone 6.8).

Uses the throwaway isolated account, not the seeded dev one: like
`TodayService.get_today`, this reads every overdue task a user owns with no
title filter to scope it, so a shared account would leak other tests' or a
real person's rows into the score. See tests/integration/isolated_user.py.

The formula itself (`compute_risk`) is unit-tested in isolation in
tests/unit/test_risk_detection.py; this only proves the query wires real
rows — including the parent/subtask cascade count — into it correctly.
"""

from datetime import date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models import Task, TaskPriority, TaskStatus
from app.services.risk_detection import list_at_risk_tasks
from tests.integration.isolated_user import ISOLATED_TEST_USER_ID, ensure_isolated_user

TEST_USER_ID = ISOLATED_TEST_USER_ID
YESTERDAY = datetime.combine(date.today() - timedelta(days=1), time(9, 0))
THREE_DAYS_AGO = datetime.combine(date.today() - timedelta(days=3), time(9, 0))
TOMORROW = datetime.combine(date.today() + timedelta(days=1), time(9, 0))


@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await ensure_isolated_user(db)
        await db.execute(delete(Task).where(Task.user_id == TEST_USER_ID))
        await db.commit()
        yield db
        await db.execute(delete(Task).where(Task.user_id == TEST_USER_ID))
        await db.commit()
    await engine.dispose()


async def _task(db, title, due_date=None, priority=None, status=TaskStatus.TODO, parent_task_id=None) -> Task:
    task = Task(
        user_id=TEST_USER_ID, title=title, status=status,
        due_date=due_date, priority=priority, parent_task_id=parent_task_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_not_yet_due_tasks_are_excluded(async_db):
    await _task(async_db, "chưa tới hạn", due_date=TOMORROW, priority=TaskPriority.URGENT)

    result = await list_at_risk_tasks(async_db, TEST_USER_ID)

    assert result == []


@pytest.mark.asyncio
async def test_overdue_task_is_scored_and_returned(async_db):
    task = await _task(async_db, "trễ hạn", due_date=YESTERDAY, priority=TaskPriority.HIGH)

    result = await list_at_risk_tasks(async_db, TEST_USER_ID)

    assert len(result) == 1
    scored_task, risk = result[0]
    assert scored_task.id == task.id
    assert risk == 3.0  # HIGH weight (3) * 1 day overdue * (1 + 0 subtasks)


@pytest.mark.asyncio
async def test_open_subtasks_raise_the_parents_risk(async_db):
    parent = await _task(async_db, "cha trễ hạn", due_date=YESTERDAY, priority=TaskPriority.MEDIUM)
    await _task(async_db, "con 1 chưa xong", parent_task_id=parent.id)
    await _task(async_db, "con 2 chưa xong", parent_task_id=parent.id)
    await _task(
        async_db, "con đã xong", parent_task_id=parent.id, status=TaskStatus.DONE,
    )

    result = await list_at_risk_tasks(async_db, TEST_USER_ID)

    scored_task, risk = next(pair for pair in result if pair[0].id == parent.id)
    assert risk == 6.0  # MEDIUM weight (2) * 1 day * (1 + 2 open subtasks)


@pytest.mark.asyncio
async def test_sorted_highest_risk_first(async_db):
    mild = await _task(async_db, "trễ nhẹ", due_date=YESTERDAY, priority=TaskPriority.LOW)
    severe = await _task(async_db, "trễ nặng", due_date=THREE_DAYS_AGO, priority=TaskPriority.URGENT)

    result = await list_at_risk_tasks(async_db, TEST_USER_ID)

    assert [t.id for t, _ in result] == [severe.id, mild.id]


@pytest.mark.asyncio
async def test_min_risk_filters_out_low_scores(async_db):
    await _task(async_db, "trễ nhẹ", due_date=YESTERDAY, priority=TaskPriority.LOW)

    result = await list_at_risk_tasks(async_db, TEST_USER_ID, min_risk=2.0)

    assert result == []
