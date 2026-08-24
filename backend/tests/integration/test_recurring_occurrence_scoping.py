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
