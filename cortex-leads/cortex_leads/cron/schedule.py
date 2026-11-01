"""Cron slots (DESIGN §5.7 `cron`). Pure: `now` in, a slot out. A slot is the local date a job is for;
the job's output row is UNIQUE per slot, so a job that runs twice for one slot writes once."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MORNING_AT = time(7, 45)  # the list is ready before staff open the page
WEEKLY_AT = time(8, 0)  # Monday


MONTHLY_AT = time(8, 0)  # the 1st


def morning_slot(now: datetime, tz: str) -> date | None:
    """Today's date once it is 07:45 local; None before. Catches up if the worker was down at 07:45."""
    local = now.astimezone(ZoneInfo(tz))
    return local.date() if local.time() >= MORNING_AT else None


def weekly_slot(now: datetime, tz: str) -> date | None:
    """The Monday of this week once Monday 08:00 local has passed (a missed Monday runs when the worker is back)."""
    local = now.astimezone(ZoneInfo(tz))
    monday = local.date() - timedelta(days=local.weekday())
    return monday if local >= datetime.combine(monday, WEEKLY_AT, tzinfo=ZoneInfo(tz)) else None


def monthly_slot(now: datetime, tz: str) -> date | None:
    """The 1st of this month once 08:00 local on the 1st has passed (a missed 1st runs when the worker is back)."""
    local = now.astimezone(ZoneInfo(tz))
    first = local.date().replace(day=1)
    return first if local >= datetime.combine(first, MONTHLY_AT, tzinfo=ZoneInfo(tz)) else None
