"""Slows password guessing. Two counters per attempt: one for the account (by hashed email, whether or not it exists, so the
answer never reveals which emails are real) and one for the network address. Crossing a limit locks that key for a while; a
correct password clears only the account's counter."""
import hashlib
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.config import get_settings
from cortex_leads.db import models as m


def account_key(email: str) -> str:
    return "acct:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


def ip_key(ip: str | None) -> str:
    return "ip:" + hashlib.sha256((ip or "unknown").encode()).hexdigest()[:32]


async def locked_for(s: AsyncSession, keys: list[str], now: datetime) -> int:
    """Seconds left on the longest lock among the keys; 0 = free to try."""
    rows = (await s.execute(select(m.LoginThrottle).where(m.LoginThrottle.key.in_(keys)))).scalars().all()
    return max((int((r.locked_until - now).total_seconds()) + 1 for r in rows if r.locked_until and r.locked_until > now), default=0)


async def fail(s: AsyncSession, key: str, now: datetime, *, limit: int, window: timedelta, lock: timedelta) -> bool:
    """Counts one failure. True when this failure is the one that locks the key."""
    row = (await s.execute(select(m.LoginThrottle).where(m.LoginThrottle.key == key).with_for_update())).scalar_one_or_none()
    if row is None:
        row = m.LoginThrottle(key=key, failures=0, first_at=now)
        s.add(row)
    if now - row.first_at > window or (row.locked_until and row.locked_until <= now):
        row.failures, row.first_at, row.locked_until = 0, now, None  # an old streak does not count against a new attempt
    row.failures += 1
    locks = row.failures >= limit
    if locks:
        row.locked_until = now + lock
    await s.flush()
    return locks


async def register_failure(s: AsyncSession, email: str, ip: str | None, now: datetime) -> bool:
    cfg = get_settings()
    by_account = await fail(s, account_key(email), now, limit=cfg.LOGIN_MAX_FAILURES, window=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES * 2),
                            lock=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES))
    await fail(s, ip_key(ip), now, limit=cfg.LOGIN_IP_MAX_FAILURES, window=timedelta(minutes=cfg.LOGIN_IP_WINDOW_MINUTES),
               lock=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES))
    return by_account


async def clear_account(s: AsyncSession, email: str) -> None:
    row = await s.get(m.LoginThrottle, account_key(email))
    if row is not None:
        await s.delete(row)
