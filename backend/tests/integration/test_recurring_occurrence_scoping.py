"""
Integration tests for recurring-event/task completion & edit-scope.

Every occurrence of a recurring `Schedule` shares the root row's id (see
`RecurrenceService.generate_instances`), so a plain update/complete used to
mutate every occurrence at once — there was no way to say "just this one".
The same problem existed for a `Task` checklist item linked to a recurring
event (`related_event_id`): one DB row, one `status`, shared by every
occurrence.

This covers both fixes at the command layer (the path the AI tools and the
REST API both go through):

  Schedule — `schedule.update` now requires `original_start_time`/
  `edit_scope` when the target is recurring, and routes through
  `ScheduleService.update_instance()` (which already existed but nothing
  called before this).

  Task — `task.update`/`task.complete` now require `occurrence_start_time`/
  `edit_scope` when the task is linked to a recurring event, and route
  through the new `TaskService.update_task_occurrence()`/
  `complete_task_occurrence()`, which materialize a per-occurrence
  exception row (mirroring Schedule's own exception mechanism) on first
  write to one occurrence.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.ai.agents.tool_context import ToolContext
from app.commands.registry import get_command_registry
from app.commands.schemas import Command
from app.models import Schedule, ScheduleType, Task
from app.services.calendar_items import CalendarItemService

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

TITLE_PREFIX = "[test-occurrence-scope] "


@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        # Tasks first: exception rows FK to their template, which FKs to
        # the schedule.
        await db.execute(delete(Task).where(Task.title.startswith(TITLE_PREFIX)))
        await db.execute(delete(Schedule).where(Schedule.title.startswith(TITLE_PREFIX)))
        await db.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def ctx(async_db):
    context = ToolContext(user_id=TEST_USER_ID, async_db=async_db)
    yield context
    context.close()


@pytest_asyncio.fixture
async def recurring_schedule(async_db):
    """A WEEKLY event with three occurrences inside the test window."""
    start = datetime.now(timezone.utc).replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=1)
    schedule = Schedule(
        user_id=TEST_USER_ID,
        title=f"{TITLE_PREFIX}Weekly practice",
        type=ScheduleType.PERSONAL,
        start_time=start,
        end_time=start + timedelta(minutes=45),
        recurrence_rule={"freq": "WEEKLY", "interval": 1, "tzid": "UTC"},
    )
    async_db.add(schedule)
    await async_db.commit()
    await async_db.refresh(schedule)
    return schedule


async def _run(ctx: ToolContext, command_name: str, args: dict):
    command = Command(
        command_name=command_name, args=args, requested_by=ctx.user_id, source="AI",
    )
    return await get_command_registry().execute(command, ctx)


# ============================================================================
# Schedule: schedule.update requires scope on a recurring target
# ============================================================================

@pytest.mark.asyncio
async def test_schedule_update_command_requires_scope_for_recurring(ctx, recurring_schedule):
    result = await _run(ctx, "schedule.update", {
        "schedule_id": str(recurring_schedule.id),
        "description": "should be rejected — no scope given",
    })
    assert result.success is False
    assert "recurring" in result.error.lower()
    assert "edit_scope" in result.error


@pytest.mark.asyncio
async def test_schedule_update_command_completion_only_defaults_to_this_only(
    async_db, ctx, recurring_schedule
):
    """Marking done/not done never needs edit_scope — occurrence_start_time
    alone is enough, and only that occurrence diverges."""
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)

    result = await _run(ctx, "schedule.update", {
        "schedule_id": str(recurring_schedule.id),
        "is_completed": True,
        "original_start_time": occ1.isoformat(),
    })
    assert result.success is True, result.error
    assert result.data["id"] != str(recurring_schedule.id)

    from app.database import SessionLocal
    from app.services.recurrence import RecurrenceService

    db = SessionLocal()
    try:
        root = db.query(Schedule).filter(Schedule.id == recurring_schedule.id).first()
        instances = RecurrenceService().generate_instances(
            root=root, range_start=occ1 - timedelta(days=1), range_end=occ2 + timedelta(days=1), db=db,
        )
    finally:
        db.close()

    def _parsed(value: str) -> datetime:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    by_start = {_parsed(i["start_time"]): i for i in instances}
    assert by_start[occ1]["is_completed"] is True
    assert by_start[occ2]["is_completed"] is False


@pytest.mark.asyncio
async def test_schedule_update_command_this_only_isolates_occurrence(async_db, ctx, recurring_schedule):
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)

    result = await _run(ctx, "schedule.update", {
        "schedule_id": str(recurring_schedule.id),
        "description": "occ1 only",
        "is_completed": True,
        "original_start_time": occ1.isoformat(),
        "edit_scope": "this_only",
    })
    assert result.success is True, result.error
    # The exception row is a different id than the root.
    assert result.data["id"] != str(recurring_schedule.id)

    # ScheduleService is sync — read back through the recurrence expansion
    # the way the calendar grid does, via a sync session for this one check.
    from app.database import SessionLocal
    from app.services.recurrence import RecurrenceService

    db = SessionLocal()
    try:
        root = db.query(Schedule).filter(Schedule.id == recurring_schedule.id).first()
        instances = RecurrenceService().generate_instances(
            root=root, range_start=occ1 - timedelta(days=1), range_end=occ2 + timedelta(days=1), db=db,
        )
    finally:
        db.close()

    # Virtual-instance dicts don't consistently carry a UTC offset in
    # `start_time` (an exception-backed instance's string does, a purely
    # virtual one's doesn't) — parse rather than string-match so this isn't
    # sensitive to that.
    def _parsed(value: str) -> datetime:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    by_start = {_parsed(i["start_time"]): i for i in instances}
    assert by_start[occ1]["is_completed"] is True
    assert by_start[occ1]["description"] == "occ1 only"
    assert by_start[occ2]["is_completed"] is False
    assert by_start[occ2]["description"] is None


@pytest.mark.asyncio
async def test_schedule_update_command_non_recurring_needs_no_scope(async_db, ctx):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    schedule = Schedule(
        user_id=TEST_USER_ID,
        title=f"{TITLE_PREFIX}One-off",
        type=ScheduleType.PERSONAL,
        start_time=start,
        end_time=start + timedelta(hours=1),
    )
    async_db.add(schedule)
    await async_db.commit()
    await async_db.refresh(schedule)

    result = await _run(ctx, "schedule.update", {
        "schedule_id": str(schedule.id),
        "description": "no scope needed, not recurring",
    })
    assert result.success is True, result.error
    assert result.data["id"] == str(schedule.id)


# ============================================================================
# Task: task.update/task.complete require scope when linked to a recurring
# event, and isolate completion per occurrence.
# ============================================================================

@pytest.mark.asyncio
async def test_task_complete_command_requires_scope_for_recurring_linked_task(ctx, recurring_schedule):
    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Checklist item",
        "related_event_id": str(recurring_schedule.id),
    })
    assert task_result.success is True, task_result.error

    result = await _run(ctx, "task.complete", {"task_id": task_result.data["id"]})
    assert result.success is False
    assert "recurring" in result.error.lower()
    assert "occurrence_start_time" in result.error


@pytest.mark.asyncio
async def test_task_complete_command_defaults_to_this_only_without_edit_scope(
    ctx, recurring_schedule
):
    """Completing never asks for a scope — occurrence_start_time alone is
    enough, edit_scope is auto-filled as this_only."""
    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Auto-scoped complete",
        "related_event_id": str(recurring_schedule.id),
    })
    result = await _run(ctx, "task.complete", {
        "task_id": task_result.data["id"],
        "occurrence_start_time": recurring_schedule.start_time.isoformat(),
    })
    assert result.success is True, result.error
    assert result.data["status"] == "done"


@pytest.mark.asyncio
async def test_task_update_command_status_only_defaults_to_this_only(ctx, recurring_schedule):
    """A status-only update (the generic path a UI's plain toggle might use
    instead of task.complete) gets the same auto-default as task.complete."""
    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Status-only toggle",
        "related_event_id": str(recurring_schedule.id),
    })
    result = await _run(ctx, "task.update", {
        "task_id": task_result.data["id"],
        "status": "done",
        "occurrence_start_time": recurring_schedule.start_time.isoformat(),
    })
    assert result.success is True, result.error
    assert result.data["status"] == "done"

    # A field edit alongside status, though, still needs edit_scope.
    result2 = await _run(ctx, "task.update", {
        "task_id": task_result.data["id"],
        "status": "todo",
        "description": "also editing a field",
        "occurrence_start_time": recurring_schedule.start_time.isoformat(),
    })
    assert result2.success is False
    assert "edit_scope" in result2.error


@pytest.mark.asyncio
async def test_task_complete_command_this_only_does_not_leak_to_other_occurrences(
    async_db, ctx, recurring_schedule
):
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)

    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}10 từ mới",
        "related_event_id": str(recurring_schedule.id),
    })
    task_id = task_result.data["id"]

    complete_result = await _run(ctx, "task.complete", {
        "task_id": task_id,
        "occurrence_start_time": occ1.isoformat(),
        "edit_scope": "this_only",
    })
    assert complete_result.success is True, complete_result.error
    assert complete_result.data["status"] == "done"

    checklist_svc = CalendarItemService(async_db)
    occ1_view = await checklist_svc.get_event_checklist(
        TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1
    )
    occ2_view = await checklist_svc.get_event_checklist(
        TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ2
    )
    assert occ1_view[0].status.value == "done"
    assert occ2_view[0].status.value != "done"
    # Both views present under the *template*'s id — never the exception's
    # own id — so a caller doesn't need to know which occurrence has
    # diverged before writing back.
    assert str(occ1_view[0].id) == task_id
    assert str(occ2_view[0].id) == task_id


@pytest.mark.asyncio
async def test_task_complete_command_all_scope_updates_template_not_existing_exceptions(
    async_db, ctx, recurring_schedule
):
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)
    occ3 = occ1 + timedelta(weeks=2)

    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}10 từ mới (all-scope)",
        "related_event_id": str(recurring_schedule.id),
    })
    task_id = task_result.data["id"]

    # occ1 diverges on its own first.
    r1 = await _run(ctx, "task.complete", {
        "task_id": task_id, "occurrence_start_time": occ1.isoformat(), "edit_scope": "this_only",
    })
    assert r1.success is True, r1.error

    # 'all' completes the template — every occurrence without its own
    # exception should now read as done, but occ1's own exception must be
    # untouched by this (it was already done, for its own reason).
    r2 = await _run(ctx, "task.complete", {
        "task_id": task_id, "occurrence_start_time": occ2.isoformat(), "edit_scope": "all",
    })
    assert r2.success is True, r2.error

    checklist_svc = CalendarItemService(async_db)
    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    occ2_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ2)
    occ3_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ3)
    assert occ1_view[0].status.value == "done"
    assert occ2_view[0].status.value == "done"
    assert occ3_view[0].status.value == "done"  # never touched directly, reads the template


@pytest.mark.asyncio
async def test_task_command_not_linked_needs_no_scope(ctx):
    task_result = await _run(ctx, "task.create", {"title": f"{TITLE_PREFIX}Standalone one-off"})
    assert task_result.success is True

    complete_result = await _run(ctx, "task.complete", {"task_id": task_result.data["id"]})
    assert complete_result.success is True, complete_result.error
    assert complete_result.data["status"] == "done"


@pytest.mark.asyncio
async def test_task_command_linked_to_non_recurring_event_needs_no_scope(async_db, ctx):
    start = datetime.now(timezone.utc) + timedelta(days=3)
    schedule = Schedule(
        user_id=TEST_USER_ID,
        title=f"{TITLE_PREFIX}One-off meeting",
        type=ScheduleType.PERSONAL,
        start_time=start,
        end_time=start + timedelta(hours=1),
    )
    async_db.add(schedule)
    await async_db.commit()
    await async_db.refresh(schedule)

    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Bring passport", "related_event_id": str(schedule.id),
    })
    assert task_result.success is True

    complete_result = await _run(ctx, "task.complete", {"task_id": task_result.data["id"]})
    assert complete_result.success is True, complete_result.error


# ============================================================================
# Task: task.create / task.delete scoping on a recurring event's checklist
# ============================================================================

@pytest.mark.asyncio
async def test_task_create_without_scope_shows_on_every_occurrence(
    async_db, ctx, recurring_schedule
):
    """Today's default, unchanged: a plain create is series-wide."""
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)

    result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Series-wide item", "related_event_id": str(recurring_schedule.id),
    })
    assert result.success is True, result.error

    checklist_svc = CalendarItemService(async_db)
    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    occ2_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ2)
    assert [t.title for t in occ1_view] == [f"{TITLE_PREFIX}Series-wide item"]
    assert [t.title for t in occ2_view] == [f"{TITLE_PREFIX}Series-wide item"]


