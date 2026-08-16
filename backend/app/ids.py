"""Primary-key generation.

Every persisted identifier in Cortex is a UUIDv7 (RFC 9562): a 48-bit
millisecond timestamp followed by 74 bits of randomness. Unlike v4 the values
sort by creation time, so inserts land on the right-hand edge of the B-tree
instead of scattering across it — far fewer page splits and less WAL churn on
the append-heavy tables (notifications, action_history, attention_bundle_queue,
events).

Always import `uuid7` from here rather than calling `uuid_utils.uuid7()`
directly: the top-level `uuid_utils.uuid7()` returns a `uuid_utils.UUID`, which
is *not* an instance of `uuid.UUID` and therefore fails psycopg2 adaptation and
Pydantic validation. Only `uuid_utils.compat` returns the stdlib type.

Note that a v7 value discloses its own creation time to anyone holding it. That
is fine for internal row ids behind auth; do not use it for an identifier whose
creation time must stay secret.
"""
import uuid

from uuid_utils.compat import uuid7 as _uuid7


def uuid7() -> uuid.UUID:
    """Return a time-ordered UUIDv7 as a standard-library `uuid.UUID`."""
    return _uuid7()


__all__ = ["uuid7"]
