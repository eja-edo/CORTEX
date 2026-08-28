"""
Integration tests for Milestone 2.6 — Task shown alongside Calendar.

Runs against the real dev Postgres, reusing the seeded user.

The milestone that matters here is M4, and it's a negative one: **no task ever
becomes a row in `schedules`**. That table means "time that is actually
taken". Free-slot planning (3.3) and interruptibility (6.2) both answer "is
the user busy?" from it, so a projected task would make every deadline look
like a booked hour — planning would return wrong answers and the Attention
Gate would go quiet, with nothing anywhere to indicate a bug.

3.3 and 6.2 don't exist yet, so the two queries they will run are written out
here (`FREE_SLOT_SQL`, `INTERRUPTIBILITY_SQL`) and asserted to be unaffected
by tasks — the same approach 2.1a used to prove its columns were sufficient
before `tasks` existed.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text

from app.models import Schedule, ScheduleType, Task, TaskStatus
from app.schemas import TaskCreate
from app.services.calendar_items import CalendarItemService, _sort_key
from app.services.tasks import TaskService

TEST_USER_ID = UUID("73552833-a6de-40a1-bb69-6e034ca75460")


@pytest_asyncio.fixture(autouse=True)
async def _seeded_user():
    """Tài khoản dev mà tệp này hardcode — dựng nếu DB không còn nó.

    Xem `tests/integration/seeded_user.py`: giả định "hàng này luôn có sẵn"
    đã sai một lần và làm 120 test đỏ cùng lúc.
    """
    from app.database_async import make_async_sessionmaker
    from tests.integration.seeded_user import ensure_seeded_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await ensure_seeded_user(db)
    await engine.dispose()

TITLE_PREFIX = "[test-2.6] "

# A fixed day well away from anything else in the dev database.
DAY = date(2026, 10, 14)
DAY_START = datetime(2026, 10, 14, 0, 0)
DAY_END = datetime(2026, 10, 14, 23, 59, 59)


# ============================================================================
# Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        await db.execute(delete(Task).where(Task.title.startswith(TITLE_PREFIX)))
        await db.execute(delete(Schedule).where(Schedule.title.startswith(TITLE_PREFIX)))
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


@pytest.fixture
def service(async_db):
    return CalendarItemService(async_db)


async def _make_schedule(
    db, title: str, start: datetime, end: datetime, location: str | None = None
) -> Schedule:
    schedule = Schedule(
        user_id=TEST_USER_ID,
        title=f"{TITLE_PREFIX}{title}",
        type=ScheduleType.PERSONAL,
        start_time=start,
        end_time=end,
        location=location,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


async def _make_task(db, title: str, due: date | None = DAY, **kwargs) -> Task:
    return await TaskService(db).create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}{title}", due_date=due, **kwargs),
        user_id=TEST_USER_ID,
    )


async def _schedule_count(db) -> int:
    return (await db.execute(
        select(func.count()).select_from(Schedule).where(Schedule.user_id == TEST_USER_ID)
    )).scalar_one()


# ============================================================================
# M4 — the hard rule: nothing from a task reaches `schedules`
# ============================================================================

@pytest.mark.asyncio
async def test_creating_many_dated_tasks_adds_no_schedule_rows(async_db):
    """2.6 M4, first half. Ten tasks, all with a due date, some completed —
    `schedules` must not gain a single row."""
    before = await _schedule_count(async_db)

    for i in range(10):
        task = await _make_task(async_db, f"deadline {i}", due=DAY)
        if i % 3 == 0:
            await TaskService(async_db).complete_task(task.id, TEST_USER_ID)

    after = await _schedule_count(async_db)
    assert after == before, "a task leaked into `schedules`"

    # ...and specifically none carrying a task's title.
    leaked = (await async_db.execute(
        select(Schedule).where(Schedule.title.startswith(TITLE_PREFIX))
    )).scalars().all()
    assert leaked == []


@pytest.mark.asyncio
async def test_reading_the_calendar_writes_nothing(async_db, service):
    """The feed merges in memory. Nothing about rendering the calendar may
    create, project or sync a row."""
    await _make_task(async_db, "read-only check", due=DAY)
    before = await _schedule_count(async_db)

    await service.get_items(TEST_USER_ID, DAY_START, DAY_END)
    await service.get_items(TEST_USER_ID, DAY_START, DAY_END)

    assert await _schedule_count(async_db) == before


# The query 3.3 will run: the busy intervals of a day come from `schedules`
# alone. A task must contribute nothing to it.
FREE_SLOT_SQL = """
SELECT start_time, end_time
FROM schedules
WHERE user_id = :user_id
  AND is_cancelled = false
  AND start_time < :day_end
  AND end_time > :day_start
