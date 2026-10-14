"""Pure scheduling rule for the silence clock (DESIGN §5.2/§5.7). `now` is always injected."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PROMISE_HOUR = time(8, 0)


def compute_next_check_at(
    last_customer_at: datetime | None,
    last_staff_at: datetime | None,
    promised_date: date | None,
    state: str,
    tz: str,
    now: datetime,
    silent_after: timedelta = timedelta(hours=24),
) -> datetime | None:
    if state != "open":
        return None
    if promised_date is not None:
        at = datetime.combine(promised_date, PROMISE_HOUR, tzinfo=ZoneInfo(tz))
        if at > now:
            return at
    # Whoever spoke last, the clock is "silence since the latest message": after a customer
    # message it waits for staff; after a staff reply it waits for the customer.
    latest = max((t for t in (last_customer_at, last_staff_at) if t is not None), default=None)
    return None if latest is None else latest + silent_after