@pytest.mark.asyncio
async def test_task_create_this_only_shows_on_just_that_occurrence(
    async_db, ctx, recurring_schedule
):
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)

    result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Occurrence-only item",
        "related_event_id": str(recurring_schedule.id),
        "occurrence_start_time": occ1.isoformat(),
        "edit_scope": "this_only",
    })
    assert result.success is True, result.error

    checklist_svc = CalendarItemService(async_db)
    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    occ2_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ2)
    assert [t.title for t in occ1_view] == [f"{TITLE_PREFIX}Occurrence-only item"]
    assert [t.title for t in occ2_view] == []

    # Deleting it needs no scope — there's only ever one occurrence it could mean.
    delete_result = await _run(ctx, "task.delete", {"task_id": result.data["id"]})
    assert delete_result.success is True, delete_result.error
    assert delete_result.data["deleted"] is True


@pytest.mark.asyncio
async def test_task_delete_command_requires_scope_for_recurring_template(
    ctx, recurring_schedule
):
    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Delete-needs-scope", "related_event_id": str(recurring_schedule.id),
    })
    result = await _run(ctx, "task.delete", {"task_id": task_result.data["id"]})
    assert result.success is False
    assert "recurring" in result.error.lower()
    assert "edit_scope" in result.error


@pytest.mark.asyncio
async def test_task_delete_this_only_hides_from_one_occurrence_keeps_template(
    async_db, ctx, recurring_schedule
):
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)

    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Delete this_only", "related_event_id": str(recurring_schedule.id),
    })
    task_id = task_result.data["id"]

    delete_result = await _run(ctx, "task.delete", {
        "task_id": task_id, "occurrence_start_time": occ1.isoformat(), "edit_scope": "this_only",
    })
    assert delete_result.success is True, delete_result.error
    assert delete_result.data["deleted"] is False

    checklist_svc = CalendarItemService(async_db)
    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    occ2_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ2)
    assert occ1_view == []
    assert [t.title for t in occ2_view] == [f"{TITLE_PREFIX}Delete this_only"]

    # The template itself is untouched — a plain fetch (no occurrence) still
    # finds it, and task.complete still works on the other occurrence.
    complete_result = await _run(ctx, "task.complete", {
        "task_id": task_id, "occurrence_start_time": occ2.isoformat(),
    })
    assert complete_result.success is True, complete_result.error


