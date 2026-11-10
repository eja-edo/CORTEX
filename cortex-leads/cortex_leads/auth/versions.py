"""Where a person's token version is remembered between requests, so a request does not have to read the database to know it.

One fact, one key: `v:<user id>` = the person's current token version, an integer. Every sign-in token carries the version it was made
at; a token below the current one is dead. Raising the number signs the person out of every device at once.

It is a cache, never the truth. The truth is the column `app_user.token_version`:
  - a missing key is a miss: read the column, write the key back (with an expiry of `VERSION_CACHE_SECONDS`);
  - Redis empty, restarted or away loses speed, never a sign-out;
  - a version write that was lost heals itself when the key expires, because the expiry belongs to each key.
Ending ONE device is not here either: it is a mark in `auth_session` and a bump of this number (auth/sessions.py).

Each request costs one `GET`. Measured on this machine with 100,000 people: a string per person 117 B, one shared hash 88 B, about
0.16 ms a request either way. A string per person is kept because each key has its own expiry (a hash cannot expire single fields
before Redis 7.4).

`MemoryStore` is the same thing in one process (development and tests). Do not run several server processes on it: a bump in one
would not reach the others for up to `VERSION_CACHE_SECONDS`."""
import logging
import time
from typing import Protocol
from uuid import UUID

from cortex_leads.config import get_settings

log = logging.getLogger(__name__)


class StoreDown(Exception):
    """Redis did not answer. Callers fall back to the database, which is slower and exactly as correct."""


class VersionStore(Protocol):
    async def get(self, user_id: UUID) -> int | None: ...
    async def set(self, user_id: UUID, version: int) -> None: ...


class RedisStore:
    def __init__(self, url: str, prefix: str) -> None:
        import redis.asyncio as aioredis

        self._r = aioredis.Redis.from_url(url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5)
        self._p = prefix

    def _key(self, user_id: UUID) -> str:
        return f"{self._p}:v:{user_id}"

    async def get(self, user_id: UUID) -> int | None:
        try:
            v = await self._r.get(self._key(user_id))
        except Exception as e:
            raise StoreDown(type(e).__name__) from e
        return int(v) if v is not None else None

    async def set(self, user_id: UUID, version: int) -> None:
        try:
            await self._r.set(self._key(user_id), version, ex=get_settings().VERSION_CACHE_SECONDS)
        except Exception as e:  # noqa: BLE001  the database is the truth; a lost write heals when the key expires
            log.warning("could not cache a token version (%s); it heals within %ss", type(e).__name__, get_settings().VERSION_CACHE_SECONDS)


class MemoryStore:
    def __init__(self) -> None:
        self._v: dict[UUID, tuple[int, float]] = {}

    async def get(self, user_id: UUID) -> int | None:
        v = self._v.get(user_id)
        if v and v[1] <= time.monotonic():
            del self._v[user_id]
            return None
        return v[0] if v else None

    async def set(self, user_id: UUID, version: int) -> None:
        self._v[user_id] = (version, time.monotonic() + get_settings().VERSION_CACHE_SECONDS)

    def forget_everything(self) -> None:
        """Tests: what an emptied Redis looks like."""
        self._v.clear()


_store: VersionStore | None = None


def get_store() -> VersionStore:
    global _store
    if _store is None:
        cfg = get_settings()
        _store = RedisStore(cfg.REDIS_URL, cfg.REDIS_PREFIX) if cfg.REDIS_URL else MemoryStore()
    return _store


def set_store(store: VersionStore | None) -> None:
    """Tests install their own; None goes back to what the settings say."""
    global _store
    _store = store
