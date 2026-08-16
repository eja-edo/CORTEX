"""
Integration tests for Milestone 6.1 M3 — the bundle flush (steps 4-5).

test_attention_gate.py already proves a busy-silenced candidate gets
queued; this file owns the other half — `flush_due_bundles` turning queued
rows into the one bundled Notification once the user is free, which is the
planning doc's own acceptance scenario for 6.1 ("8 candidates during a
meeting -> 0 during, 1 bundled after").
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database_async import make_async_sessionmaker
from app.models import AttentionBundleQueue, AttentionItemType, Notification, Schedule, ScheduleType
from app.services.attention_bundle import enqueue_async, flush_due_bundles
from tests.integration.isolated_user import ensure_isolated_user

TITLE_PREFIX = "[test-6.1-bundle] "


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
        await db.execute(delete(Schedule).where(Schedule.user_id == user_id))
        await db.commit()
    await engine.dispose()


async def _enqueue(db, user_id, *, suffix: str) -> AttentionBundleQueue:
    return await enqueue_async(
        db, user_id=user_id, item_type=AttentionItemType.TASK, item_id=uuid4(),
        reason_key="task.overdue", title=f"{TITLE_PREFIX}{suffix}", body=None,
        payload={}, actions=[], attention_log_id=None,
    )


@pytest.mark.asyncio
async def test_still_busy_user_is_not_flushed(async_db, user_id):
    now = datetime.now(timezone.utc)
    schedule = Schedule(
        user_id=user_id, title=f"{TITLE_PREFIX}meeting", type=ScheduleType.PERSONAL,
        start_time=now - timedelta(minutes=5), end_time=now + timedelta(minutes=55),
    )
    async_db.add(schedule)
    await async_db.commit()

    await _enqueue(async_db, user_id, suffix="a")

    flushed = await flush_due_bundles(async_db)

    assert flushed == 0
    rows = (
        await async_db.execute(select(AttentionBundleQueue).where(AttentionBundleQueue.user_id == user_id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].flushed_at is None


@pytest.mark.asyncio
async def test_free_user_gets_one_bundled_notification_for_all_queued_items(async_db, user_id):
    await _enqueue(async_db, user_id, suffix="one")
    await _enqueue(async_db, user_id, suffix="two")
    await _enqueue(async_db, user_id, suffix="three")

    flushed = await flush_due_bundles(async_db)

    assert flushed == 1

    notifications = (
        await async_db.execute(select(Notification).where(Notification.user_id == user_id))
    ).scalars().all()
    assert len(notifications) == 1
    assert "3" in notifications[0].title
    assert notifications[0].reason_key == "attention.bundle"
    assert len(notifications[0].payload["bundled_items"]) == 3
    # One content block per item, not one block holding a "\n"-joined
    # string — the latter renders as a single line in the detail modal
    # (BlockRenderer's text block has no white-space: pre-wrap).
    assert len(notifications[0].content) == 3
    assert all(block["type"] == "text" for block in notifications[0].content)
    assert " • " in notifications[0].body

    rows = (
        await async_db.execute(select(AttentionBundleQueue).where(AttentionBundleQueue.user_id == user_id))
    ).scalars().all()
    assert all(row.flushed_at is not None for row in rows)
    assert all(row.bundle_notification_id == notifications[0].id for row in rows)


@pytest.mark.asyncio
async def test_already_flushed_rows_are_not_flushed_again(async_db, user_id):
    await _enqueue(async_db, user_id, suffix="solo")
    first_flush = await flush_due_bundles(async_db)
    assert first_flush == 1

    second_flush = await flush_due_bundles(async_db)
    assert second_flush == 0

    notifications = (
        await async_db.execute(select(Notification).where(Notification.user_id == user_id))
    ).scalars().all()
    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_no_pending_rows_is_a_no_op(async_db, user_id):
    flushed = await flush_due_bundles(async_db)
    assert flushed == 0