@pytest.mark.asyncio
async def test_task_delete_all_removes_from_every_occurrence(
    async_db, ctx, recurring_schedule
):
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)

    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Delete all", "related_event_id": str(recurring_schedule.id),
    })
    task_id = task_result.data["id"]

    delete_result = await _run(ctx, "task.delete", {
        "task_id": task_id, "occurrence_start_time": occ1.isoformat(), "edit_scope": "all",
    })
    assert delete_result.success is True, delete_result.error
    assert delete_result.data["deleted"] is True

    checklist_svc = CalendarItemService(async_db)
    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    occ2_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ2)
    assert occ1_view == []
    assert occ2_view == []


@pytest.mark.asyncio
async def test_task_delete_this_only_revert_restores_the_occurrence(
    async_db, ctx, recurring_schedule
):
    occ1 = recurring_schedule.start_time

    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Delete then undo", "related_event_id": str(recurring_schedule.id),
    })
    task_id = task_result.data["id"]

    delete_result = await _run(ctx, "task.delete", {
        "task_id": task_id, "occurrence_start_time": occ1.isoformat(), "edit_scope": "this_only",
    })
    assert delete_result.success is True, delete_result.error

    revert_result = await get_command_registry().revert_command(delete_result.action_id, ctx)
    assert revert_result.success is True, revert_result.error

    checklist_svc = CalendarItemService(async_db)
    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    assert [t.title for t in occ1_view] == [f"{TITLE_PREFIX}Delete then undo"]


