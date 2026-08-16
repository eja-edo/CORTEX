"""
Availability — "is the user busy right now?" (seed of Milestone 3.3) plus
"is it just a bad time regardless of the calendar?" (quiet hours, 6.2).

`is_user_busy` is deliberately not the full free-slot query 3.3 describes (a
range scan returning every free/busy interval between two timestamps,
consumed by the AI Planner and by "when's the next free slot" prompts).
What exists here is the point-in-time predicate the Attention Gate (6.1)
actually needs: is the user in a meeting, or in a quiet-hours window, right
now. Both should end up calling the same underlying query as 3.3 — expand
this module into the range version when 3.3 is built, don't write a second
one next to it.

A task never makes `is_user_busy` `True`. Only `schedules` does — a task
has a due date, not a time it occupies (2.5's Task vs Schedule boundary).
Mixing the two back together here would reintroduce exactly the bug 2.5/2.6
removed: every overdue task would make the user look "busy".

`should_stay_quiet[_async|_sync]` is what the Gate actually calls — it's
`is_user_busy` OR "inside the user's configured quiet hours" (6.2), so the
Gate's step 3 doesn't need to know there are two separate signals behind
"is now a bad time".
"""

from datetime import datetime, time, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Schedule
from app.services.user_preferences import get_preferences_async, get_preferences_sync


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