ORDER BY start_time
"""

# The query 6.2 will run: is the user in something right now?
INTERRUPTIBILITY_SQL = """
SELECT EXISTS (
    SELECT 1 FROM schedules
    WHERE user_id = :user_id
      AND is_cancelled = false
      AND start_time <= :moment
      AND end_time >= :moment
)
"""


@pytest.mark.asyncio
async def test_free_slots_are_unchanged_by_overdue_and_due_tasks(async_db):
    """2.6 M4, second half. One real meeting and a pile of tasks — including
    overdue ones — and the busy intervals stay exactly the one meeting."""
    meeting_start = datetime(2026, 10, 14, 14, 0)
    meeting_end = datetime(2026, 10, 14, 15, 0)
    await _make_schedule(async_db, "team sync", meeting_start, meeting_end)

    params = {"user_id": TEST_USER_ID, "day_start": DAY_START, "day_end": DAY_END}
    busy_before = (await async_db.execute(text(FREE_SLOT_SQL), params)).all()
    # One booked hour. Compared structurally rather than against the literal
    # datetimes: `schedules.start_time` is a timestamptz, so it comes back
    # normalised to UTC rather than as the naive value that went in.
    assert len(busy_before) == 1
    assert (busy_before[0][1] - busy_before[0][0]) == timedelta(hours=1)

    # Five tasks due today, plus three long overdue — the exact situation
    # that would flood the day if tasks were projected into `schedules`.
    for i in range(5):
        await _make_task(async_db, f"due today {i}", due=DAY)
    for i in range(3):
        await _make_task(async_db, f"overdue {i}", due=DAY - timedelta(days=i + 1))

    busy_after = (await async_db.execute(text(FREE_SLOT_SQL), params)).all()
    assert busy_after == busy_before, "tasks changed the busy intervals of the day"

    # The rest of the day is still free: 24h minus the one booked hour.
    booked_minutes = sum(
        (end - start).total_seconds() / 60 for start, end in busy_after
    )
    assert booked_minutes == 60


@pytest.mark.asyncio
async def test_interruptibility_is_unchanged_by_tasks_due_now(async_db):
    """A task due right now must not make the user look mid-meeting — that's
    how the Attention Gate would fall permanently silent."""
    moment = datetime(2026, 10, 14, 9, 30)
    params = {"user_id": TEST_USER_ID, "moment": moment}

    assert (await async_db.execute(text(INTERRUPTIBILITY_SQL), params)).scalar_one() is False

    for i in range(4):
        await _make_task(async_db, f"due right now {i}", due=DAY)

    assert (await async_db.execute(text(INTERRUPTIBILITY_SQL), params)).scalar_one() is False, (
        "tasks made the user look busy — 6.2 would go silent"
    )

    # A real meeting still registers, so the query itself isn't broken.
    await _make_schedule(
        async_db, "standup", datetime(2026, 10, 14, 9, 0), datetime(2026, 10, 14, 10, 0)
    )
    assert (await async_db.execute(text(INTERRUPTIBILITY_SQL), params)).scalar_one() is True


@pytest.mark.asyncio
async def test_completing_a_task_creates_no_schedule_row(async_db):
    """Not even the "it happened, record it" path writes to `schedules`."""
    before = await _schedule_count(async_db)
    task = await _make_task(async_db, "finish me", due=DAY)
    await TaskService(async_db).complete_task(task.id, TEST_USER_ID)
    await TaskService(async_db).delete_task(task.id, TEST_USER_ID)
    assert await _schedule_count(async_db) == before


# ============================================================================
# The unified shape (M1)
# ============================================================================

@pytest.mark.asyncio
async def test_schedule_and_task_share_one_shape(async_db, service):
    schedule = await _make_schedule(
        async_db, "meeting", datetime(2026, 10, 14, 10, 0), datetime(2026, 10, 14, 11, 0),
        location="Room 3",
    )
    task = await _make_task(async_db, "write the spec", due=DAY)

    items = await service.get_items(TEST_USER_ID, DAY_START, DAY_END)
    by_id = {item.id: item for item in items}

    block = by_id[schedule.id]
    assert block.kind == "schedule"
    assert block.render_as == "block"
    # Passed through from the row unchanged (timestamptz → UTC-aware).
    assert block.start_time == schedule.start_time
    assert block.end_time == schedule.end_time
    assert (block.end_time - block.start_time) == timedelta(hours=1)
    assert block.location == "Room 3"
    assert block.status == "scheduled"
    # A schedule has no deadline in this shape.
    assert block.due_date is None

    marker = by_id[task.id]
    assert marker.kind == "task"
    assert marker.render_as == "marker"
    assert marker.due_date == datetime(2026, 10, 14, 0, 0)
    assert marker.status == "todo"
    # A task occupies no span — this is the whole point.
    assert marker.start_time is None
    assert marker.end_time is None
    assert marker.location is None


@pytest.mark.asyncio
async def test_render_as_is_served_not_inferred(async_db, service):
    """The client must never have to map kind→rendering itself; every item
    states how it should be drawn."""
    await _make_schedule(
        async_db, "block", datetime(2026, 10, 14, 8, 0), datetime(2026, 10, 14, 9, 0)
    )
    await _make_task(async_db, "marker", due=DAY)

    items = await service.get_items(TEST_USER_ID, DAY_START, DAY_END)
    mapping = {item.kind: item.render_as for item in items}
    assert mapping == {"schedule": "block", "task": "marker"}
    assert all(item.render_as in ("block", "marker") for item in items)


@pytest.mark.asyncio
async def test_task_due_date_has_no_meaningful_time(async_db, service):
    """A task's deadline is a day. The time is padding to fit the shared
    shape, and it is always midnight so nothing renders a clock from it."""
    await _make_task(async_db, "midnight check", due=DAY)
    items = await service.get_items(TEST_USER_ID, DAY_START, DAY_END)
    marker = next(i for i in items if i.kind == "task")
    assert marker.due_date.time() == datetime.min.time()


@pytest.mark.asyncio
async def test_items_are_merged_and_time_sorted(async_db, service):
    """One array, ordered by when things happen — schedules by start time,
    tasks by due date."""
    await _make_schedule(
        async_db, "afternoon", datetime(2026, 10, 14, 16, 0), datetime(2026, 10, 14, 17, 0)
    )
    await _make_schedule(
        async_db, "morning", datetime(2026, 10, 14, 9, 0), datetime(2026, 10, 14, 10, 0)
    )
    await _make_task(async_db, "due today", due=DAY)

    items = await service.get_items(TEST_USER_ID, DAY_START, DAY_END)
    # Sorted by the service's own key, which normalises the naive task date
    # and the aware schedule timestamp to a comparable form.
    sort_values = [_sort_key(i) for i in items]
    assert sort_values == sorted(sort_values)
    # The midnight task sorts ahead of both meetings.
    assert items[0].kind == "task"


@pytest.mark.asyncio
async def test_range_filtering(async_db, service):
    """Schedules overlap the window; tasks fall inside it by due date."""
    inside = await _make_schedule(
        async_db, "inside", datetime(2026, 10, 14, 9, 0), datetime(2026, 10, 14, 10, 0)
    )
    overlapping = await _make_schedule(
        async_db, "spans midnight", datetime(2026, 10, 13, 23, 0), datetime(2026, 10, 14, 1, 0)
    )
    await _make_schedule(
        async_db, "next week", datetime(2026, 10, 21, 9, 0), datetime(2026, 10, 21, 10, 0)
    )
    task_today = await _make_task(async_db, "today", due=DAY)
    await _make_task(async_db, "next week task", due=DAY + timedelta(days=7))

    ids = {i.id for i in await service.get_items(TEST_USER_ID, DAY_START, DAY_END)}
    assert inside.id in ids
    assert overlapping.id in ids, "a meeting overlapping the window still occupies it"
    assert task_today.id in ids
    assert len(ids) == 3


@pytest.mark.asyncio
async def test_undated_tasks_stay_off_the_calendar(async_db, service):
    """A task with no due date has no day to sit on. It's still real work —
    the "Hôm nay" screen (2.7) is where it belongs, not the grid."""
    undated = await _make_task(async_db, "someday", due=None)
    items = await service.get_items(TEST_USER_ID, DAY_START, DAY_END)
    assert undated.id not in {i.id for i in items}


@pytest.mark.asyncio
async def test_cancelled_schedules_are_excluded(async_db, service):
    cancelled = await _make_schedule(
        async_db, "called off", datetime(2026, 10, 14, 12, 0), datetime(2026, 10, 14, 13, 0)
    )
    cancelled.is_cancelled = True
    await async_db.commit()

    items = await service.get_items(TEST_USER_ID, DAY_START, DAY_END)
    assert cancelled.id not in {i.id for i in items}


@pytest.mark.asyncio
async def test_status_is_flattened_for_both_kinds(async_db, service):
    schedule = await _make_schedule(
        async_db, "done meeting", datetime(2026, 10, 14, 7, 0), datetime(2026, 10, 14, 8, 0)
    )
    schedule.is_completed = True
    await async_db.commit()

    task = await _make_task(async_db, "done task", due=DAY)
    await TaskService(async_db).complete_task(task.id, TEST_USER_ID)

    items = {i.id: i for i in await service.get_items(TEST_USER_ID, DAY_START, DAY_END)}
    assert items[schedule.id].status == "completed"
    assert items[task.id].status == "done"


@pytest.mark.asyncio
async def test_items_are_scoped_to_their_owner(async_db, service):
    await _make_schedule(
        async_db, "mine", datetime(2026, 10, 14, 9, 0), datetime(2026, 10, 14, 10, 0)
    )
    await _make_task(async_db, "mine too", due=DAY)

    assert await service.get_items(uuid4(), DAY_START, DAY_END) == []


# ============================================================================
# Checklist (M3)
# ============================================================================

@pytest.mark.asyncio
async def test_checklist_reads_tasks_by_event_not_description(async_db, service):
    """"Render tasks as a checklist, never parse a checklist into tasks."
    The widget's source is the `tasks` table; the event's description is
    untouched prose."""
    event = await _make_schedule(
        async_db, "planning", datetime(2026, 10, 14, 10, 0), datetime(2026, 10, 14, 11, 0)
    )
    event.description = "Agenda: roadmap, hiring. - [ ] this is prose, not a checklist"
    await async_db.commit()
    event_id = event.id

    first = await _make_task(async_db, "draft the roadmap", due=None, related_event_id=event_id)
    second = await _make_task(async_db, "book the room", due=None, related_event_id=event_id)
    await _make_task(async_db, "unrelated", due=None)

    checklist = await service.get_event_checklist(TEST_USER_ID, event_id)
    assert [t.id for t in checklist] == [first.id, second.id]

    # The description was never touched by any of it.
    await async_db.refresh(event)
    assert event.description == "Agenda: roadmap, hiring. - [ ] this is prose, not a checklist"


@pytest.mark.asyncio
async def test_checklist_items_do_not_appear_as_calendar_markers(async_db, service):
    """A checklist line with no due date belongs inside the event, not as a
    separate marker on the day."""
    event = await _make_schedule(
        async_db, "with checklist", datetime(2026, 10, 14, 10, 0), datetime(2026, 10, 14, 11, 0)
    )
    item = await _make_task(async_db, "sub item", due=None, related_event_id=event.id)

    items = await service.get_items(TEST_USER_ID, DAY_START, DAY_END)
    assert item.id not in {i.id for i in items}


# ============================================================================
# API
# ============================================================================

@pytest_asyncio.fixture
async def api_client(async_db):
    from app import app
    from app.database_async import get_async_db
    from app.dependencies import get_current_user_or_internal

    class _StubUser:
        id = TEST_USER_ID

    async def _override_db():
        yield async_db

    app.dependency_overrides[get_current_user_or_internal] = lambda: _StubUser()
    app.dependency_overrides[get_async_db] = _override_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api") as client:
        yield client

    app.dependency_overrides.pop(get_current_user_or_internal, None)
    app.dependency_overrides.pop(get_async_db, None)


@pytest.mark.asyncio
async def test_api_returns_the_agreed_shape(api_client, async_db):
    await _make_schedule(
        async_db, "meeting", datetime(2026, 10, 14, 10, 0), datetime(2026, 10, 14, 11, 0),
        location="Room 3",
    )
    await _make_task(async_db, "spec", due=DAY)

    response = await api_client.get(
        "/calendar/items",
        params={"from": DAY_START.isoformat(), "to": DAY_END.isoformat()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 2

    expected_keys = {
        "id", "kind", "render_as", "title", "start_time", "end_time",
        "due_date", "status", "location",
    }
    for item in body:
        assert set(item.keys()) == expected_keys

    block = next(i for i in body if i["kind"] == "schedule")
    marker = next(i for i in body if i["kind"] == "task")
    assert block["render_as"] == "block"
    assert marker["render_as"] == "marker"
    assert marker["start_time"] is None and marker["end_time"] is None
    assert block["due_date"] is None


@pytest.mark.asyncio
async def test_api_rejects_a_backwards_range(api_client):
    response = await api_client.get(
        "/calendar/items",
        params={"from": DAY_END.isoformat(), "to": DAY_START.isoformat()},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_api_requires_both_bounds(api_client):
    assert (await api_client.get(
        "/calendar/items", params={"from": DAY_START.isoformat()}
    )).status_code == 422


@pytest.mark.asyncio
async def test_api_checklist_endpoint(api_client, async_db):
    event = await _make_schedule(
        async_db, "checklist event", datetime(2026, 10, 14, 10, 0), datetime(2026, 10, 14, 11, 0)
    )
    event_id = event.id
    await _make_task(async_db, "line one", due=None, related_event_id=event_id)

    response = await api_client.get(f"/calendar/events/{event_id}/checklist")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["related_event_id"] == str(event_id)


@pytest.mark.asyncio
async def test_checklist_actions_are_plain_task_commands(api_client, async_db):
    """Every widget interaction is one command against one task: create,
    complete, delete. No parsing, no diffing, no reconciliation."""
    event = await _make_schedule(
        async_db, "actions", datetime(2026, 10, 14, 10, 0), datetime(2026, 10, 14, 11, 0)
    )
    event_id = event.id
    schedules_before = await _schedule_count(async_db)

    # Type a line + Enter → task.create
    created = await api_client.post(
        "/tasks",
        json={"title": f"{TITLE_PREFIX}new line", "related_event_id": str(event_id)},
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    # Tick the box → task.complete
    completed = await api_client.post(f"/tasks/{task_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"

    # Delete the line → task.delete
    assert (await api_client.delete(f"/tasks/{task_id}")).status_code == 204
    assert (await api_client.get(f"/calendar/events/{event_id}/checklist")).json() == []

    # ...and none of it touched `schedules`.
    assert await _schedule_count(async_db) == schedules_before


@pytest.mark.asyncio
async def test_task_delete_command_is_registered_and_revertable():
    """The checklist's "delete line" maps to task.delete, which has to exist
    as a command like the other three."""
    import app.commands.handlers  # noqa: F401 — triggers registration
    from app.commands.registry import get_command_registry

    commands = {c["name"]: c for c in get_command_registry().list_commands()}
    assert "task.delete" in commands
    assert commands["task.delete"]["revertable"] is True
