"""Sign-ins: an access token and a refresh token, and what makes both revocable.

The ACCESS token (auth/tokens.py, cookie `cl_session`) is a short-lived signed JWT. Redis (auth/versions.py) holds one number per person, their
token version, and a request costs one `GET`. A token at the current version passes. A token at an OLDER version is not simply refused: the
database is asked whether *that sign-in* is still good (the person active, its `auth_session` row not revoked). If it is, the token is swapped for
one at the new version; if not, it is out. That one rule gives every kind of sign-out, instantly, with nothing but the version in Redis:
  - everywhere (password change, disabled, role or email changed, "sign out everywhere"): every row is marked revoked, so every old token is out;
  - one device on its own: that row is marked revoked and the version is raised, so that device is out on its very next request while the
    person's other devices pass through the same check, are found good, and are quietly re-issued once.

The REFRESH token (cookie `cl_refresh`, `<sid>.<secret>`, good `REFRESH_TOKEN_DAYS` from its last use) is how a sign-in outlives its access token. It is
opaque, only a hash of its secret is kept, and it is swapped for a new one every time it is used. Using an OLD one a moment later is two tabs racing and
is let through (an access token only); using it after that means two holders, so the whole sign-in is ended. A refresh also re-reads the person: a locked
or removed account, or a revoked sign-in, gets nothing.

The database is the truth (`app_user.token_version`, `auth_session`); Redis only saves the read, and being emptied costs speed, never a sign-out.
`auth_session` rows are also the list of devices (when, where, from what, last active)."""
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.auth import tokens
from cortex_leads.auth.versions import StoreDown, get_store
from cortex_leads.config import get_settings
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session

_REFRESH = re.compile(r"^([0-9a-f-]{36})\.([A-Za-z0-9_-]{40,})$")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _refresh_end(now: datetime, sign_in_ends: datetime) -> datetime:
    return min(now + timedelta(days=get_settings().REFRESH_TOKEN_DAYS), sign_in_ends)


async def create(s: AsyncSession, user: m.AppUser, tenant: m.Tenant, *, ip: str | None, user_agent: str | None, now: datetime) -> tuple[str, str]:
    """Opens a sign-in for a person already inside a tenant transaction. Returns (access token, refresh token): the two cookie values."""
    secret = secrets.token_urlsafe(32)
    ends = now + timedelta(hours=get_settings().SESSION_ABSOLUTE_HOURS)
    row = m.AuthSession(id=uuid7(), tenant_id=user.tenant_id, user_id=user.id, created_at=now, last_seen_at=now, expires_at=ends, ip=ip,
                        user_agent=(user_agent or "")[:300] or None, refresh_hash=_hash(secret), refresh_expires_at=_refresh_end(now, ends))
    s.add(row)
    await s.flush()
    return tokens.issue(user, tenant, row.id, now, now), f"{row.id}.{secret}"


@dataclass(frozen=True)
class Refreshed:
    access: str | None = None
    refresh: str | None = None  # None with an access token: the caller already holds the new one (two tabs racing)
    refresh_ends: datetime | None = None
    reason: str | None = None  # why not: "invalid" (unknown, ended, expired, locked) or "reused" (a spent token came back after the grace)
    tenant_id: UUID | None = None
    user_id: UUID | None = None


async def refresh(cookie: str, now: datetime | None = None, *, ip: str | None = None, user_agent: str | None = None) -> Refreshed:
    """Uses a refresh token: a new access token and a new refresh token. Anything wrong with it ends here with a reason and nothing else."""
    now = now or datetime.now(UTC)
    found = _REFRESH.match(cookie or "")
    if not found:
        return Refreshed(reason="invalid")
    sid, secret = UUID(found.group(1)), found.group(2)
    async with system_session() as s:
        await s.execute(text("select set_config('app.session_id', :i, true)"), {"i": str(sid)})  # the one row this cookie names
        tenant_id = (await s.execute(select(m.AuthSession.tenant_id).where(m.AuthSession.id == sid))).scalar_one_or_none()
    if tenant_id is None:
        return Refreshed(reason="invalid")
    grace = timedelta(seconds=get_settings().REFRESH_REUSE_GRACE_SECONDS)
    async with tenant_session(tenant_id) as s:
        row = await s.get(m.AuthSession, sid, with_for_update=True)  # two refreshes of one sign-in take turns
        user = await s.get(m.AppUser, row.user_id) if row else None
        tenant = await s.get(m.Tenant, tenant_id)
        if (row is None or user is None or tenant is None or user.status != "active" or row.revoked_at is not None or row.expires_at <= now
                or row.refresh_expires_at is None or row.refresh_expires_at <= now or row.refresh_hash is None):
            return Refreshed(reason="invalid", tenant_id=tenant_id)
        who = {"tenant_id": tenant_id, "user_id": user.id}
        presented = _hash(secret)
        if hmac.compare_digest(presented, row.refresh_hash):  # the normal case: swap it for a new one
            new_secret = secrets.token_urlsafe(32)
            row.refresh_prev_hash, row.refresh_hash, row.refresh_rotated_at = row.refresh_hash, _hash(new_secret), now
            row.refresh_expires_at = _refresh_end(now, row.expires_at)
            row.last_seen_at = now
            row.ip, row.user_agent = ip or row.ip, (user_agent or "")[:300] or row.user_agent
            return Refreshed(tokens.issue(user, tenant, sid, row.created_at, now), f"{sid}.{new_secret}", row.refresh_expires_at, **who)
        if row.refresh_prev_hash and hmac.compare_digest(presented, row.refresh_prev_hash):  # a secret that WAS right, one swap ago
            if row.refresh_rotated_at and now - row.refresh_rotated_at <= grace:
                return Refreshed(tokens.issue(user, tenant, sid, row.created_at, now), None, row.refresh_expires_at, **who)
            await revoke(s, sid, "refresh_reused", now)  # a spent token again after the grace: two holders, so no holder
            return Refreshed(reason="reused", **who)
        return Refreshed(reason="invalid", **who)  # a guess: the sign-in id is not a secret (it is in the access token), so a wrong secret must cost the owner nothing


