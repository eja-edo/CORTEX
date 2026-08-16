"""
Integration tests for Milestone 6.1 M2+M3 — Attention Gate, all five steps.

Runs against the real dev Postgres, on the throwaway isolated account (see
tests/integration/isolated_user.py) — needed here specifically because
`is_user_busy` reads *every* schedule row for a user with no title filter,
so this can't safely share the seeded dev account the way most other
integration tests do.

Both `request_attention_async` (used by notification_subscribers.py) and
`request_attention_sync` (used by `/internal/attention/request`, i.e. every
workflow-originated candidate) implement the same three steps
independently — see attention_gate.py's module docstring for why. The
`_sync` tests below exist to catch the two drifting apart, not to
re-prove every case the `_async` tests already cover.
"""

from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import sync_session
from app.database_async import make_async_sessionmaker
from app.models import (
    AttentionBundleQueue,
    AttentionItemType,
    AttentionLevel,
    AttentionLog,
    Notification,
    Schedule,
    ScheduleType,
    Task,
    TaskPriority,
    TaskStatus,
)
from app.services.attention_gate import request_attention_async, request_attention_sync
from tests.integration.isolated_user import ensure_isolated_user

TITLE_PREFIX = "[test-6.1] "

YESTERDAY = datetime.combine(date.today() - timedelta(days=1), time(9, 0))
SIX_DAYS_AGO = datetime.combine(date.today() - timedelta(days=6), time(9, 0))


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
        await db.execute(delete(Schedule).where(Schedule.user_id == user_id))
        await db.execute(delete(Task).where(Task.user_id == user_id))
        await db.commit()
    await engine.dispose()


