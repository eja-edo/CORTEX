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
from tests.project_helper import personal_project_id, personal_project_id_sync
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
        project_id=await personal_project_id(db, user_id),
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
            project_id=personal_project_id_sync(db, user_id),
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
            project_id=personal_project_id_sync(db, user_id),
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


# ============================================================================
# Step 2b — supersession (nested reasons about the same item)
# ============================================================================
#
# `task.overdue`, `task.blocked_cascade` and `task.at_risk` are nested
# predicates: every at-risk task is also blocked-cascade-eligible and also
# overdue. Plain dedup can't collapse them because it keys on
# (item_id, reason_key) by design. See attention_reason_catalog.SUPERSEDES.


@pytest.mark.asyncio
async def test_at_risk_suppresses_the_overdue_nudge_for_the_same_task(async_db, user_id):
    """The user-visible bug: one urgent, late task with open subtasks
    produced three near-identical notifications in a single evaluator tick,
    two of which were also DM'd. Only the strongest should speak."""
    task = await _make_task(
        async_db, user_id, suffix="triple", priority=TaskPriority.URGENT, due_date=YESTERDAY
    )

    at_risk = await request_attention_async(
        async_db, user_id=user_id, title="Rủi ro cao",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.at_risk",
    )
    cascade = await request_attention_async(
        async_db, user_id=user_id, title="Đang bị chặn",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.blocked_cascade",
    )
    overdue = await request_attention_async(
        async_db, user_id=user_id, title="Quá hạn",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert at_risk is not None
    assert cascade is None
    assert overdue is None

    notifications = (
        await async_db.execute(select(Notification).where(Notification.user_id == user_id))
    ).scalars().all()
    assert len(notifications) == 1
    assert notifications[0].reason_key == "task.at_risk"

    # Silence is still a recorded decision — "why didn't Cortex say anything
    # about this being overdue?" has to stay answerable.
    logs = await _attention_log_for(async_db, task.id)
    by_reason = {log.reason_key: log.level for log in logs}
    assert by_reason["task.at_risk"] is not AttentionLevel.SILENT
    assert by_reason["task.blocked_cascade"] is AttentionLevel.SILENT
    assert by_reason["task.overdue"] is AttentionLevel.SILENT


@pytest.mark.asyncio
async def test_escalation_still_speaks_after_a_weaker_reason_already_did(async_db, user_id):
    """Supersession is one-directional on purpose. A task that was merely
    overdue and has since crossed the risk threshold has genuinely got
    worse, and that is news — suppressing it would make the Gate quieter
    than the situation warrants."""
    task = await _make_task(
        async_db, user_id, suffix="escalating", priority=TaskPriority.HIGH, due_date=YESTERDAY
    )

    overdue = await request_attention_async(
        async_db, user_id=user_id, title="Quá hạn",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )
    at_risk = await request_attention_async(
        async_db, user_id=user_id, title="Rủi ro cao",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.at_risk",
    )

    assert overdue is not None
    assert at_risk is not None


@pytest.mark.asyncio
async def test_supersession_is_scoped_to_one_item(async_db, user_id):
    """An at-risk task must not silence a *different* task's overdue nudge."""
    risky = await _make_task(
        async_db, user_id, suffix="risky", priority=TaskPriority.URGENT, due_date=YESTERDAY
    )
    other = await _make_task(
        async_db, user_id, suffix="other", priority=TaskPriority.LOW, due_date=YESTERDAY
    )

    await request_attention_async(
        async_db, user_id=user_id, title="Rủi ro cao",
        item_type=AttentionItemType.TASK, item_id=risky.id, reason_key="task.at_risk",
    )
    overdue = await request_attention_async(
        async_db, user_id=user_id, title="Quá hạn",
        item_type=AttentionItemType.TASK, item_id=other.id, reason_key="task.overdue",
    )

    assert overdue is not None


@pytest.mark.asyncio
async def test_unrelated_reasons_are_not_superseded(async_db, user_id):
    """`task.due_soon` and `task.stale` stand alone — the nesting rule must
    not leak into reasons that aren't part of the overdue family."""
    task = await _make_task(
        async_db, user_id, suffix="unrelated", priority=TaskPriority.URGENT, due_date=YESTERDAY
    )

    await request_attention_async(
        async_db, user_id=user_id, title="Rủi ro cao",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.at_risk",
    )
    stale = await request_attention_async(
        async_db, user_id=user_id, title="Bị bỏ quên",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.stale",
    )

    assert stale is not None


def test_sync_path_applies_supersession_too(user_id):
    """The sync twin re-implements steps 1-3; this catches it drifting."""
    task_id = uuid4()
    with sync_session() as db:
        task = Task(
            project_id=personal_project_id_sync(db, user_id),
            id=task_id, user_id=user_id, title=f"{TITLE_PREFIX}sync-supersede",
            status=TaskStatus.TODO, due_date=YESTERDAY, priority=TaskPriority.URGENT,
        )
        db.add(task)
        db.commit()

    try:
        with sync_session() as db:
            at_risk = request_attention_sync(
                db, user_id=user_id, title="Rủi ro cao",
                item_type=AttentionItemType.TASK, item_id=task_id, reason_key="task.at_risk",
            )
            overdue = request_attention_sync(
                db, user_id=user_id, title="Quá hạn",
                item_type=AttentionItemType.TASK, item_id=task_id, reason_key="task.overdue",
            )

        assert at_risk is not None
        assert overdue is None
    finally:
        with sync_session() as db:
            db.execute(delete(Notification).where(Notification.user_id == user_id))
            db.execute(delete(AttentionLog).where(AttentionLog.item_id == task_id))
            db.execute(delete(Task).where(Task.id == task_id))
            db.commit()
