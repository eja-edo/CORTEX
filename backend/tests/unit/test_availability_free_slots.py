from datetime import datetime, timedelta, timezone

from app.services.availability import _gaps


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, tzinfo=timezone.utc)


def test_no_busy_intervals_the_whole_range_is_free():
    assert _gaps([], _at(9), _at(17), timedelta(minutes=30)) == [(_at(9), _at(17))]


def test_one_meeting_in_the_middle_splits_the_range_in_two():
    busy = [(_at(12), _at(13))]
    assert _gaps(busy, _at(9), _at(17), timedelta(minutes=30)) == [
        (_at(9), _at(12)),
        (_at(13), _at(17)),
    ]


def test_back_to_back_meetings_merge_into_one_busy_block():
    busy = [(_at(10), _at(11)), (_at(11), _at(12))]
    assert _gaps(busy, _at(9), _at(17), timedelta(minutes=30)) == [
        (_at(9), _at(10)),
        (_at(12), _at(17)),
    ]


def test_overlapping_meetings_merge():
    busy = [(_at(10), _at(12)), (_at(11), _at(13))]
    assert _gaps(busy, _at(9), _at(17), timedelta(minutes=30)) == [
        (_at(9), _at(10)),
        (_at(13), _at(17)),
    ]


def test_meeting_spanning_the_whole_range_leaves_no_free_slot():
    busy = [(_at(8), _at(18))]
    assert _gaps(busy, _at(9), _at(17), timedelta(minutes=30)) == []


def test_meeting_outside_the_range_is_clipped_away():
    busy = [(_at(6), _at(8)), (_at(18), _at(20))]
    assert _gaps(busy, _at(9), _at(17), timedelta(minutes=30)) == [(_at(9), _at(17))]


def test_gap_shorter_than_min_duration_is_dropped():
    busy = [(_at(12), _at(12, 45))]
    assert _gaps(busy, _at(12), _at(13), timedelta(minutes=30)) == []


def test_gap_exactly_min_duration_is_kept():
    busy = [(_at(12), _at(12, 30))]
    assert _gaps(busy, _at(12), _at(13), timedelta(minutes=30)) == [(_at(12, 30), _at(13))]


def test_unsorted_input_is_handled():
    busy = [(_at(14), _at(15)), (_at(10), _at(11))]
    assert _gaps(busy, _at(9), _at(17), timedelta(minutes=30)) == [
        (_at(9), _at(10)),
        (_at(11), _at(14)),
        (_at(15), _at(17)),
    ]
