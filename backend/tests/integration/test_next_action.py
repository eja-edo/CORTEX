"""
Integration test for `NextActionService` (Milestone 3.5) — the
`/planning/next-action` endpoint's service layer.

`TodayService`'s ranking and `risk_detection`'s scoring are each covered
end-to-end elsewhere (test_today.py, test_risk_detection_integration.py);
this only proves the composition — that both signals land in one response,
and that `at_risk` surfaces a task even when it didn't make the top of
`now_actions`.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models import Task, TaskPriority, TaskStatus
from app.schemas import TaskCreate
from app.services.next_action import NextActionService
from app.services.tasks import TaskService
from tests.integration.isolated_user import ISOLATED_TEST_USER_ID, ensure_isolated_user

TEST_USER_ID = ISOLATED_TEST_USER_ID
TWO_DAYS_AGO = datetime.now().replace(microsecond=0) - timedelta(days=2)
ONE_DAY_AGO = datetime.now().replace(microsecond=0) - timedelta(days=1)


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


@pytest.mark.asyncio
async def test_empty_account_is_onboarding_with_nothing_at_risk(async_db):
    result = await NextActionService(async_db).get_next_action(TEST_USER_ID)

    assert result.state == "onboarding"
    assert result.now_actions == []
    assert result.at_risk == []


@pytest.mark.asyncio
async def test_at_risk_task_surfaces_even_when_crowded_out_of_now_actions(async_db):
    tasks = TaskService(async_db)
    # Three LOW-priority tasks, each more overdue than the at-risk task
    # below — TodayService._rank_actions sorts by overdue_days first, so
    # these fill 3.1's MAX_NOW_ACTIONS=3 cap ahead of it regardless of its
    # higher priority. LOW(1) * (3|4|5) days * 1 = 3/4/5 — all under the
    # risk threshold, so none of these become at_risk themselves.
    for days_overdue in (3, 4, 5):
        await tasks.create_task(
            TaskCreate(
                title=f"[test-3.5] chặn trước {days_overdue}",
                due_date=datetime.now().replace(microsecond=0) - timedelta(days=days_overdue),
                priority=TaskPriority.LOW,
            ),
            TEST_USER_ID,
        )
    # HIGH(3) * 2 days * 1 = 6.0 — crosses the risk threshold, but ranked
    # behind the three more-overdue tasks above so it won't be in
    # now_actions.
    at_risk_task = await tasks.create_task(
        TaskCreate(title="[test-3.5] rủi ro cao", due_date=TWO_DAYS_AGO, priority=TaskPriority.HIGH),
        TEST_USER_ID,
    )

    result = await NextActionService(async_db).get_next_action(TEST_USER_ID)

    assert len(result.now_actions) == 3
    assert at_risk_task.id not in {a.task_id for a in result.now_actions}

    assert len(result.at_risk) == 1
    assert result.at_risk[0].task_id == at_risk_task.id
    assert result.at_risk[0].risk_score == 6.0
    assert "Quá hạn 2 ngày" in result.at_risk[0].impact


@pytest.mark.asyncio
async def test_mildly_overdue_task_is_in_now_actions_but_not_at_risk(async_db):
    tasks = TaskService(async_db)
    task = await tasks.create_task(
        TaskCreate(title="[test-3.5] trễ nhẹ", due_date=ONE_DAY_AGO, priority=TaskPriority.LOW),
        TEST_USER_ID,
    )

    result = await NextActionService(async_db).get_next_action(TEST_USER_ID)

    assert task.id in {a.task_id for a in result.now_actions}
    assert result.at_risk == []
