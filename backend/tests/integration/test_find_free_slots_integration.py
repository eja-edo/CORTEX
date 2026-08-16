"""
Integration test for `find_free_slots` (Milestone 3.3) — proves the DB
query side (`_schedule_intervals_stmt`) feeds real rows into the gap logic
correctly. The gap-merging itself is unit-tested in isolation in
`tests/unit/test_availability_free_slots.py`; this only needs enough cases
to prove the wiring, not to re-cover every merge scenario.
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.database_async import close_async_engine, make_async_sessionmaker
from app.models import Schedule, ScheduleType
from app.services.availability import find_free_slots
from tests.integration.isolated_user import ensure_isolated_user

TITLE_PREFIX = "[test-availability-3.3] "
DAY_START = datetime.combine(date.today() + timedelta(days=1), time(9, 0), tzinfo=timezone.utc)
DAY_END = datetime.combine(date.today() + timedelta(days=1), time(17, 0), tzinfo=timezone.utc)


@pytest_asyncio.fixture(autouse=True)
async def _reset_global_async_engine():
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
async def cleanup(user_id):
    yield
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await db.execute(delete(Schedule).where(Schedule.user_id == user_id))
        await db.commit()
    await engine.dispose()


async def _add_schedule(user_id, start: datetime, end: datetime, cancelled: bool = False):
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        s = Schedule(
            user_id=user_id, title=f"{TITLE_PREFIX}block",
            type=ScheduleType.PERSONAL, start_time=start, end_time=end,
            is_cancelled=cancelled,
        )
        db.add(s)
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_empty_calendar_the_whole_day_is_one_free_slot(user_id, cleanup):
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        slots = await find_free_slots(db, user_id, DAY_START, DAY_END)
    await engine.dispose()

    assert slots == [(DAY_START, DAY_END)]


@pytest.mark.asyncio
async def test_a_meeting_splits_the_day_around_it(user_id, cleanup):
    meeting_start = DAY_START.replace(hour=12)
    meeting_end = DAY_START.replace(hour=13)
    await _add_schedule(user_id, meeting_start, meeting_end)

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        slots = await find_free_slots(db, user_id, DAY_START, DAY_END)
    await engine.dispose()

    assert slots == [(DAY_START, meeting_start), (meeting_end, DAY_END)]


@pytest.mark.asyncio
async def test_a_cancelled_meeting_frees_its_slot_back_up(user_id, cleanup):
    meeting_start = DAY_START.replace(hour=12)
    meeting_end = DAY_START.replace(hour=13)
    await _add_schedule(user_id, meeting_start, meeting_end, cancelled=True)

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        slots = await find_free_slots(db, user_id, DAY_START, DAY_END)
    await engine.dispose()

    assert slots == [(DAY_START, DAY_END)]


@pytest.mark.asyncio
async def test_min_duration_filters_out_short_gaps(user_id, cleanup):
    # Two meetings 15 minutes apart — shorter than the default 30-minute floor.
    await _add_schedule(user_id, DAY_START.replace(hour=10), DAY_START.replace(hour=11))
    await _add_schedule(
        user_id, DAY_START.replace(hour=11, minute=15), DAY_START.replace(hour=12)
    )

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        slots = await find_free_slots(db, user_id, DAY_START, DAY_END)
    await engine.dispose()

    gap_between_meetings = (DAY_START.replace(hour=11), DAY_START.replace(hour=11, minute=15))
    assert gap_between_meetings not in slots


@pytest.mark.asyncio
async def test_reversed_range_returns_no_slots(user_id, cleanup):
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        slots = await find_free_slots(db, user_id, DAY_END, DAY_START)
    await engine.dispose()

    assert slots == []