@pytest.mark.asyncio
async def test_task_this_only_created_item_can_be_toggled_repeatedly(
    async_db, ctx, recurring_schedule
):
    """Regression: `_resolve_occurrence_target`'s `this_only` branch used to
    assume `task_id` always named a plain template, and looked for an
    exception keyed on `recurrence_id == task_id`. For a row already scoped
    to one occurrence at creation (`original_start_time` set, no
    `recurrence_id` of its own), that lookup can never match — every
    complete/un-complete created a fresh, unreachable exception instead of
    ever landing back on the row the checklist actually reads, so the
    checkbox silently reset the instant you refetched."""
    occ1 = recurring_schedule.start_time

    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Toggle this-only item",
        "related_event_id": str(recurring_schedule.id),
        "occurrence_start_time": occ1.isoformat(),
        "edit_scope": "this_only",
    })
    assert task_result.success is True, task_result.error
    task_id = task_result.data["id"]

    checklist_svc = CalendarItemService(async_db)

    complete_result = await _run(ctx, "task.complete", {
        "task_id": task_id, "occurrence_start_time": occ1.isoformat(),
    })
    assert complete_result.success is True, complete_result.error
    # Completing an already-occurrence-scoped row must land on that same
    # row, never a new one.
    assert complete_result.data["id"] == task_id

    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    assert len(occ1_view) == 1
    assert occ1_view[0].status.value == "done"

    # Un-tick: task.update with status=todo, same occurrence scope.
    uncomplete_result = await _run(ctx, "task.update", {
        "task_id": task_id, "status": "todo", "occurrence_start_time": occ1.isoformat(),
    })
    assert uncomplete_result.success is True, uncomplete_result.error
    assert uncomplete_result.data["id"] == task_id

    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    assert len(occ1_view) == 1
    assert occ1_view[0].status.value == "todo"


