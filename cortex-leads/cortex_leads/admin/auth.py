"""Signing in to the platform admin page (WP47, DESIGN §5.16). Kept apart from the console's sign-in on purpose: its own table
(`platform_admin`), its own signing key, its own cookie that only `/api/admin` ever receives, its own CSRF key. A token of the console
does not decode here and a token of this page does not decode there.

Password, then always a TOTP code: an admin without two-step sign-in cannot sign in at all (it is set up in the terminal by
`cli create-admin`, so there is no moment when a password alone opens anything). The token is short (`ADMIN_IDLE_MINUTES` from the last
request, re-issued when half of that is gone) and never outlives `ADMIN_SESSION_HOURS`. Every request reads the admin's row again:
there are a handful of admins and few requests, so the database is asked each time and a disabled account or a sign-out is felt at once."""
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import func, select

from cortex_leads.audit import context as audit_context
from cortex_leads.auth import mfa, throttle
from cortex_leads.config import get_settings
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session

COOKIE = "cl_admin"
PATH = "/api/admin"
CHALLENGE_COOKIE = "cl_admin_mfa"
CHALLENGE_PATH = "/api/admin/session"
CHALLENGE_TTL = timedelta(minutes=5)
ISS = "cortex-leads"
AUD = "admin"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _key(label: bytes) -> bytes:
    cfg = get_settings()
    return hashlib.sha256(label + (cfg.JWT_SECRET or cfg.CONNECTOR_SECRET_KEY).encode()).digest()


def account_key(email: str) -> str:
    """The guessing counter of one admin account; apart from a business account with the same address."""
    return "admin:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


def code_key(admin_id: UUID) -> str:
    return "admin-mfa:" + hashlib.sha256(str(admin_id).encode()).hexdigest()[:32]


# --- the token -----------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Claims:
    admin_id: UUID
    version: int
    auth_time: datetime
    expires_at: datetime


def expiry(auth_time: datetime, now: datetime) -> datetime:
    cfg = get_settings()
    return min(now + timedelta(minutes=cfg.ADMIN_IDLE_MINUTES), auth_time + timedelta(hours=cfg.ADMIN_SESSION_HOURS))


def issue(admin: m.PlatformAdmin, auth_time: datetime, now: datetime) -> str:
    return jwt.encode({"iss": ISS, "aud": AUD, "sub": str(admin.id), "ver": admin.token_version, "iat": int(now.timestamp()),
                       "exp": int(expiry(auth_time, now).timestamp()), "ac": int(auth_time.timestamp())}, _key(b"admin-jwt|"), algorithm="HS256")


def decode(token: str | None, now: datetime) -> Claims | None:
    try:
        p = jwt.decode(token or "", _key(b"admin-jwt|"), algorithms=["HS256"], issuer=ISS, audience=AUD,
                       options={"require": ["exp", "iat", "sub", "ver", "ac", "aud"], "verify_exp": False})
        c = Claims(UUID(p["sub"]), int(p["ver"]), datetime.fromtimestamp(p["ac"], UTC), datetime.fromtimestamp(p["exp"], UTC))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None
    if c.expires_at <= now or c.auth_time + timedelta(hours=get_settings().ADMIN_SESSION_HOURS) <= now:
        return None
    return c


def csrf_for(admin_id: UUID, auth_time: datetime) -> str:
    """Tied to the sign-in (who and when), so a re-issued token keeps the page's token valid."""
    return hmac.new(_key(b"admin-csrf|"), f"{admin_id}|{int(auth_time.timestamp())}".encode(), hashlib.sha256).hexdigest()[:32]


def set_cookie(response: Response, request: Request, token: str, now: datetime, expires_at: datetime) -> None:
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=max(1, int((expires_at - now).total_seconds())), path=PATH)


def clear_cookies(response: Response) -> None:
    response.delete_cookie(COOKIE, path=PATH)
    response.delete_cookie(CHALLENGE_COOKIE, path=CHALLENGE_PATH)


# --- between the password and the code -----------------------------------------------------------------------------------------------------
def challenge(admin_id: UUID, version: int, now: datetime) -> str:
    return jwt.encode({"sub": str(admin_id), "ver": version, "aud": "admin-mfa", "iat": int(now.timestamp()),
                       "exp": int((now + CHALLENGE_TTL).timestamp())}, _key(b"admin-mfa|"), algorithm="HS256")


