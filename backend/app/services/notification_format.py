"""Shared formatting for notification text.

Every detection reason used to render its own one-liner from a bare count —
"Còn 5 việc chưa xong", "Trễ 3 ngày" — which is a number the user has to go
look up rather than a fact they can act on. That is the same mistake
`today.py`'s module docstring calls out for the "Hôm nay" screen ("it serves
decisions, not numbers"), arriving through a different door.

This module is the one place notification text is composed, so a task reads
the same way in a Mezon DM, the notification bell and the detail modal, and
so a new reason gets the detail for free instead of reinventing a phrasing.

**Two different kinds of timestamp live here and must not be mixed up.**
`Task.due_date` is `DateTime(timezone=False)` — a wall-clock deadline the
user typed, deliberately not an instant (see the column's comment in
models.py), so it is printed as-is. `Schedule.start_time` is `TIMESTAMPTZ`,
a real instant, so it is converted into `settings.DISPLAY_TIMEZONE` before
printing. Running either through the other's path is how a 14:00 meeting
ends up announced as 07:00.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How many items a digest names before falling back to "…và N việc khác".
# Small on purpose: the notification bell renders content blocks inline, and
# a list of twenty is a backlog, not a notification — the same reasoning
# behind `today.MAX_NOW_ACTIONS`.
MAX_LISTED_ITEMS = 5

_PRIORITY_LABELS = {
    "urgent": "khẩn cấp",
    "high": "ưu tiên cao",
    "medium": "ưu tiên vừa",
    "low": "ưu tiên thấp",
}


def _parse(iso_value: Any) -> datetime | None:
    """Payloads arrive as JSON, so every timestamp is an ISO string by the
    time a subscriber sees it. Returns None rather than raising: a
    malformed timestamp should cost the notification one detail, not the
    whole delivery."""
    if not iso_value:
        return None
    if isinstance(iso_value, datetime):
        return iso_value
    try:
        return datetime.fromisoformat(str(iso_value))
    except (TypeError, ValueError):
        return None


def local_clock(iso_value: Any) -> str | None:
    """`HH:MM DD/MM` in the display timezone, for a real instant
    (`Schedule.start_time`). Naive input is read as UTC — the schema stores
    UTC throughout, and guessing the host's zone would shift the printed
    time by its offset."""
    parsed = _parse(iso_value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        local = parsed.astimezone(ZoneInfo(settings.DISPLAY_TIMEZONE))
    except Exception:
        logger.warning("Invalid DISPLAY_TIMEZONE %r, falling back to UTC", settings.DISPLAY_TIMEZONE)
        local = parsed.astimezone(timezone.utc)
    return local.strftime("%H:%M %d/%m")


def priority_label(priority: str | None) -> str | None:
    """`None` for an unset priority, which is not the same as LOW and must
    not be printed as one (see TaskPriority's docstring)."""
    if not priority:
        return None
    return _PRIORITY_LABELS.get(str(priority).lower())


def task_due_phrase(due_iso: Any, *, today: date | None = None) -> str | None:
    """How a task's deadline reads in a sentence: `hạn hôm nay 17:00`,
    `hạn 20/08`, `trễ 3 ngày`.

    Day-granular, matching `today._due_day`: a task due at 23:00 today is
    "due today", not "overdue by -9 hours". The time-of-day is only shown
    when the task actually carries one — a bare date arrives as midnight,
    and printing "hạn hôm nay 00:00" would invent a deadline the user never
    set.
    """
    parsed = _parse(due_iso)
    if parsed is None:
        return None
    today = today or datetime.now(timezone.utc).date()
    due_day = parsed.date()
    has_time = (parsed.hour, parsed.minute) != (0, 0)
    clock = parsed.strftime(" %H:%M") if has_time else ""

    delta = (due_day - today).days
    if delta < 0:
        return f"trễ {-delta} ngày"
    if delta == 0:
        return f"hạn hôm nay{clock}"
    if delta == 1:
        return f"hạn ngày mai{clock}"
    return f"hạn {parsed.strftime('%d/%m')}{clock}"


def task_due_stamp(due_iso: Any) -> str | None:
    """A task's deadline as a bare date, `20/08` or `20/08 17:00`.

    The absolute twin of `task_due_phrase`. Reasons that already state the
    lateness themselves ("Trễ 3 ngày") need the date, not a second relative
    phrase — pairing them would read "Trễ 3 ngày · trễ 3 ngày".
    """
    parsed = _parse(due_iso)
    if parsed is None:
        return None
    has_time = (parsed.hour, parsed.minute) != (0, 0)
    return parsed.strftime("%d/%m %H:%M") if has_time else parsed.strftime("%d/%m")


def join_facts(*facts: str | None) -> str:
    """Glue the non-empty facts with ` · `. Keeping the separator in one
    place is what makes every reason's body read as one system."""
    return " · ".join(f for f in facts if f)


def task_line(item: dict[str, Any], *, today: date | None = None, bullet: str = "• ") -> str:
    """One task as a line in a digest: `• Viết báo cáo Q3 — trễ 3 ngày · ưu tiên cao`."""
    title = str(item.get("title") or "(không có tiêu đề)")
    facts = join_facts(
        task_due_phrase(item.get("due_date"), today=today),
        priority_label(item.get("priority")),
    )
    return f"{bullet}{title} — {facts}" if facts else f"{bullet}{title}"


def schedule_line(item: dict[str, Any], *, bullet: str = "• ") -> str:
    """One calendar event as a line: `• Họp team — 14:00 20/08 · Phòng A`."""
    title = str(item.get("title") or "(không có tiêu đề)")
    facts = join_facts(local_clock(item.get("start_time")), item.get("location") or None)
    return f"{bullet}{title} — {facts}" if facts else f"{bullet}{title}"


def overflow_line(shown: int, total: int, *, noun: str = "việc") -> str | None:
    """`…và 7 việc khác` — the counts the old bodies led with are still the
    honest summary, they just belong after the named items rather than
    instead of them."""
    remaining = total - shown
    return f"…và {remaining} {noun} khác" if remaining > 0 else None


def text_blocks(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Notification `content` as one text block per line.

    `BlockRenderer` wraps each block in its own div, so separate blocks are
    what actually produce separate lines in the bell and the detail modal —
    a single block with embedded newlines collapses into one run of text.
    """
    return [{"type": "text", "text": line} for line in lines if line]
