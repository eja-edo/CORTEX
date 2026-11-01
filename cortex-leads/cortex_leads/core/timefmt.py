"""The one place dates and times are written out (DESIGN §5.13). Nothing else calls `isoformat` or `strftime`.

  * an INSTANT is a `timestamptz`: on the wire `2026-10-21T03:20:54Z` (UTC, `Z`, whole seconds, never `+07:00`);
  * a CALENDAR DAY is a `date`: on the wire `2026-10-25`;
  * a time of day is never stored as text: it is read off an instant in the business's time zone;
  * people read `HH:mm` and `dd/mm` (`dd/mm/yyyy` when the year is not the current one), in the BUSINESS's zone,
    whatever zone the browser or the server is in.
The business's zone is `tenant.timezone` (IANA name). Naive datetimes are refused: a time without a zone is a bug."""
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

Zone = ZoneInfo | str


def _zone(tz: Zone) -> ZoneInfo:
    return tz if isinstance(tz, ZoneInfo) else ZoneInfo(tz)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime: every instant carries its zone")
    return dt


def wire(dt: datetime | None) -> str | None:
    """RFC 3339, UTC, `Z`, seconds. The only way an instant leaves the API."""
    return None if dt is None else _aware(dt).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def wire_date(d: date | None) -> str | None:
    return None if d is None else d.isoformat()


def local(dt: datetime, tz: Zone) -> datetime:
    return _aware(dt).astimezone(_zone(tz))


def vi_time(dt: datetime, tz: Zone) -> str:
    d = local(dt, tz)
    return f"{d.hour:02d}:{d.minute:02d}"


def vi_date(x: datetime | date, tz: Zone, now: datetime) -> str:
    """`dd/mm` this year, `dd/mm/yyyy` otherwise. A `date` is already a calendar day; an instant is read in `tz`."""
    d = local(x, tz).date() if isinstance(x, datetime) else x
    this_year = local(now, tz).year
    return f"{d.day:02d}/{d.month:02d}" + ("" if d.year == this_year else f"/{d.year}")


def vi_datetime(dt: datetime, tz: Zone, now: datetime) -> str:
    return f"{vi_time(dt, tz)} {vi_date(dt, tz, now)}"


def day_start(now: datetime, tz: Zone) -> datetime:
    """Midnight that began the business's current day, as an instant (UTC). "Today" for any number an owner reads."""
    z = _zone(tz)
    return datetime.combine(local(now, z).date(), time(0), tzinfo=z).astimezone(UTC)


def stamp(dt: datetime, tz: Zone) -> str:
    """`2026-10-21 10:42` in the business's zone: how a time is written for a MODEL to read (it must not see UTC
    and tell a customer "tối qua" about a message sent this morning)."""
    d = local(dt, tz)
    return f"{d.year}-{d.month:02d}-{d.day:02d} {d.hour:02d}:{d.minute:02d}"


def vi_duration(delta: timedelta) -> str:
    s = int(delta.total_seconds())
    for size, name in ((86_400, "ngày"), (3_600, "giờ"), (60, "phút")):
        if s >= size and s % size == 0:
            return f"{s // size} {name}"
    return f"{s} giây"


async def tenant_tz(session: AsyncSession, tenant_id: UUID) -> str:
    from cortex_leads.db.models import Tenant

    return (await session.execute(select(Tenant.timezone).where(Tenant.id == tenant_id))).scalar_one()


def public(obj: Any) -> Any:
    """Deep-converts datetimes / dates in a plain structure to their wire form (for evidence blobs and logs)."""
    if isinstance(obj, datetime):
        return wire(obj)
    if isinstance(obj, date):
        return wire_date(obj)
    if isinstance(obj, dict):
        return {k: public(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [public(v) for v in obj]
    return obj