def read_challenge(token: str | None, now: datetime) -> tuple[UUID, int] | None:
    try:
        c = jwt.decode(token or "", _key(b"admin-mfa|"), algorithms=["HS256"], audience="admin-mfa", options={"require": ["sub", "ver", "exp"]})
        if c["exp"] <= int(now.timestamp()):
            return None
        return UUID(c["sub"]), int(c["ver"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


# --- the signed-in admin -------------------------------------------------------------------------------------------------------------------
@dataclass
class AdminSession:
    admin_id: UUID
    email: str
    name: str
    csrf: str
    auth_time: datetime
    expires_at: datetime

    @property
    def actor(self) -> str:
        return f"admin:{self.email}"


async def lookup(email: str) -> m.PlatformAdmin | None:
    async with system_session() as s:
        return (await s.execute(select(m.PlatformAdmin).where(func.lower(m.PlatformAdmin.email) == email.strip().lower()))).scalar_one_or_none()


def _unauth() -> HTTPException:
    return HTTPException(401, {"code": "ADMIN_SIGNED_OUT", "message": "Phiên quản trị đã hết. Hãy đăng nhập lại."})


async def admin_dep(request: Request, response: Response) -> AdminSession:
    now = datetime.now(UTC)
    c = decode(request.cookies.get(COOKIE), now)
    if c is None:
        raise _unauth()
    async with system_session() as s:
        row = await s.get(m.PlatformAdmin, c.admin_id)
    if row is None or row.status != "active" or row.token_version != c.version or row.mfa_enabled_at is None:
        raise _unauth()
    sess = AdminSession(row.id, row.email, row.display_name, csrf_for(row.id, c.auth_time), c.auth_time, c.expires_at)
    audit_context.current().session_id = f"a:{str(row.id)[:8]}"
    if request.method in UNSAFE and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), sess.csrf):
        raise HTTPException(403, {"code": "CSRF", "message": "Thiếu hoặc sai mã CSRF."})
    if c.expires_at - now < timedelta(minutes=get_settings().ADMIN_IDLE_MINUTES) / 2:  # sliding: busy admins are not thrown out mid-task
        sess.expires_at = expiry(c.auth_time, now)
        set_cookie(response, request, issue(row, c.auth_time, now), now, sess.expires_at)
    return sess


ADMIN = Depends(admin_dep)


async def check_code(sess: AdminSession, code: str, now: datetime) -> None:
    """The step-up for the actions that could hand someone else's account to an attacker: the admin's code from the app, now. A
    recovery code is not accepted here (it is for getting in, not for confirming). Wrong codes count toward the same lock as at sign-in."""
    info = audit_context.current()
    keys = [code_key(sess.admin_id), throttle.ip_key(info.ip)]
    async with system_session() as s:
        if wait := await throttle.locked_for(s, keys, now):
            raise HTTPException(429, {"code": "LOGIN_LOCKED", "message": "Quá nhiều lần thử. Hãy đợi rồi thử lại.", "retry_after_s": wait})
        row = (await s.execute(select(m.PlatformAdmin).where(m.PlatformAdmin.id == sess.admin_id).with_for_update())).scalar_one()
        secret = mfa.unseal(row.mfa_secret_enc)
        step = mfa.match(secret, code, now, row.mfa_last_step) if secret else None
        if step is not None:
            row.mfa_last_step = step
            return
    await count_wrong_code(sess.admin_id, now)
    raise HTTPException(401, {"code": "BAD_MFA_CODE", "message": "Mã không đúng hoặc đã được dùng."})


async def count_wrong_code(admin_id: UUID, now: datetime) -> bool:
    cfg = get_settings()
    info = audit_context.current()
    async with system_session() as s:
        locked = await throttle.fail(s, code_key(admin_id), now, limit=cfg.LOGIN_MAX_FAILURES, window=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES * 2),
                                     lock=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES))
        await throttle.fail(s, throttle.ip_key(info.ip), now, limit=cfg.LOGIN_IP_MAX_FAILURES, window=timedelta(minutes=cfg.LOGIN_IP_WINDOW_MINUTES),
                            lock=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES))
    return locked
