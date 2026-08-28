"""Integration tests for Milestone 6.9 — Feedback Loop, Gate integration.

Simulates repeated dismissal by writing AttentionLog rows directly (the
same table `POST /attention-log/{id}/response` would have written to) and
checking the Gate's next decision for that (user, reason_key) reflects the
downgrade — the M4 test Bản 2's spec calls for ("giả lập user dismiss liên
tục 1 loại → tần suất/cấp độ giảm").
"""

from datetime import date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.config import settings
from app.database_async import make_async_sessionmaker
from tests.project_helper import personal_project_id, personal_project_id_sync
from app.models import (
    AttentionBundleQueue,
    AttentionItemType,
    AttentionLevel,
    AttentionLog,
    AttentionResponse,
    Notification,
    Task,
    TaskPriority,
    TaskStatus,
    UserPreferences,
)
from app.services.attention_gate import request_attention_async
from tests.integration.isolated_user import ensure_isolated_user

TITLE_PREFIX = "[test-6.9] "
YESTERDAY = datetime.combine(date.today() - timedelta(days=1), time(9, 0))


@pytest_asyncio.fixture
async def user_id():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
    await engine.dispose()
    return uid


@pytest_asyncio.fixture
async def async_db(user_id):
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        await db.execute(delete(AttentionBundleQueue).where(AttentionBundleQueue.user_id == user_id))
        await db.execute(delete(Notification).where(Notification.user_id == user_id))
        await db.execute(delete(AttentionLog).where(AttentionLog.user_id == user_id))
        await db.execute(delete(Task).where(Task.user_id == user_id))
        await db.execute(delete(UserPreferences).where(UserPreferences.user_id == user_id))
        await db.commit()
    await engine.dispose()


async def _make_task(db, user_id, *, suffix: str, priority, due_date) -> Task:
    task = Task(
        project_id=await personal_project_id(db, user_id),
        user_id=user_id, title=f"{TITLE_PREFIX}{suffix}", status=TaskStatus.TODO,
        due_date=due_date, priority=priority,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _record_dismissals(db, user_id, *, reason_key: str, count: int) -> None:
    for _ in range(count):
        db.add(AttentionLog(
            user_id=user_id,
            item_type=AttentionItemType.TASK,
            item_id=user_id,  # arbitrary — dismiss_count is keyed on (user_id, reason_key) only
            reason_key=reason_key,
            level=AttentionLevel.RECOMMEND,
            response=AttentionResponse.DISMISSED,
        ))
    await db.commit()


@pytest.mark.asyncio
async def test_dismissals_below_threshold_do_not_downgrade(async_db, user_id):
    await _record_dismissals(async_db, user_id, reason_key="task.overdue", count=settings.FEEDBACK_LOOP_DISMISS_THRESHOLD - 1)
    task = await _make_task(async_db, user_id, suffix="below", priority=TaskPriority.MEDIUM, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
    assert notification.attention_level is AttentionLevel.RECOMMEND


@pytest.mark.asyncio
async def test_one_threshold_of_dismissals_downgrades_one_level(async_db, user_id):
    await _record_dismissals(async_db, user_id, reason_key="task.overdue", count=settings.FEEDBACK_LOOP_DISMISS_THRESHOLD)
    task = await _make_task(async_db, user_id, suffix="one-threshold", priority=TaskPriority.MEDIUM, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
    assert notification.attention_level is AttentionLevel.INFORM


@pytest.mark.asyncio
async def test_enough_dismissals_silences_and_is_not_queued(async_db, user_id):
    await _record_dismissals(
        async_db, user_id, reason_key="task.overdue", count=settings.FEEDBACK_LOOP_DISMISS_THRESHOLD * 10,
    )
    task = await _make_task(async_db, user_id, suffix="silenced", priority=TaskPriority.MEDIUM, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is None
    queued = (
        await async_db.execute(
            AttentionBundleQueue.__table__.select().where(AttentionBundleQueue.item_id == task.id)
        )
    ).fetchall()
    assert queued == [], "feedback-driven silence must not be bundled for later, same as an explicit opt-out"


@pytest.mark.asyncio
async def test_downgrade_does_not_beat_urgent_escalation_below_ask_ceiling(async_db, user_id):
    """One threshold of dismissals drops RECOMMEND -> INFORM, but urgency
    still escalates *up to* ASK first — downgrade caps the escalated
    level, it doesn't ignore escalation outright."""
    await _record_dismissals(async_db, user_id, reason_key="task.overdue", count=settings.FEEDBACK_LOOP_DISMISS_THRESHOLD)
    task = await _make_task(async_db, user_id, suffix="urgent-vs-downgrade", priority=TaskPriority.URGENT, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
    assert notification.attention_level is AttentionLevel.RECOMMEND


@pytest.mark.asyncio
async def test_dismissals_on_one_reason_do_not_affect_another(async_db, user_id):
    await _record_dismissals(
        async_db, user_id, reason_key="task.stale", count=settings.FEEDBACK_LOOP_DISMISS_THRESHOLD * 10,
    )
    task = await _make_task(async_db, user_id, suffix="other-reason", priority=TaskPriority.MEDIUM, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
    assert notification.attention_level is AttentionLevel.RECOMMEND
