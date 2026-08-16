"""UUIDv7 generation guarantees relied on by every primary key."""
import time
import uuid

from app.ids import uuid7


def _timestamp_ms(value: uuid.UUID) -> int:
    """Milliseconds since the epoch encoded in the leading 48 bits."""
    return value.int >> 80


def test_returns_stdlib_uuid():
    # uuid_utils' top-level uuid7() returns its own UUID class, which psycopg2
    # cannot adapt and Pydantic rejects. The helper must hand back the stdlib
    # type or every insert breaks at the driver boundary.
    value = uuid7()
    assert type(value) is uuid.UUID


def test_sets_version_and_variant():
    for _ in range(100):
        value = uuid7()
        assert value.version == 7
        assert value.variant == uuid.RFC_4122


def test_encodes_current_time():
    # Both bounds are floored: the uuid carries whole milliseconds, while
    # time.time() has sub-millisecond precision that would otherwise put the
    # lower bound just above a legitimately-equal timestamp.
    before = int(time.time() * 1000)
    value = uuid7()
    after = int(time.time() * 1000)
    assert before <= _timestamp_ms(value) <= after


def test_timestamps_are_non_decreasing():
    values = [uuid7() for _ in range(500)]
    stamps = [_timestamp_ms(v) for v in values]
    assert stamps == sorted(stamps)


def test_no_collisions_within_a_millisecond():
    values = {uuid7() for _ in range(10_000)}
    assert len(values) == 10_000
