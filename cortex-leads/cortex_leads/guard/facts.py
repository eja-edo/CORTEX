"""Date phrases in Vietnamese customer text -> the set of dates they may mean (DESIGN N5/A4).
A fact the AI proposes must land inside this set, or be flagged vague for a human to confirm."""
import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from cortex_leads.privacy.redact import _fold

HORIZON_DAYS = 180
_WD = {"hai": 0, "2": 0, "ba": 1, "3": 1, "tu": 2, "4": 2, "nam": 3, "5": 3,
       "sau": 4, "6": 4, "bay": 5, "7": 5, "chu nhat": 6}
_DMY = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?!\d)")
_DAY = re.compile(r"\bngay (\d{1,2})(?![\d/])")
_WEEKDAY = re.compile(r"\b(?:thu (hai|ba|tu|nam|sau|bay|[2-7])|(chu nhat))\b(?: (tuan nay|tuan sau))?")
# "mai" alone is also a given name: only "ngày mai" or a verb/preposition right before it.
_TOMORROW = re.compile(r"\bngay mai\b|\b(?:den|vao|hen|toi|qua|lai|goi|bao) mai\b")
_VAGUE = re.compile(r"\b(sau tet|dau thang|giua thang|cuoi thang|dau nam|cuoi nam|sau nay|it hom|"
                    r"may hom|vai hom|vai ngay|may ngay|thang toi|hom nao|luc nao)\b")


def is_vague(text: str) -> bool:
    return _VAGUE.search(_fold(text)) is not None


def extract_date_candidates(text: str, now: datetime, tz: str) -> set[date]:
    """Future dates (<= 180 days) the phrases in `text` can mean, relative to `now` in `tz`."""
    t, today = _fold(text), now.astimezone(ZoneInfo(tz)).date()
    monday = today - timedelta(days=today.weekday())
    out: set[date] = set()

    def add(y: int, mo: int, d: int) -> None:
        try:
            out.add(date(y + (mo - 1) // 12, (mo - 1) % 12 + 1, d))
        except ValueError:
            pass

    for d, mo, y in _DMY.findall(t):
        if y:
            add(int(y), int(mo), int(d))
        else:  # no year: this year, or next when already past
            add(today.year + (0 if (int(mo), int(d)) > (today.month, today.day) else 1), int(mo), int(d))
    for d in _DAY.findall(t):
        add(today.year, today.month + (0 if int(d) > today.day else 1), int(d))
    if _TOMORROW.search(t):
        out.add(today + timedelta(days=1))
    if "ngay kia" in t:
        out.add(today + timedelta(days=2))
    weekdays = _WEEKDAY.findall(t)
    for num, cn, qual in weekdays:
        idx = _WD[num or cn]
        if not qual:
            out.add(today + timedelta(days=(idx - today.weekday()) % 7 or 7))
        else:
            out.add(monday + timedelta(days=idx + (7 if qual == "tuan sau" else 0)))
    if "cuoi tuan" in t:
        out |= {monday + timedelta(days=5), monday + timedelta(days=6)}
        if not any(d > today for d in out):
            out |= {monday + timedelta(days=12), monday + timedelta(days=13)}
    if not weekdays and re.search(r"\btuan sau\b", t):  # "thứ 6 tuần sau" is one day, not the week
        out |= {monday + timedelta(days=7 + i) for i in range(7)}
    if re.search(r"\bthang sau\b", t):
        y, mo = today.year + today.month // 12, today.month % 12 + 1
        out |= {date(y, mo, d) for d in range(1, calendar.monthrange(y, mo)[1] + 1)}
    return {d for d in out if today < d <= today + timedelta(days=HORIZON_DAYS)}