# ============================================================================
# Task: a series-wide checklist item's due date tracks the occurrence being
# viewed, instead of freezing whichever occurrence it was created from.
# ============================================================================

@pytest.mark.asyncio
async def test_series_wide_item_without_due_date_tracks_each_occurrence(
    async_db, ctx, recurring_schedule
):
    """Regression: `useEventChecklist.addTask` used to always send
    `due_date = <the currently-open occurrence's end time>` for a
    series-wide item too — a single DB column, so every occurrence showed
    that same frozen date forever, no matter which occurrence's checklist
    was actually open. The frontend fix stops defaulting a series-wide
    item's due_date at all; this is the backend half — filling it in fresh,
    per occurrence, on read."""
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)
    duration = recurring_schedule.end_time - recurring_schedule.start_time

    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}No frozen date", "related_event_id": str(recurring_schedule.id),
    })
    assert task_result.success is True, task_result.error

    checklist_svc = CalendarItemService(async_db)
    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    occ2_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ2)

    # due_date comes back naive (local wall-clock, matching every other
    # due_date — see _event_occurrence_end_time); the fixture's tzid is
    # UTC, so the naive value is numerically identical to the aware one.
    assert occ1_view[0].due_date == (occ1 + duration).replace(tzinfo=None)
    assert occ2_view[0].due_date == (occ2 + duration).replace(tzinfo=None)
    assert occ1_view[0].due_date != occ2_view[0].due_date