async def sign_in_of_refresh(cookie: str) -> tuple[UUID, UUID] | None:
    """(sign-in id, business) of a refresh token whose secret is right, for signing out when the access token is already gone."""
    found = _REFRESH.match(cookie or "")
    if not found:
        return None
    sid = UUID(found.group(1))
    async with system_session() as s:
        await s.execute(text("select set_config('app.session_id', :i, true)"), {"i": str(sid)})
        row = (await s.execute(select(m.AuthSession.tenant_id, m.AuthSession.refresh_hash, m.AuthSession.refresh_prev_hash)
                               .where(m.AuthSession.id == sid))).one_or_none()
    if row is None or not any(h and hmac.compare_digest(_hash(found.group(2)), h) for h in (row.refresh_hash, row.refresh_prev_hash)):
        return None
    return sid, row.tenant_id


async def _from_database(c: tokens.Claims) -> tuple[int, bool] | None:
    """The truth about this token's sign-in: (the person's current version, whether this very sign-in is still good), or None if the person
    is gone or locked, or the sign-in was ended."""
    async with tenant_session(c.tenant_id) as s:
        user = await s.get(m.AppUser, c.user_id)
        row = await s.get(m.AuthSession, c.sid)
        if user is None or user.status != "active" or row is None or row.revoked_at is not None:
            return None
        return user.token_version, True


async def verify(cookie: str, now: datetime | None = None) -> tokens.Claims | None:
    """The claims of a sign-in that is still good (`stale` set when it must be given a new token), or None."""
    now = now or datetime.now(UTC)
    c = tokens.decode(cookie, now)
    if c is None:
        return None
    store = get_store()
    cached = True
    try:
        current = await store.get(c.user_id)
    except StoreDown:
        current, cached = None, False
    if current == c.version:
        return c  # the common case: one GET, nothing else
    truth = await _from_database(c)  # no number cached, or the token is not at it: ask whether this sign-in is good
    if truth is None:
        return None
    current = truth[0]
    if cached:
        await store.set(c.user_id, current)
    if current == c.version:
        return c
    return replace(c, stale=True) if current > c.version else None


async def renew(c: tokens.Claims, now: datetime) -> str | None:
    """A fresh access token for an active sign-in, at the person's current version (what a token one version behind is given). None if the person or the sign-in is no longer good."""
    async with tenant_session(c.tenant_id) as s:
        user = await s.get(m.AppUser, c.user_id)
        row = await s.get(m.AuthSession, c.sid)
        tenant = await s.get(m.Tenant, c.tenant_id)
        if user is None or tenant is None or user.status != "active" or row is None or row.revoked_at is not None:
            return None
        return tokens.issue(user, tenant, c.sid, c.auth_time, now)


async def reissue(s: AsyncSession, user_id: UUID, sid: UUID, auth_time: datetime, now: datetime) -> str:
    """A token for a sign-in that must survive its person's version being raised (they changed their own password, or their own email)."""
    user = await s.get(m.AppUser, user_id, populate_existing=True)
    tenant = await s.get(m.Tenant, user.tenant_id)
    return tokens.issue(user, tenant, sid, auth_time, now)


async def _bump(s: AsyncSession, user_id: UUID) -> int:
    version = (await s.execute(update(m.AppUser).where(m.AppUser.id == user_id).values(token_version=m.AppUser.token_version + 1)
                               .returning(m.AppUser.token_version))).scalar_one()
    await get_store().set(user_id, version)  # before the commit on purpose: if the commit fails the cost is a re-check, never a missed sign-out
    return version


async def revoke(s: AsyncSession, session_id: UUID, reason: str, now: datetime) -> bool:
    """Ends one sign-in on its own (a sign-out, or «sign this device out»), at once: its row is marked and the person's version is raised, so
    that token is checked against the database on its next request and found revoked. The person's other devices are found good and re-issued."""
    user_id = (await s.execute(update(m.AuthSession).where(m.AuthSession.id == session_id, m.AuthSession.revoked_at.is_(None))
                               .values(revoked_at=now, revoked_reason=reason).returning(m.AuthSession.user_id))).scalar_one_or_none()
    if user_id is None:
        return False
    await _bump(s, user_id)
    return True


async def revoke_user(s: AsyncSession, user_id: UUID, reason: str, now: datetime, *, keep: UUID | None = None) -> int:
    """Ends every sign-in of a person at once: every row is marked revoked and the version is raised. `keep`: that one sign-in goes on, so its
    holder must be given a fresh token (`reissue`). Returns how many sign-ins ended."""
    q = update(m.AuthSession).where(m.AuthSession.user_id == user_id, m.AuthSession.revoked_at.is_(None))
    if keep is not None:
        q = q.where(m.AuthSession.id != keep)
    ended = (await s.execute(q.values(revoked_at=now, revoked_reason=reason))).rowcount
    await _bump(s, user_id)
    return ended


async def active_for(s: AsyncSession, user_id: UUID, now: datetime) -> list[m.AuthSession]:
    return list((await s.execute(select(m.AuthSession).where(
        m.AuthSession.user_id == user_id, m.AuthSession.revoked_at.is_(None), m.AuthSession.expires_at > now, m.AuthSession.refresh_expires_at > now)
        .order_by(m.AuthSession.created_at.desc()))).scalars())
