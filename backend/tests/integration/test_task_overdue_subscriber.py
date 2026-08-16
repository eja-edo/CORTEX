"""
Integration test for the task.overdue -> Attention Gate wiring
(notification_subscribers.handle_task_overdue), the first real
detection->delivery path a Task ever had — see that function's docstring.

Not re-testing the Gate's own decision logic here (test_attention_gate.py
owns that); this only proves the subscriber builds a correct candidate from
the event payload and the two missing-field guards work.
"""

from datetime import date, datetime, time, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database_async import close_async_engine, make_async_sessionmaker
from app.events.schemas import EventEnvelope
from app.models import AttentionLog, Notification, Task, TaskPriority, TaskStatus
from app.services.notification_subscribers import handle_task_overdue
from tests.integration.isolated_user import ensure_isolated_user

TITLE_PREFIX = "[test-subscriber-4.3] "
YESTERDAY = datetime.combine(date.today() - timedelta(days=1), time(9, 0))


@pytest_asyncio.fixture(autouse=True)
async def _reset_global_async_engine():
    """`handle_task_overdue` (like `handle_schedule_reminder_due`) opens its
    own session via the module-global `AsyncSessionLocal` proxy in
    `app.database_async` — correct in production (one process, one loop for
    the app's whole life) but that global binds its asyncpg pool to
    whichever event loop first touches it. This suite's fixture loop scope
    is per-function (pytest.ini), so a prior test's now-closed loop leaks
    into this one without a reset — "attached to a different loop"."""
    await close_async_engine()
    yield
    await close_async_engine()


@pytest_asyncio.fixture
async def user_id():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
    await engine.dispose()
    return uid


@pytest_asyncio.fixture
async def task(user_id):
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        t = Task(
            user_id=user_id, title=f"{TITLE_PREFIX}subscriber",
            status=TaskStatus.TODO, due_date=YESTERDAY, priority=TaskPriority.URGENT,
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)
        yield t
        await db.execute(delete(Notification).where(Notification.user_id == user_id))
        await db.execute(delete(AttentionLog).where(AttentionLog.user_id == user_id))
        await db.execute(delete(Task).where(Task.id == t.id))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_publishes_a_notification_tagged_with_the_task(user_id, task):
    event = EventEnvelope(
        type="task.overdue", source="StateEvaluator", user_id=user_id,
        payload={"task_id": str(task.id), "title": task.title, "overdue_days": 1},
    )

    await handle_task_overdue(event)

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        rows = (
            await db.execute(select(Notification).where(Notification.user_id == user_id))
        ).scalars().all()
    await engine.dispose()

    assert len(rows) == 1
    assert rows[0].reason_key == "task.overdue"
    assert rows[0].payload["task_id"] == str(task.id)


@pytest.mark.asyncio
async def test_missing_user_id_is_skipped_without_raising():
    event = EventEnvelope(
        type="task.overdue", source="StateEvaluator", user_id=None,
        payload={"task_id": str(uuid4()), "title": "x", "overdue_days": 1},
    )
    await handle_task_overdue(event)  # must not raise


@pytest.mark.asyncio
async def test_missing_task_id_is_skipped_without_raising(user_id):
    event = EventEnvelope(
        type="task.overdue", source="StateEvaluator", user_id=user_id,
        payload={"title": "x", "overdue_days": 1},
    )
    await handle_task_overdue(event)  # must not raise