@pytest.mark.asyncio
async def test_series_wide_item_with_explicit_due_date_is_never_overridden(
    async_db, ctx, recurring_schedule
):
    """The per-occurrence default (previous test) only fills in a *missing*
    due date — an explicit one, set on purpose, must read back identically
    on every occurrence."""
    occ1 = recurring_schedule.start_time
    occ2 = occ1 + timedelta(weeks=1)
    explicit_due = (occ1 + timedelta(days=30)).date().isoformat()

    task_result = await _run(ctx, "task.create", {
        "title": f"{TITLE_PREFIX}Explicit due date",
        "related_event_id": str(recurring_schedule.id),
        "due_date": explicit_due,
    })
    assert task_result.success is True, task_result.error

    checklist_svc = CalendarItemService(async_db)
    occ1_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ1)
    occ2_view = await checklist_svc.get_event_checklist(TEST_USER_ID, recurring_schedule.id, occurrence_start_time=occ2)

    assert occ1_view[0].due_date == occ2_view[0].due_date
    assert occ1_view[0].due_date.date().isoformat() == explicit_due


# ============================================================================
# ScheduleService.get_schedule_by_id must report is_recurring/recurrence
# correctly — every single-schedule endpoint (and the mezon bot's
# taskActions.prepareTaskWrite, via cortex.getSchedule) depends on it to
# decide whether a checklist write needs an occurrence/scope at all.
# ============================================================================

def test_get_schedule_by_id_reports_is_recurring(recurring_schedule):
    """Regression: `Schedule` (the ORM model) has no `is_recurring`/
    `recurrence` attribute — only `recurrence_rule`. Every endpoint that
    returns a single `Schedule` straight through `ScheduleResponse`
    (GET/POST/PUT `/schedules/*`, all going through `get_schedule_by_id` or
    a sibling that shares `_attach_google_sync_flags`) used to silently
    default those two fields to `False`/`None` via Pydantic's
    `from_attributes` fallback — never an error, just wrong, for every
    recurring schedule. The mezon bot's `taskActions.prepareTaskWrite`
    calls exactly this endpoint (`cortex.getSchedule`) to decide whether a
    checklist task's event recurs before asking which occurrence; reading
    `false` here meant it never asked, and the backend then rejected the
    bare completion/snooze write with a 422 for missing
    `occurrence_start_time`/`edit_scope`."""
    from app.database import SessionLocal
    from app.services.schedule_service import ScheduleService

    db = SessionLocal()
    try:
        fetched = ScheduleService(db).get_schedule_by_id(recurring_schedule.id, TEST_USER_ID)
        assert fetched is not None
        assert fetched.is_recurring is True
        assert fetched.recurrence == recurring_schedule.recurrence_rule
    finally:
        db.close()


@pytest.mark.asyncio
async def test_schedule_update_command_response_reports_is_recurring(
    async_db, ctx, recurring_schedule
):
    """Same bug, on the write side: `update_instance`'s `all`/`this_and_after`
    branches return a raw `Schedule` too (`_update_instance_all`'s `root`,
    `_update_instance_this_and_after`'s `new_root`) — both go through
    `_attach_google_sync_flags`, so both get the same fix."""
    result = await _run(ctx, "schedule.update", {
        "schedule_id": str(recurring_schedule.id),
        "description": "still recurring after an all-scope edit",
        "original_start_time": recurring_schedule.start_time.isoformat(),
        "edit_scope": "all",
    })
    assert result.success is True, result.error

    from app.database import SessionLocal
    from app.services.schedule_service import ScheduleService

    db = SessionLocal()
    try:
        fetched = ScheduleService(db).get_schedule_by_id(recurring_schedule.id, TEST_USER_ID)
        assert fetched.is_recurring is True
    finally:
        db.close()
