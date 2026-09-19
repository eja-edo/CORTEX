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
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Schedule, Task
from app.schemas import CalendarItem
from app.services.recurrence import RecurrenceService
from app.utils.logger import get_logger

logger = get_logger(__name__)


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


def _as_occurrence_view(template: Task, exception: Task) -> Task:
    """`exception`'s fields, under `template`'s id — a transient object,
    never added to the session. See `get_event_checklist`'s docstring for
    why the id must stay the template's, not the exception row's own.

    `is_exception` (and every other column not set below) must be passed
    explicitly: a bare `Task(...)` never flushed through the session skips
    the column-level Python defaults SQLAlchemy normally applies at INSERT,
    so an omitted attribute reads back as `None` — not "unset, use the
    default" — which fails `TaskResponse.is_exception: bool`'s (non-Optional)
    validation on serialization.
    """
    return Task(
        id=template.id,
        user_id=exception.user_id,
        # Bắt buộc truyền: xem docstring ở trên — cột không set sẽ đọc ra
        # `None` chứ không phải giá trị mặc định, và `project_id` không
        # nullable nên nó sẽ trượt validation lúc serialize.
        project_id=exception.project_id,
        title=exception.title,
        status=exception.status,
        due_date=exception.due_date,
        priority=exception.priority,
        description=exception.description,
        related_event_id=exception.related_event_id,
        parent_task_id=exception.parent_task_id,
        source_conversation_id=exception.source_conversation_id,
        source_message_id=exception.source_message_id,
        completed_at=exception.completed_at,
        is_exception=False,
        is_cancelled=False,
        created_at=exception.created_at,
        updated_at=exception.updated_at,
    )


