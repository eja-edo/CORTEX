"""Unit tests for `app.services.notification_format`.

The module exists because every detection reason used to render its own
one-liner from a bare count, so this pins the two things that actually
went wrong: the wall-clock/instant distinction, and lists that named
nothing.
"""

from datetime import date

import pytest

from app.config import settings
from app.services.notification_format import (
    MAX_LISTED_ITEMS,
    join_facts,
    local_clock,
    overflow_line,
    priority_label,
    schedule_line,
    task_due_phrase,
    task_due_stamp,
    task_line,
    text_blocks,
)

TODAY = date(2026, 8, 24)


# ---------------------------------------------------------------------------
# The two kinds of timestamp
# ---------------------------------------------------------------------------


def test_schedule_times_are_converted_to_the_display_timezone(monkeypatch):
    """`Schedule.start_time` is TIMESTAMPTZ — a real instant. Printing it
    raw told a Vietnamese user their 14:00 meeting was at 07:00."""
    monkeypatch.setattr(settings, "DISPLAY_TIMEZONE", "Asia/Ho_Chi_Minh")
    assert local_clock("2026-08-24T07:00:00+00:00") == "14:00 24/08"


def test_naive_schedule_times_are_read_as_utc(monkeypatch):
    """The schema stores UTC throughout; guessing the host's zone instead
    would shift every printed time by the machine's offset."""
    monkeypatch.setattr(settings, "DISPLAY_TIMEZONE", "Asia/Ho_Chi_Minh")
    assert local_clock("2026-08-24T07:00:00") == "14:00 24/08"


def test_task_deadlines_are_never_timezone_shifted(monkeypatch):
    """`Task.due_date` is `DateTime(timezone=False)` on purpose — a
    wall-clock deadline the user typed, not an instant (see the column's
    comment in models.py). Running it through the schedule path would move
    "hạn 17:00" to "hạn 00:00 hôm sau" for a UTC+7 user."""
    monkeypatch.setattr(settings, "DISPLAY_TIMEZONE", "Asia/Ho_Chi_Minh")
    assert task_due_stamp("2026-08-24T17:00:00") == "24/08 17:00"
    assert task_due_phrase("2026-08-24T17:00:00", today=TODAY) == "hạn hôm nay 17:00"


def test_a_bare_date_does_not_invent_a_time():
    """A task created from a plain date arrives as midnight. Printing "hạn
    hôm nay 00:00" would state a deadline the user never set."""
    assert task_due_phrase("2026-08-24T00:00:00", today=TODAY) == "hạn hôm nay"
    assert task_due_stamp("2026-08-24T00:00:00") == "24/08"


@pytest.mark.parametrize(
    "due,expected",
    [
        ("2026-08-21T00:00:00", "trễ 3 ngày"),
        ("2026-08-24T00:00:00", "hạn hôm nay"),
        ("2026-08-25T09:30:00", "hạn ngày mai 09:30"),
        ("2026-09-02T00:00:00", "hạn 02/09"),
    ],
)
def test_due_phrase_is_day_granular(due, expected):
    """Matches `today._due_day`: a task due at 23:00 today is "due today",
    not "overdue by -9 hours"."""
    assert task_due_phrase(due, today=TODAY) == expected


def test_unparseable_or_missing_timestamps_cost_one_detail_not_the_delivery():
    for bad in (None, "", "not-a-date", "2026-13-45"):
        assert task_due_phrase(bad, today=TODAY) is None
        assert task_due_stamp(bad) is None
        assert local_clock(bad) is None


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------


def test_unset_priority_is_not_printed_as_low():
    """Unset ranks below every set value but is not the same as LOW — see
    TaskPriority's docstring. Printing "ưu tiên thấp" would assert
    something the user never said."""
    assert priority_label(None) is None
    assert priority_label("") is None
    assert priority_label("low") == "ưu tiên thấp"
    assert priority_label("urgent") == "khẩn cấp"


def test_unknown_priority_is_dropped_rather_than_echoed():
    assert priority_label("catastrophic") is None


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def test_join_facts_drops_the_empty_ones():
    assert join_facts("Trễ 3 ngày", None, "ưu tiên cao") == "Trễ 3 ngày · ưu tiên cao"
    assert join_facts(None, None) == ""


def test_task_line_names_the_task_and_its_standing():
    line = task_line(
        {"title": "Viết báo cáo Q3", "due_date": "2026-08-21T00:00:00", "priority": "high"},
        today=TODAY,
    )
    assert line == "• Viết báo cáo Q3 — trễ 3 ngày · ưu tiên cao"


def test_task_line_survives_a_task_with_no_facts_at_all():
    assert task_line({"title": "Dọn backlog"}, today=TODAY) == "• Dọn backlog"


def test_task_line_never_renders_an_empty_title():
    assert "(không có tiêu đề)" in task_line({"title": ""}, today=TODAY)


def test_schedule_line_uses_the_converted_clock(monkeypatch):
    monkeypatch.setattr(settings, "DISPLAY_TIMEZONE", "Asia/Ho_Chi_Minh")
    line = schedule_line(
        {"title": "Họp khách hàng", "start_time": "2026-08-24T07:00:00+00:00", "location": "Phòng A"}
    )
    assert line == "• Họp khách hàng — 14:00 24/08 · Phòng A"


def test_overflow_line_only_appears_when_something_is_hidden():
    assert overflow_line(5, 12) == "…và 7 việc khác"
    assert overflow_line(3, 3) is None
    assert overflow_line(5, 2) is None


def test_text_blocks_are_one_per_line():
    """`BlockRenderer` wraps each block in its own element, so separate
    blocks are what produce separate lines — a single block with embedded
    newlines collapses into one run of text."""
    blocks = text_blocks(["a", "", "b"])
    assert blocks == [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]


def test_max_listed_items_stays_small():
    """The bell renders content blocks inline; a list of twenty is a
    backlog, not a notification."""
    assert 1 < MAX_LISTED_ITEMS <= 10
