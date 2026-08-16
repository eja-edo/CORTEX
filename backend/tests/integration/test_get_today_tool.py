"""
Integration test for the `get_today` agent tool (Milestone 3.1 M4).

`TodayService`'s ranking itself is already covered end-to-end in
test_today.py; this only proves `get_today_handler` reaches the real
service through `ToolContext` and translates `TodayResponse` into the
tool's dict shape correctly — the thing an agent actually sees.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.ai.agents.tool_context import ToolContext
from app.ai.tools.get_today import get_today_handler
from app.models import Task, TaskPriority, TaskStatus
from app.schemas import TaskCreate
from app.services.tasks import TaskService
from tests.integration.isolated_user import ISOLATED_TEST_USER_ID, ensure_isolated_user

TEST_USER_ID = ISOLATED_TEST_USER_ID
# Task.due_date is a naive TIMESTAMP WITHOUT TIME ZONE column — match it,
# same as test_today.py's own fixtures do.
YESTERDAY = datetime.now().replace(microsecond=0) - timedelta(days=1)


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


@pytest_asyncio.fixture(autouse=True)
async def _reset_event_bus_between_tests():
    from app.events.event_bus import reset_event_bus

    reset_event_bus()
    yield
    import app.events.event_bus as event_bus_module
    if event_bus_module._event_bus is not None:
        try:
            await event_bus_module._event_bus.disconnect()
        except Exception:
            pass
        event_bus_module._event_bus = None


@pytest.mark.asyncio
async def test_reports_overdue_task_with_its_reason_and_pending_confirmation(async_db):
    tasks = TaskService(async_db)
    overdue = await tasks.create_task(
        TaskCreate(title="[test-3.1-M4] nộp báo cáo", due_date=YESTERDAY, priority=TaskPriority.HIGH),
        TEST_USER_ID,
    )
    candidate = await tasks.create_task(
        TaskCreate(title="[test-3.1-M4] gửi proposal"), TEST_USER_ID,
    )
    candidate.status = TaskStatus.PENDING_CONFIRM
    await async_db.commit()

    ctx = ToolContext(user_id=TEST_USER_ID, async_db=async_db)
    result = await get_today_handler({}, ctx)

    assert result["success"] is True
    assert result["state"] == "has_actions"

    assert len(result["now_actions"]) == 1
    action = result["now_actions"][0]
    assert action["task_id"] == str(overdue.id)
    assert "Quá hạn" in action["reason"]

    assert len(result["needs_confirmation"]) == 1
    assert result["needs_confirmation"][0]["task_id"] == str(candidate.id)


@pytest.mark.asyncio
async def test_empty_account_reports_onboarding_with_no_actions(async_db):
    ctx = ToolContext(user_id=TEST_USER_ID, async_db=async_db)
    result = await get_today_handler({}, ctx)

    assert result["success"] is True
    assert result["state"] == "onboarding"
    assert result["now_actions"] == []
    assert result["suggestions"] == []
    assert result["needs_confirmation"] == []
