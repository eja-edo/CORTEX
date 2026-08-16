"""
Availability — "is the user busy right now?" (6.1's need), "is it just a bad
time regardless of the calendar?" (quiet hours, 6.2), and "when's the user
next free?" (the range scan, Milestone 3.3).

`is_user_busy` stays a point-in-time query — it's what the Attention Gate
(6.1) needs on the hot path and a single indexed lookup is cheaper than
pulling a range and checking membership. `find_free_slots` is the range
version 3.3 asked for: both query the same `schedules` table under the same
"non-cancelled block owns this time" rule, so a definition change (e.g. what
counts as cancelled) only has one place to happen — `_schedule_intervals`.

A task never makes the user "busy" here. Only `schedules` does — a task has
a due date, not a time it occupies (2.5's Task vs Schedule boundary). Mixing
the two back together would reintroduce exactly the bug 2.5/2.6 removed:
every overdue task would make the user look busy, and `find_free_slots`
would report someone with 40 overdue tasks as having no free time at all.

`should_stay_quiet[_async|_sync]` is what the Gate actually calls — it's
`is_user_busy` OR "inside the user's configured quiet hours" (6.2), so the
Gate's step 3 doesn't need to know there are two separate signals behind
"is now a bad time".
"""

from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Schedule
from app.services.user_preferences import get_preferences_async, get_preferences_sync

DEFAULT_MIN_SLOT = timedelta(minutes=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _busy_stmt(user_id: UUID, at: datetime):
    return (
        select(Schedule.id)
        .where(
            Schedule.user_id == user_id,
            Schedule.is_cancelled.is_(False),
            Schedule.start_time <= at,
            Schedule.end_time > at,
        )
        .limit(1)
    )


async def is_user_busy(session: AsyncSession, user_id: UUID, at: datetime | None = None) -> bool:
    """Is `user_id` inside a schedule block at `at` (default: now)?

    Cancelled schedules don't count as busy — cancelling a meeting is what
    frees the slot it held. Recurring exceptions are just rows in the same
    table by the time they land here, so no separate handling is needed.
    """
    result = await session.execute(_busy_stmt(user_id, at or _now()))
    return result.first() is not None


def is_user_busy_sync(session: Session, user_id: UUID, at: datetime | None = None) -> bool:
    """Sync twin of `is_user_busy`, for callers holding a plain `Session`
    (the Attention Gate's sync path — see its module docstring)."""
    result = session.execute(_busy_stmt(user_id, at or _now()))
    return result.first() is not None


def _schedule_intervals_stmt(user_id: UUID, start: datetime, end: datetime):
    """Non-cancelled schedules that overlap `[start, end)` at all — the same
    "busy" definition `_busy_stmt` uses, widened from a point to a range."""
    return (
        select(Schedule.start_time, Schedule.end_time)
        .where(
            Schedule.user_id == user_id,
            Schedule.is_cancelled.is_(False),
            Schedule.start_time < end,
            Schedule.end_time > start,
        )
        .order_by(Schedule.start_time)
    )


def _gaps(
    busy: list[tuple[datetime, datetime]],
    start: datetime,
    end: datetime,
    min_duration: timedelta,
) -> list[tuple[datetime, datetime]]:
    """Free intervals in `[start, end)` once `busy` is subtracted out.

    Pure and DB-free on purpose — merging overlapping/back-to-back meetings
    and inverting them into gaps is the part worth unit-testing directly,
    without standing up a session for every case.
    """
    merged: list[list[datetime]] = []
    for busy_start, busy_end in sorted(busy):
        clipped_start, clipped_end = max(busy_start, start), min(busy_end, end)
        if clipped_start >= clipped_end:
            continue
        if merged and clipped_start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], clipped_end)
        else:
            merged.append([clipped_start, clipped_end])

    free: list[tuple[datetime, datetime]] = []
    cursor = start
    for busy_start, busy_end in merged:
        if busy_start - cursor >= min_duration:
            free.append((cursor, busy_start))
        cursor = max(cursor, busy_end)
    if end - cursor >= min_duration:
        free.append((cursor, end))
    return free


async def find_free_slots(
    session: AsyncSession,
    user_id: UUID,
    start: datetime,
    end: datetime,
    min_duration: timedelta = DEFAULT_MIN_SLOT,
) -> list[tuple[datetime, datetime]]:
    """Free intervals of at least `min_duration` inside `[start, end)`.

    An empty or reversed range (`end <= start`) has no slots in it — asking
    is a caller bug, not a "no schedules" answer, but returning `[]` rather
    than raising keeps this a query function, not a validator.
    """
    if end <= start:
        return []
    result = await session.execute(_schedule_intervals_stmt(user_id, start, end))
    busy = [(row.start_time, row.end_time) for row in result.all()]
    return _gaps(busy, start, end, min_duration)


def is_in_quiet_hours(start: time | None, end: time | None, at: datetime) -> bool:
    """Is `at`'s time-of-day (UTC) inside the daily `[start, end)` window?

    Both null means quiet hours aren't configured — never quiet. Handles
    the overnight case (`start > end`, e.g. 22:00-07:00) by treating it as
    "outside `[end, start)`" instead of the same-day comparison, which
    would otherwise be permanently false for any window that crosses
    midnight.
    """
    if start is None or end is None:
        return False
    now = at.astimezone(timezone.utc).time() if at.tzinfo else at.time()
    if start <= end:
        return start <= now < end
    return now >= start or now < end


async def should_stay_quiet_async(session: AsyncSession, user_id: UUID, at: datetime | None = None) -> bool:
    """The Gate's actual step-3 predicate: busy, or inside quiet hours."""
    at = at or _now()
    if await is_user_busy(session, user_id, at):
        return True
    prefs = await get_preferences_async(session, user_id)
    if prefs is None:
        return False
    return is_in_quiet_hours(prefs.quiet_hours_start, prefs.quiet_hours_end, at)


def should_stay_quiet_sync(session: Session, user_id: UUID, at: datetime | None = None) -> bool:
    """Sync twin of `should_stay_quiet_async`."""
    at = at or _now()
    if is_user_busy_sync(session, user_id, at):
        return True
    prefs = get_preferences_sync(session, user_id)
    if prefs is None:
        return False
    return is_in_quiet_hours(prefs.quiet_hours_start, prefs.quiet_hours_end, at)
