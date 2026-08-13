"""
Unified calendar feed (Milestone 2.6).

The calendar shows schedules and tasks together, but they are stored apart
and they mean different things:

    A schedule **occupies** time. A task **consumes** it.

A meeting from 14:00–15:00 takes that hour. "Write the API spec, due Friday"
does not take Friday — it just has to be done before it. That distinction is
why tasks were given their own table in 2.5, and it is load-bearing beyond
the UI: free-slot planning (3.3) and interruptibility (6.2) both answer "is
the user busy?" by reading `schedules`. If tasks were projected into that
table, every task with a deadline would make the user look busy, planning
would return wrong answers, and the Attention Gate would go permanently
quiet — silently, with nothing to indicate a bug.

So this module **only reads**. It writes nothing, and in particular it never
creates a `schedules` row from a task. There is no projection and no sync in
either direction; the calendar queries both tables and merges in memory.
"""

import asyncio
from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Schedule, Task
from app.schemas import CalendarItem
from app.services.recurrence import RecurrenceService


def _schedule_status(schedule: Schedule) -> str:
    """`schedules` has booleans rather than a status enum; flatten them into
    the one string the unified shape exposes."""
    if schedule.is_cancelled:
        return "cancelled"
    if schedule.is_completed:
        return "completed"
    return "scheduled"


def schedule_to_item(schedule: Schedule) -> CalendarItem:
    return CalendarItem(
        id=schedule.id,
        kind="schedule",
        render_as="block",  # occupies a span in the time grid
        title=schedule.title,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        due_date=None,
        status=_schedule_status(schedule),
        location=schedule.location,
    )


def _instance_dict_to_item(instance: dict) -> CalendarItem:
    """A virtual/materialized occurrence from `RecurrenceService.generate_instances`
    — same unified shape as `schedule_to_item`, just built from a dict instead
    of an ORM row (every occurrence of one series shares the series' id;
    that's `generate_instances`'s existing convention, not new here)."""
    return CalendarItem(
        id=UUID(instance["id"]),
        kind="schedule",
        render_as="block",
        title=instance["title"],
        start_time=datetime.fromisoformat(instance["start_time"]),
        end_time=datetime.fromisoformat(instance["end_time"]),
        due_date=None,
        status="completed" if instance.get("is_completed") else "scheduled",
        location=instance.get("location"),
    )


def _expand_recurring_schedules_sync(
    user_id: UUID, range_start: datetime, range_end: datetime
) -> list[dict]:
    """Recurring root schedules, expanded into one dict per occurrence
    inside the window — mirrors the recurring half of
    `ScheduleService.list_schedules`. Runs in a worker thread (see
    `CalendarItemService._get_schedules`): `RecurrenceService` and the
    queries it needs (`Session.query`) are sync-only, and this module is
    otherwise fully async — calling them directly here would block the
    event loop for every request.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        recurrence_svc = RecurrenceService()
        roots = (
            db.query(Schedule)
            .filter(Schedule.user_id == user_id, Schedule.recurrence_id.is_(None))
            .all()
        )
        recurring_roots = [s for s in roots if recurrence_svc.is_recurring(s.recurrence_rule)]

        instances: list[dict] = []
        for root in recurring_roots:
            instances.extend(
                recurrence_svc.generate_instances(
                    root=root, range_start=range_start, range_end=range_end, db=db,
                )
            )
        return instances
    finally:
        db.close()


def task_to_item(task: Task) -> CalendarItem:
    return CalendarItem(
        id=task.id,
        kind="task",
        render_as="marker",  # a point in the day, never a span
        title=task.title,
        start_time=None,
        end_time=None,
        # Usually midnight of the due day; can carry a real time (e.g. an
        # event checklist item, see `useEventChecklist`). Passed through
        # as-is — `render_as="marker"` is what keeps this from ever being
        # drawn as a clock position, not the value itself.
        due_date=task.due_date,
        status=task.status.value,
        location=None,
    )


def _sort_key(item: CalendarItem) -> datetime:
    """Schedules sort by when they start, tasks by when they're due.

    Both are forced to UTC-aware first. `schedules.start_time` is a
    `timestamptz` and comes back aware, while a task's due date is a plain
    calendar day with no zone at all — comparing the two raw raises
    "can't compare offset-naive and offset-aware datetimes", which would
    500 any request that returned both kinds at once.
    """
    value = item.start_time or item.due_date or datetime.min
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class CalendarItemService:
    """Read-only. See the module docstring for why that is a hard rule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_items(
        self, user_id: UUID, range_start: datetime, range_end: datetime
    ) -> list[CalendarItem]:
        schedule_items = await self._get_schedules(user_id, range_start, range_end)
        tasks = await self._get_tasks(user_id, range_start.date(), range_end.date())

        items = schedule_items + [task_to_item(t) for t in tasks]
        items.sort(key=_sort_key)
        return items

    async def _get_schedules(
        self, user_id: UUID, range_start: datetime, range_end: datetime
    ) -> list[CalendarItem]:
        """Overlap, not containment: a meeting that starts before the window
        and ends inside it still occupies part of the visible days.

        A recurring schedule is stored as a single row (the series'
        anchor), so drawing rows 1:1 would show it only once no matter how
        many times it repeats. `recurrence_id.is_(None)` here excludes both
        that anchor row (expanded separately below, since its own
        `start_time` is just its first occurrence) and any already-edited
        single occurrence (recurrence_id set) — the latter gets pulled in
        by `_expand_recurring_schedules_sync`'s exception lookup instead,
        so counting it here too would draw it twice.
        """
        stmt = (
            select(Schedule)
            .where(
                Schedule.user_id == user_id,
                Schedule.start_time <= range_end,
                Schedule.end_time >= range_start,
                Schedule.is_cancelled.is_(False),
                Schedule.recurrence_id.is_(None),
            )
            .order_by(Schedule.start_time.asc())
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        recurrence_svc = RecurrenceService()
        standalone = [schedule_to_item(s) for s in rows if not recurrence_svc.is_recurring(s.recurrence_rule)]

        instances = await asyncio.to_thread(
            _expand_recurring_schedules_sync, user_id, range_start, range_end
        )
        return standalone + [_instance_dict_to_item(i) for i in instances]

    async def _get_tasks(self, user_id: UUID, range_start: date, range_end: date) -> list[Task]:
        """Tasks with no `due_date` are left out: they have no day to sit on.
        They are still real work — the "Hôm nay" screen (2.7) is where they
        surface, not the calendar grid.

        Bounds cover the *whole* day at each end — `due_date` can now carry a
        real time (see `models.Task.due_date`), so a task due at 23:00 on
        `range_end` must still be included, not cut off at that day's 00:00.
        """
        day_start = datetime.combine(range_start, time.min)
        day_end = datetime.combine(range_end, time.max)
        stmt = (
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.due_date.is_not(None),
                Task.due_date >= day_start,
                Task.due_date <= day_end,
            )
            .order_by(Task.due_date.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_event_checklist(self, user_id: UUID, event_id: UUID) -> list[Task]:
        """The tasks attached to one event — the checklist widget's query.

        Read straight from `tasks`; the event's `description` is never parsed
        and never used to store checklist state. Rendering tasks as a
        checklist is one-way on purpose: the reverse (parsing lines back into
        tasks) needs a diff on every keystroke, and one missed line leaves an
        orphan task that the Attention Gate will then nag about.
        """
        stmt = (
            select(Task)
            .where(Task.user_id == user_id, Task.related_event_id == event_id)
            .order_by(Task.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())
