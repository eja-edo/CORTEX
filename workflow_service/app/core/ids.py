"""Primary-key generation.

Mirrors `backend/app/ids.py` — both services write UUIDv7 (RFC 9562) so ids
stay time-ordered across the whole system, including the workflow rows the
backend joins against.

Import `uuid7` from here rather than calling `uuid_utils.uuid7()` directly: the
top-level `uuid_utils.uuid7()` returns a `uuid_utils.UUID`, which is not an
instance of `uuid.UUID` and so fails driver adaptation and Pydantic validation.
Only `uuid_utils.compat` returns the stdlib type.
"""
import uuid

from uuid_utils.compat import uuid7 as _uuid7


def uuid7() -> uuid.UUID:
    """Return a time-ordered UUIDv7 as a standard-library `uuid.UUID`."""
    return _uuid7()


__all__ = ["uuid7"]
