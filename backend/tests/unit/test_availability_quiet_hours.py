from datetime import datetime, time, timezone

from app.services.availability import is_in_quiet_hours


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 13, hour, minute, tzinfo=timezone.utc)


def test_unconfigured_quiet_hours_is_never_quiet():
    assert is_in_quiet_hours(None, None, _at(23)) is False


def test_same_day_window_start_inclusive_end_exclusive():
    start, end = time(12, 0), time(13, 0)
    assert is_in_quiet_hours(start, end, _at(12, 0)) is True
    assert is_in_quiet_hours(start, end, _at(12, 30)) is True
    assert is_in_quiet_hours(start, end, _at(13, 0)) is False
    assert is_in_quiet_hours(start, end, _at(11, 59)) is False


def test_overnight_window_wraps_midnight():
    # 22:00 - 07:00 — quiet late at night and early morning, not midday.
    start, end = time(22, 0), time(7, 0)
    assert is_in_quiet_hours(start, end, _at(23, 0)) is True
    assert is_in_quiet_hours(start, end, _at(2, 0)) is True
    assert is_in_quiet_hours(start, end, _at(6, 59)) is True
    assert is_in_quiet_hours(start, end, _at(7, 0)) is False
    assert is_in_quiet_hours(start, end, _at(12, 0)) is False
    assert is_in_quiet_hours(start, end, _at(21, 59)) is False


def test_naive_datetime_is_treated_as_already_utc():
    start, end = time(12, 0), time(13, 0)
    naive_noon = datetime(2026, 8, 13, 12, 30)
    assert is_in_quiet_hours(start, end, naive_noon) is True
