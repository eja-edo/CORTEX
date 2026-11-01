"""DESIGN §5.13: one way to write an instant, a day and a time of day."""
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from cortex_leads.core.timefmt import (
    day_start,
    public,
    vi_date,
    vi_datetime,
    vi_duration,
    vi_time,
    wire,
    wire_date,
)

VN = "Asia/Ho_Chi_Minh"  # UTC+7
NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)  # 10:00 on 12/10 in Vietnam


def test_an_instant_leaves_as_utc_with_z_whatever_zone_it_was_held_in():
    assert wire(NOW) == "2026-10-12T03:00:00Z"
    assert wire(datetime(2026, 10, 12, 10, 0, tzinfo=timezone(timedelta(hours=7)))) == "2026-10-12T03:00:00Z"  # never +07:00
    assert wire(datetime(2026, 10, 12, 3, 0, 5, 987654, tzinfo=UTC)) == "2026-10-12T03:00:05Z"  # whole seconds
    assert wire(None) is None and wire_date(None) is None and wire_date(date(2026, 10, 25)) == "2026-10-25"


def test_a_time_without_a_zone_is_refused_not_guessed():
    with pytest.raises(ValueError):
        wire(datetime(2026, 10, 12, 3, 0))
    with pytest.raises(ValueError):
        vi_time(datetime(2026, 10, 12, 3, 0), VN)


def test_people_read_the_business_zone_not_the_servers():
    assert vi_time(NOW, VN) == "10:00" and vi_time(NOW, "America/New_York") == "23:00"  # the evening before there
    late = datetime(2026, 10, 12, 18, 30, tzinfo=UTC)  # 01:30 on the 13th in Vietnam
    assert vi_date(late, VN, NOW) == "13/10" and vi_date(late, "UTC", NOW) == "12/10"
    assert vi_datetime(late, VN, NOW) == "01:30 13/10"


def test_the_year_is_shown_only_when_it_is_not_this_year():
    assert vi_date(date(2026, 1, 5), VN, NOW) == "05/01"
    assert vi_date(date(2027, 1, 5), VN, NOW) == "05/01/2027" and vi_date(date(2025, 12, 31), VN, NOW) == "31/12/2025"
    assert vi_datetime(datetime(2027, 1, 4, 20, 0, tzinfo=UTC), VN, NOW) == "03:00 05/01/2027"
    new_year = datetime(2026, 12, 31, 18, 0, tzinfo=UTC)  # already 2027 in Vietnam
    assert vi_date(date(2027, 1, 5), VN, new_year) == "05/01"  # "this year" is the business's year


def test_today_begins_at_the_business_midnight():
    assert day_start(NOW, VN) == datetime(2026, 10, 11, 17, 0, tzinfo=UTC)
    assert day_start(datetime(2026, 10, 11, 16, 59, tzinfo=UTC), VN) == datetime(2026, 10, 10, 17, 0, tzinfo=UTC)
    assert day_start(NOW, "UTC") == datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


def test_durations_use_the_largest_exact_unit():
    assert [vi_duration(timedelta(**k)) for k in ({"hours": 20}, {"hours": 48}, {"days": 14}, {"minutes": 5}, {"seconds": 30}, {"hours": 36})] == [
        "20 giờ", "2 ngày", "14 ngày", "5 phút", "30 giây", "36 giờ"]


def test_a_structure_is_converted_deeply():
    assert public({"a": NOW, "b": [date(2026, 10, 25), {"c": NOW}], "d": 3}) == {"a": "2026-10-12T03:00:00Z", "b": ["2026-10-25", {"c": "2026-10-12T03:00:00Z"}], "d": 3}