def _with_default_due_date(row: Task, due_date: datetime) -> Task:
    """`row`, with `due_date` filled in — a transient copy, never added to
    the session (same reasoning as `_as_occurrence_view`: this must never be
    mistaken for a real write). Used when a checklist item never had its own
    due date set (`due_date IS NULL`, template or exception) and is being
    viewed for a specific occurrence — see `get_event_checklist`."""
    return Task(
        id=row.id,
        user_id=row.user_id,
        project_id=row.project_id,
        title=row.title,
        status=row.status,
        due_date=due_date,
        priority=row.priority,
        description=row.description,
        related_event_id=row.related_event_id,
        parent_task_id=row.parent_task_id,
        source_conversation_id=row.source_conversation_id,
        source_message_id=row.source_message_id,
        completed_at=row.completed_at,
        is_exception=row.is_exception,
        is_cancelled=row.is_cancelled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


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
        tasks = await self.get_tasks_in_range(user_id, range_start.date(), range_end.date())

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

    async def get_tasks_in_range(self, user_id: UUID, range_start: date, range_end: date) -> list[Task]:
        """Việc của một khoảng ngày — **không lọc trạng thái**.

        Công khai vì nó là định nghĩa dùng chung của *"việc của ngày X"*:
        lưới lịch vẽ từ đây, và `StateEvaluator._publish_day_review` đếm từ
        đây. Hai chỗ tự viết truy vấn riêng là hai chỗ sẽ trôi khỏi nhau —
        và chúng đã trôi: bản tổng kết cuối ngày từng chọn *mọi* việc đang
        mở, nên nó nói "còn 10 việc" trong khi màn hình cùng ngày hiện 1.

        Đã xong và chưa xong đều trả về. Người gọi tự tách theo `status` —
        một bản tổng kết cần cả hai nửa để nói được tỷ lệ.

        Tasks with no `due_date` are left out: they have no day to sit on.
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
                # Occurrence-exception rows (per-occurrence completion on a
                # recurring event's checklist task — see `Task.recurrence_id`)
                # are resolved by `get_event_checklist`, never drawn directly
                # on the calendar grid.
                Task.recurrence_id.is_(None),
            )
            .order_by(Task.due_date.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_event_checklist(
        self,
        user_id: UUID,
        event_id: UUID,
        occurrence_start_time: datetime | None = None,
    ) -> list[Task]:
        """The tasks attached to one event — the checklist widget's query.

        Read straight from `tasks`; the event's `description` is never parsed
        and never used to store checklist state. Rendering tasks as a
        checklist is one-way on purpose: the reverse (parsing lines back into
        tasks) needs a diff on every keystroke, and one missed line leaves an
        orphan task that the Attention Gate will then nag about.

        `occurrence_start_time` matters only when the linked event is
        recurring, in three ways:

        1. A plain template (`related_event_id == event_id`,
           `recurrence_id IS NULL`, `original_start_time IS NULL`) is
           swapped for its per-occurrence exception row if one exists for
           this occurrence (created lazily by
           `TaskService.complete_task_occurrence`/`update_task_occurrence`),
           exactly mirroring how `RecurrenceService.generate_instances`
           resolves a `Schedule` exception for one occurrence. No exception
           yet -> the template itself is returned unchanged, same as an
           un-overridden `Schedule` occurrence still reads the root's
           `is_completed` — so an `all`-scope edit (which writes the
           template) keeps showing on every occurrence that hasn't diverged.
        2. That exception is skipped entirely (not substituted, not shown)
           when it's `is_cancelled` — a `this_only` *delete* on the
           template: this one occurrence loses the item, every other
           occurrence keeps reading the still-intact template. Mirrors
           `RecurrenceService.generate_instances` dropping a cancelled
           `Schedule` instance the same way.
        3. A row created with `edit_scope=this_only` (`original_start_time`
           set, `recurrence_id` NULL — see `Task.original_start_time`'s
           docstring) only appears when it matches the occurrence being
           asked for; it's invisible to every other occurrence and to a
           caller not viewing any specific occurrence at all.
        4. A checklist item with no due date of its own (`due_date IS
           NULL` — never explicitly set, on either a template or an
           exception) shows this occurrence's own end time instead of no
           date at all. A series-wide item's "+ Add" panel doesn't ask
           which day it's for (there is no single day — it's every
           occurrence), so it can't write a real `due_date` at creation the
           way a one-off or `this_only` item's does (see `TaskService
           .create_task`'s `scoped_to_one_occurrence`, and `useEventChecklist
           .addTask` on the frontend). Without this, every occurrence showed
           whichever single date happened to be baked in at creation time —
           every newly-added series-wide item landing on the same day
           regardless of which occurrence's checklist you actually opened
           it from. An item with a real `due_date` (the user set one
           explicitly, `all`-scope) is never touched here — explicit beats
           default, on every occurrence.

        The id an exception is substituted under is always the *template's*
        — never the exception row's own id — so a caller writing back
        (`PATCH/POST /tasks/{id}?occurrence_start_time=...`) always addresses
        the same stable id regardless of whether this occurrence has
        diverged yet. Same convention `generate_instances` uses for Schedule
        (every virtual instance reports the root's id). The substitute is a
        transient, session-detached `Task` — never `session.add()`ed, so it
        can't be flushed and can't collide with the exception's real row.
        """
        rows = list(
            (
                await self.session.execute(
                    select(Task)
                    .where(
                        Task.user_id == user_id,
                        Task.related_event_id == event_id,
                        Task.recurrence_id.is_(None),
                    )
                    .order_by(Task.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        # An occurrence-scoped row (case 3 above) only belongs to the
        # occurrence it names — everywhere else, and when no occurrence is
        # specified at all, it doesn't exist.
        templates = [
            t for t in rows
            if t.original_start_time is None or t.original_start_time == occurrence_start_time
        ]
        if occurrence_start_time is None or not templates:
            return templates

        occurrence_end_time = await self._event_occurrence_end_time(event_id, occurrence_start_time)

        plain_templates = [t for t in templates if t.original_start_time is None]
        if not plain_templates:
            return self._with_default_due_dates(templates, occurrence_end_time)

        exceptions_stmt = select(Task).where(
            Task.user_id == user_id,
            Task.recurrence_id.in_([t.id for t in plain_templates]),
            Task.original_start_time == occurrence_start_time,
        )
        exceptions_by_template = {
            e.recurrence_id: e
            for e in (await self.session.execute(exceptions_stmt)).scalars().all()
        }
        results = []
        for t in templates:
            exception = exceptions_by_template.get(t.id)
            if exception is None:
                results.append(t)
            elif not exception.is_cancelled:
                results.append(_as_occurrence_view(t, exception))
            # else: cancelled for this occurrence — omitted.
        return self._with_default_due_dates(results, occurrence_end_time)

    async def _event_occurrence_end_time(
        self, event_id: UUID, occurrence_start_time: datetime,
    ) -> datetime | None:
        """This occurrence's own end time — `occurrence_start_time` plus the
        event's duration — for point 4 of `get_event_checklist`'s docstring.
        `None` if the event can't be found (nothing sensible to fall back
        to; case 4 then just doesn't apply).

        Naive on the way out, in the *event's own* `tzid` (its
        `recurrence_rule`, same default `RecurrenceService` itself falls
        back to): `Task.due_date` is deliberately a naive local-wall-clock
        column (see its own docstring), and every real `due_date` sitting
        next to this one in the same result list was written as the
        browser's local time — stripping tzinfo off a UTC value directly
        would silently shift it by the user's offset (the exact bug
        `recurrence.py`'s `_wire_utc` exists to dodge on the `Schedule`
        side), and could even land it on the wrong day.
        """
        event = (
            await self.session.execute(select(Schedule).where(Schedule.id == event_id))
        ).scalar_one_or_none()
        if event is None or event.start_time is None or event.end_time is None:
            return None
        result = occurrence_start_time + (event.end_time - event.start_time)
        tzid = (event.recurrence_rule or {}).get("tzid", "UTC")
        try:
            result = result.astimezone(ZoneInfo(tzid))
        except Exception:
            logger.warning("Unknown tzid %r on schedule %s; treating as UTC", tzid, event_id)
        return result.replace(tzinfo=None)

    @staticmethod
    def _with_default_due_dates(rows: list[Task], occurrence_end_time: datetime | None) -> list[Task]:
        if occurrence_end_time is None:
            return rows
        return [
            _with_default_due_date(t, occurrence_end_time) if t.due_date is None else t
            for t in rows
        ]