async def _make_task(db, user_id, *, suffix: str, priority, due_date) -> Task:
    task = Task(
        user_id=user_id,
        title=f"{TITLE_PREFIX}{suffix}",
        status=TaskStatus.TODO,
        due_date=due_date,
        priority=priority,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _make_busy_schedule(db, user_id) -> Schedule:
    now = datetime.now(timezone.utc)
    schedule = Schedule(
        user_id=user_id,
        title=f"{TITLE_PREFIX}meeting",
        type=ScheduleType.PERSONAL,
        start_time=now - timedelta(minutes=5),
        end_time=now + timedelta(minutes=55),
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


async def _attention_log_for(db, item_id) -> list[AttentionLog]:
    rows = (
        await db.execute(select(AttentionLog).where(AttentionLog.item_id == item_id))
    ).scalars().all()
    return list(rows)


# ============================================================================
# Step 1 — importance (baseline + task-specific escalation)
# ============================================================================


@pytest.mark.asyncio
async def test_low_priority_overdue_task_stays_at_reason_baseline(async_db, user_id):
    task = await _make_task(async_db, user_id, suffix="low", priority=TaskPriority.LOW, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
    assert notification.attention_level is AttentionLevel.RECOMMEND
    assert notification.reason_key == "task.overdue"
    assert notification.attention_log_id is not None


@pytest.mark.asyncio
async def test_urgent_priority_escalates_to_ask(async_db, user_id):
    task = await _make_task(async_db, user_id, suffix="urgent", priority=TaskPriority.URGENT, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
    assert notification.attention_level is AttentionLevel.ASK


@pytest.mark.asyncio
async def test_five_plus_days_overdue_escalates_to_ask_even_without_priority(async_db, user_id):
    task = await _make_task(async_db, user_id, suffix="stale", priority=None, due_date=SIX_DAYS_AGO)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
    assert notification.attention_level is AttentionLevel.ASK


# ============================================================================
# Step 2 — already known (dedup via attention_log)
# ============================================================================


@pytest.mark.asyncio
async def test_second_call_same_item_same_reason_is_suppressed(async_db, user_id):
    task = await _make_task(async_db, user_id, suffix="dedup", priority=TaskPriority.LOW, due_date=YESTERDAY)
    kwargs = dict(
        db=async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    first = await request_attention_async(**kwargs)
    second = await request_attention_async(**kwargs)

    assert first is not None
    assert second is None

    rows = await _attention_log_for(async_db, task.id)
    assert len(rows) == 1
    notifications = (
        await async_db.execute(select(Notification).where(Notification.attention_log_id == rows[0].id))
    ).scalars().all()
    assert len(notifications) == 1


# ============================================================================
# Step 3 — availability (busy check)
# ============================================================================


@pytest.mark.asyncio
async def test_busy_user_silences_a_non_critical_candidate_and_queues_it(async_db, user_id):
    task = await _make_task(async_db, user_id, suffix="busy-recommend", priority=TaskPriority.LOW, due_date=YESTERDAY)
    await _make_busy_schedule(async_db, user_id)

    notification = await request_attention_async(
        async_db, user_id=user_id, title=f"{TITLE_PREFIX}quá hạn",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is None
    rows = await _attention_log_for(async_db, task.id)
    assert len(rows) == 1
    assert rows[0].level is AttentionLevel.SILENT

    queued = (
        await async_db.execute(
            select(AttentionBundleQueue).where(AttentionBundleQueue.item_id == task.id)
        )
    ).scalars().all()
    assert len(queued) == 1
    assert queued[0].flushed_at is None
    assert queued[0].attention_log_id == rows[0].id


@pytest.mark.asyncio
async def test_busy_user_does_not_silence_a_critical_candidate(async_db, user_id):
    task = await _make_task(async_db, user_id, suffix="busy-ask", priority=TaskPriority.URGENT, due_date=YESTERDAY)
    await _make_busy_schedule(async_db, user_id)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
    assert notification.attention_level is AttentionLevel.ASK

    queued = (
        await async_db.execute(
            select(AttentionBundleQueue).where(AttentionBundleQueue.item_id == task.id)
        )
    ).scalars().all()
    assert queued == []


# ============================================================================
# Pass-through — item-less system candidates (e.g. Google Calendar reauth)
# ============================================================================


@pytest.mark.asyncio
async def test_item_less_candidate_bypasses_the_gate_entirely(async_db, user_id):
    notification = await request_attention_async(
        async_db, user_id=user_id, title=f"{TITLE_PREFIX}system alert",
    )

    assert notification is not None
    assert notification.reason_key is None
    assert notification.attention_level is None
    assert notification.attention_log_id is None


# ============================================================================
# Sync twin — enough to catch it drifting from the async implementation
# ============================================================================


def test_sync_dedup_matches_async_behaviour(user_id):
    with sync_session() as db:
        task = Task(
            user_id=user_id, title=f"{TITLE_PREFIX}sync-dedup",
            status=TaskStatus.TODO, due_date=YESTERDAY, priority=TaskPriority.LOW,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        kwargs = dict(
            db=db, user_id=user_id, title="x",
            item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
        )
        first = request_attention_sync(**kwargs)
        second = request_attention_sync(**kwargs)

        assert first is not None
        assert first.attention_level == AttentionLevel.RECOMMEND
        assert second is None

        db.query(AttentionBundleQueue).filter(AttentionBundleQueue.user_id == user_id).delete()
        db.query(Notification).filter(Notification.user_id == user_id).delete()
        db.query(AttentionLog).filter(AttentionLog.user_id == user_id).delete()
        db.query(Task).filter(Task.user_id == user_id).delete()
        db.commit()


def test_sync_busy_check_silences_non_critical_and_queues_it(user_id):
    with sync_session() as db:
        task = Task(
            user_id=user_id, title=f"{TITLE_PREFIX}sync-busy",
            status=TaskStatus.TODO, due_date=YESTERDAY, priority=TaskPriority.LOW,
        )
        now = datetime.now(timezone.utc)
        schedule = Schedule(
            user_id=user_id, title=f"{TITLE_PREFIX}sync-meeting", type=ScheduleType.PERSONAL,
            start_time=now - timedelta(minutes=5), end_time=now + timedelta(minutes=55),
        )
        db.add_all([task, schedule])
        db.commit()
        db.refresh(task)

        notification = request_attention_sync(
            db, user_id=user_id, title="x",
            item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
        )

        assert notification is None
        queued = (
            db.query(AttentionBundleQueue)
            .filter(AttentionBundleQueue.user_id == user_id, AttentionBundleQueue.item_id == task.id)
            .all()
        )
        assert len(queued) == 1
        assert queued[0].flushed_at is None

        db.query(AttentionBundleQueue).filter(AttentionBundleQueue.user_id == user_id).delete()
        db.query(AttentionLog).filter(AttentionLog.user_id == user_id).delete()
        db.query(Schedule).filter(Schedule.user_id == user_id).delete()
        db.query(Task).filter(Task.user_id == user_id).delete()
        db.commit()
