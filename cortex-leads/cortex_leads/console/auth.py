"""Console session (WP30). A person signs in with email and password; the browser holds a signed token (`auth/tokens.py`) in an HttpOnly
cookie. Every request checks it against the person's current version and the list of ended sign-ins (`auth/sessions.py`), so a sign-out, a password change, a disabled or
demoted account all take effect at once. State-changing calls need the CSRF token (an HMAC of the sign-in's id) in `X-CSRF-Token`;
SameSite=Strict is the first line, this the second. What a role may do is `auth/perms.py`; an endpoint names the permission it needs."""
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request, Response

from cortex_leads.audit import context as audit_context
from cortex_leads.audit.service import record_new
from cortex_leads.auth import perms, sessions, tokens
from cortex_leads.auth.roles import Role
from cortex_leads.config import get_settings
from cortex_leads.review.auth import Caller

COOKIE = "cl_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# What a person who must choose a new password may still reach: the way to do it, to see who they are, and to leave.


def _key() -> bytes:
    return hashlib.sha256(b"console-csrf|" + get_settings().CONNECTOR_SECRET_KEY.encode()).digest()


def csrf_for(sid: UUID | str) -> str:
    """Tied to the sign-in, not to the token: a re-issued token keeps the page's token valid."""
    return hmac.new(_key(), ("csrf|" + str(sid)).encode(), hashlib.sha256).hexdigest()[:32]


REFRESH_COOKIE = "cl_refresh"
REFRESH_PATH = "/api/v1/session"  # the refresh token is only ever sent to the sign-in endpoints (refresh, sign out), never to the rest of the API


def set_cookie(response: Response, request: Request, token: str, auth_time: datetime) -> None:
    """The access token's cookie: lives as long as the token does (and never past the end of the sign-in)."""
    cfg = get_settings()
    now = datetime.now(UTC)
    left = int((min(now + timedelta(minutes=cfg.ACCESS_TOKEN_MINUTES), auth_time + timedelta(hours=cfg.SESSION_ABSOLUTE_HOURS)) - now).total_seconds())
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=max(1, left), path="/")


def set_refresh_cookie(response: Response, request: Request, token: str, ends: datetime) -> None:
    response.set_cookie(REFRESH_COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=max(1, int((ends - datetime.now(UTC)).total_seconds())), path=REFRESH_PATH)


def clear_cookies(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)


@dataclass
class Session:
    caller: Caller
    tenant_name: str
    tz: ZoneInfo
    csrf: str
    user_id: UUID
    session_id: UUID
    email: str
    name: str
    auth_time: datetime

    @property
    def actor(self) -> str:
        return f"staff:{self.caller.staff_ref or self.caller.role}"

    @property
    def is_owner(self) -> bool:
        return self.caller.role == Role.OWNER

    def can(self, perm: str) -> bool:
        return perms.can(self.caller.role, perm)

    @property
    def permissions(self) -> list[str]:
        return sorted(perms.ROLE_PERMS.get(self.caller.role, ()))


def _unauth() -> HTTPException:
    return HTTPException(401, "not signed in")


def session_of(c: tokens.Claims) -> Session:
    return Session(Caller(c.tenant_id, c.role, c.staff_ref), c.tenant_name, ZoneInfo(c.tz), csrf_for(c.sid), c.user_id, c.sid, c.email, c.name, c.auth_time)


async def session_dep(request: Request, response: Response) -> Session:
    cookie = request.cookies.get(COOKIE, "")
    now = datetime.now(UTC)
    c = await sessions.verify(cookie, now)
    if c is None:
        raise _unauth()
    sess = session_of(c)
    audit_context.current().session_id = f"s:{str(c.sid)[:8]}"
    if request.method in UNSAFE and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), sess.csrf):
        await record_new(sess.caller.tenant_id, actor=sess.actor, role=sess.caller.role, category="access", action="csrf.refused",
                         result="denied", summary="Yêu cầu bị từ chối: thiếu hoặc sai mã CSRF",
                         metadata={"method": request.method, "path": request.url.path})
        raise HTTPException(403, "CSRF token missing or invalid")
    if c.stale:  # made at an older version but its sign-in is still good: given a token at the current one
        fresh = await sessions.renew(c, now)
        if fresh is None:
            raise _unauth()
        set_cookie(response, request, fresh, c.auth_time)
    return sess


def need(perm: str):  # type: ignore[no-untyped-def]
    """The dependency of an endpoint that needs `perm`. A refusal is itself a line in the activity log."""
    if not any(perm in p for p in perms.ROLE_PERMS.values()):
        raise ValueError(f"unknown permission: {perm}")

    async def dep(request: Request, sess: Session = Depends(session_dep)) -> Session:
        if not sess.can(perm):
            await record_new(sess.caller.tenant_id, actor=sess.actor, role=sess.caller.role, category="access", action="permission.refused",
                             result="denied", summary="Thử làm việc vượt quyền của vai trò", metadata={"path": request.url.path, "needs": perm})
            raise HTTPException(403, {"code": "FORBIDDEN", "message": "Bạn không có quyền làm việc này."})
        return sess

    dep.perm = perm  # type: ignore[attr-defined]  # read by the test that holds every class endpoint to a decision
    return Depends(dep)


ANY = Depends(session_dep)  # signed in; nothing more is asked (the account endpoints)
