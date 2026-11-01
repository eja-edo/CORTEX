"""Console session (WP30). A person signs in with email and password; the browser holds an opaque cookie that names a server-side
session (`auth/sessions.py`). Every request re-reads the session and the account, so a sign-out, a password change, a disabled or
demoted account all take effect at once. State-changing calls need the CSRF token (an HMAC of the cookie) in `X-CSRF-Token`;
SameSite=Strict is the first line, this the second. What a role may do is `auth/perms.py`; an endpoint names the permission it needs."""
import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request

from cortex_leads.audit import context as audit_context
from cortex_leads.audit.service import record_new
from cortex_leads.auth import perms, sessions
from cortex_leads.config import get_settings
from cortex_leads.review.auth import Caller

COOKIE = "cl_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# What a person who must choose a new password may still reach: the way to do it, to see who they are, and to leave.
STILL_ALLOWED = {"/api/v1/session", "/api/v1/session/password", "/api/v1/session/logout"}


def _key() -> bytes:
    return hashlib.sha256(b"console-csrf|" + get_settings().CONNECTOR_SECRET_KEY.encode()).digest()


def csrf_for(cookie: str) -> str:
    return hmac.new(_key(), ("csrf|" + cookie).encode(), hashlib.sha256).hexdigest()[:32]


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
    must_change_password: bool = False

    @property
    def actor(self) -> str:
        return f"staff:{self.caller.staff_ref or self.caller.role}"

    @property
    def is_owner(self) -> bool:
        return self.caller.role == "owner"

    def can(self, perm: str) -> bool:
        return perms.can(self.caller.role, perm)

    @property
    def permissions(self) -> list[str]:
        return sorted(perms.ROLE_PERMS.get(self.caller.role, ()))


def _unauth() -> HTTPException:
    return HTTPException(401, "not signed in")


async def session_dep(request: Request) -> Session:
    cookie = request.cookies.get(COOKIE, "")
    found = await sessions.resolve(cookie)
    if found is None:
        raise _unauth()
    u = found.user
    sess = Session(Caller(u.tenant_id, u.role, u.staff_ref), found.tenant.name, ZoneInfo(found.tenant.timezone), csrf_for(cookie), u.id,
                   found.session_id, u.email, u.display_name, u.must_change_password)
    audit_context.current().session_id = f"s:{str(found.session_id)[:8]}"
    if request.method in UNSAFE and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), sess.csrf):
        await record_new(sess.caller.tenant_id, actor=sess.actor, role=sess.caller.role, category="access", action="csrf.refused",
                         result="denied", summary="Yêu cầu bị từ chối: thiếu hoặc sai mã CSRF",
                         metadata={"method": request.method, "path": request.url.path})
        raise HTTPException(403, "CSRF token missing or invalid")
    if sess.must_change_password and request.url.path not in STILL_ALLOWED:
        raise HTTPException(403, {"code": "PASSWORD_CHANGE_REQUIRED", "message": "Bạn cần đặt mật khẩu mới trước khi dùng tiếp."})
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

    return Depends(dep)


ANY = Depends(session_dep)  # signed in; nothing more is asked (the account endpoints)
