"""Server-side sessions. The cookie is `<id>.<secret>`; the database keeps a hash of the secret, so reading the table never
yields a working cookie. Every request re-reads the session and the account, so signing out, a password change, disabling a
person or demoting them takes effect on their very next request, not when a cookie happens to expire."""
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.config import get_settings
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session

TOUCH_EVERY = timedelta(seconds=60)  # `last_seen_at` is a sliding idle clock; writing it on every request would make every read a write
_COOKIE = re.compile(r"^([0-9a-f-]{36})\.([A-Za-z0-9_-]{40,})$")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass(frozen=True)
class Resolved:
    session_id: UUID
    user: m.AppUser
    tenant: m.Tenant
    cookie: str


async def create(s: AsyncSession, user: m.AppUser, *, ip: str | None, user_agent: str | None, now: datetime) -> str:
    """Opens a session for a person already inside a tenant transaction. Returns the cookie value (the only time the secret exists)."""
    secret = secrets.token_urlsafe(32)
    row = m.AuthSession(id=uuid7(), tenant_id=user.tenant_id, user_id=user.id, secret_hash=_hash(secret), created_at=now, last_seen_at=now,
                        expires_at=now + timedelta(hours=get_settings().SESSION_ABSOLUTE_HOURS), ip=ip, user_agent=(user_agent or "")[:300] or None)
    s.add(row)
    await s.flush()
    return f"{row.id}.{secret}"


async def resolve(cookie: str, now: datetime | None = None) -> Resolved | None:
    """The person behind a cookie, or None for anything unknown, wrong, ended, idle, disabled or without a business."""
    now = now or datetime.now(UTC)
    found = _COOKIE.match(cookie or "")
    if not found:
        return None
    sid, secret = UUID(found.group(1)), found.group(2)
    async with system_session() as s:
        await s.execute(text("select set_config('app.session_id', :i, true)"), {"i": str(sid)})  # the one row this cookie names
        row = (await s.execute(select(m.AuthSession).where(m.AuthSession.id == sid))).scalar_one_or_none()
        if row is None or not hmac.compare_digest(row.secret_hash, _hash(secret)) or row.revoked_at is not None or row.expires_at <= now:
            return None
        if now - row.last_seen_at > timedelta(minutes=get_settings().SESSION_IDLE_MINUTES):
            return None
        await s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(row.tenant_id)})
        user = (await s.execute(select(m.AppUser).where(m.AppUser.id == row.user_id))).scalar_one_or_none()
        tenant = await s.get(m.Tenant, row.tenant_id)
        if user is None or user.status != "active" or tenant is None:
            return None
        if now - row.last_seen_at > TOUCH_EVERY:
            await s.execute(update(m.AuthSession).where(m.AuthSession.id == sid).values(last_seen_at=now))
        s.expunge_all()
        return Resolved(sid, user, tenant, cookie)


async def revoke(s: AsyncSession, session_id: UUID, reason: str, now: datetime) -> bool:
    res = await s.execute(update(m.AuthSession).where(m.AuthSession.id == session_id, m.AuthSession.revoked_at.is_(None))
                          .values(revoked_at=now, revoked_reason=reason))
    return res.rowcount > 0


async def revoke_user(s: AsyncSession, user_id: UUID, reason: str, now: datetime, *, keep: UUID | None = None) -> int:
    q = update(m.AuthSession).where(m.AuthSession.user_id == user_id, m.AuthSession.revoked_at.is_(None))
    if keep is not None:
        q = q.where(m.AuthSession.id != keep)
    return (await s.execute(q.values(revoked_at=now, revoked_reason=reason))).rowcount


async def active_for(s: AsyncSession, user_id: UUID, now: datetime) -> list[m.AuthSession]:
    idle = now - timedelta(minutes=get_settings().SESSION_IDLE_MINUTES)
    return list((await s.execute(select(m.AuthSession).where(
        m.AuthSession.user_id == user_id, m.AuthSession.revoked_at.is_(None), m.AuthSession.expires_at > now, m.AuthSession.last_seen_at > idle)
        .order_by(m.AuthSession.created_at.desc()))).scalars())
