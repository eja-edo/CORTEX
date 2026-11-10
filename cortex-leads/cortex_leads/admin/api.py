"""The platform admin API (WP47), mounted at /api/admin. Apart from the console's /api/v1: its own sign-in (`admin/auth.py`), and every
endpoint other than the sign-in steps needs `ADMIN`. `tests/console/test_platform_admin.py` holds every route to that decision."""
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cortex_leads.admin import auth, service
from cortex_leads.admin.auth import ADMIN, AdminSession
from cortex_leads.admin.service import AdminError
from cortex_leads.audit import context as audit_context
from cortex_leads.audit.service import record_new
from cortex_leads.auth import mfa, passwords, throttle
from cortex_leads.config import get_settings
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session

router = APIRouter()
PUBLIC = {("POST", "/session/login"), ("POST", "/session/mfa"), ("POST", "/session/logout")}  # every other route needs a signed-in admin


def _refuse(e: AdminError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "message": e.message})


def _me(sess: AdminSession) -> dict[str, Any]:
    return {"email": sess.email, "name": sess.name, "csrf": sess.csrf, "expires_at": wire(sess.expires_at)}


def _log_email(email: str) -> str:
    e = email.strip().lower()
    return e[:120] if "@" in e and " " not in e and len(e) <= 120 else "(không phải email)"


GENERIC = HTTPException(401, {"code": "BAD_CREDENTIALS", "message": "Email hoặc mật khẩu không đúng."})
LOCKED = lambda wait: HTTPException(429, {"code": "LOGIN_LOCKED", "message": "Quá nhiều lần thử. Hãy đợi rồi thử lại.", "retry_after_s": wait},
                                    headers={"Retry-After": str(wait)})


# --- signing in ---------------------------------------------------------------------------------------------------------------------------
class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=passwords.MAX_LEN)


@router.post("/session/login")
async def login(body: Login, request: Request, response: Response) -> dict[str, Any]:
    """The password step. Right password = a 5-minute challenge cookie and nothing else; the session is made only by the code step.
    An admin without two-step sign-in is refused like a wrong password (it is set up in the terminal, never here)."""
    now = datetime.now(UTC)
    info = audit_context.current()
    email = body.email.strip().lower()
    keys = [auth.account_key(email), throttle.ip_key(info.ip)]
    async with system_session() as s:
        if wait := await throttle.locked_for(s, keys, now):
            raise LOCKED(wait)
    admin = await auth.lookup(email)
    ok = passwords.verify_password(body.password, admin.password_hash if admin else None)  # always hashes: timing tells nothing
    usable = admin is not None and admin.status == "active" and admin.mfa_enabled_at is not None
    if not ok or not usable:
        cfg = get_settings()
        async with system_session() as s:
            await throttle.fail(s, keys[0], now, limit=cfg.LOGIN_MAX_FAILURES, window=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES * 2),
                                lock=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES))
            await throttle.fail(s, keys[1], now, limit=cfg.LOGIN_IP_MAX_FAILURES, window=timedelta(minutes=cfg.LOGIN_IP_WINDOW_MINUTES),
                                lock=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES))
        why = "unknown_email" if admin is None else "bad_password" if not ok else "disabled" if admin.status != "active" else "no_mfa"
        await record_new(None, actor=f"admin:{_log_email(email)}", role=service.ROLE, category="auth", action="admin.login.failed", result="failed",
                         summary="Đăng nhập trang quản trị thất bại", metadata={"reason": why})
        raise GENERIC
    response.set_cookie(auth.CHALLENGE_COOKIE, auth.challenge(admin.id, admin.token_version, now), httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", max_age=int(auth.CHALLENGE_TTL.total_seconds()), path=auth.CHALLENGE_PATH)
    return {"mfa_required": True}


class Code(BaseModel):
    code: str = Field(min_length=6, max_length=24)


@router.post("/session/mfa")
async def sign_in_code(body: Code, request: Request, response: Response) -> dict[str, Any]:
    """The code step: the 6-digit code, or one recovery code (struck off by this). Only the holder of the challenge cookie gets here."""
    now = datetime.now(UTC)
    info = audit_context.current()
    got = auth.read_challenge(request.cookies.get(auth.CHALLENGE_COOKIE), now)
    if got is None:
        raise HTTPException(401, {"code": "MFA_EXPIRED", "message": "Đã quá thời gian nhập mã. Hãy đăng nhập lại từ đầu."})
    admin_id, version = got
    async with system_session() as s:
        if wait := await throttle.locked_for(s, [auth.code_key(admin_id), throttle.ip_key(info.ip)], now):
            raise LOCKED(wait)
    method, row = None, None
    async with system_session() as s:
        row = await s.get(m.PlatformAdmin, admin_id, with_for_update=True)
        if row is not None and row.status == "active" and row.token_version == version and row.mfa_enabled_at is not None:
            method = mfa.use_code(row, body.code, now)
            if method:
                row.last_login_at = now
        email = row.email if row else "?"
        left = len(row.mfa_recovery or []) if row else 0
    if method is None:
        locked = await auth.count_wrong_code(admin_id, now)
        await record_new(None, actor=f"admin:{email}", role=service.ROLE, category="auth", action="admin.login.mfa_failed", result="failed",
                         summary="Sai mã xác thực 2 lớp ở trang quản trị" + (" (khoá tạm)" if locked else ""))
        raise HTTPException(401, {"code": "BAD_MFA_CODE", "message": "Mã không đúng hoặc đã được dùng."})
    async with system_session() as s:
        await throttle.clear(s, auth.account_key(email))
        await throttle.clear(s, auth.code_key(admin_id))
    expires = auth.expiry(now, now)
    auth.set_cookie(response, request, auth.issue(row, now, now), now, expires)
    response.delete_cookie(auth.CHALLENGE_COOKIE, path=auth.CHALLENGE_PATH)
    await record_new(None, actor=f"admin:{email}", role=service.ROLE, category="auth", action="admin.login.ok", summary="Đăng nhập trang quản trị",
                     metadata={"mfa": method})
    me = _me(AdminSession(row.id, row.email, row.display_name, auth.csrf_for(row.id, now), now, expires))
    return {**me, **({"recovery_left": left} if method == "recovery" else {})}


@router.get("/session")
async def me(sess: AdminSession = ADMIN) -> dict[str, Any]:
    return _me(sess)


@router.post("/session/logout")
async def logout(request: Request) -> Any:
    """Ends every sign-in of this admin (the version is raised): an admin page left open on another machine is closed too. Works with an
    expired token as well (there is nothing to end then, but the cookie still goes)."""
    now = datetime.now(UTC)
    c = auth.decode(request.cookies.get(auth.COOKIE), now)
    sess = None
    if c is not None:
        try:
            sess = await auth.admin_dep(request, Response())  # the CSRF check, as for any state-changing call
        except HTTPException as e:
            if e.status_code != 401:
                raise
    if sess is not None:
        async with system_session() as s:
            row = await s.get(m.PlatformAdmin, sess.admin_id, with_for_update=True)
            row.token_version += 1
        await record_new(None, actor=sess.actor, role=service.ROLE, category="auth", action="admin.logout", summary="Đăng xuất trang quản trị")
    out = JSONResponse({"ok": True})
    auth.clear_cookies(out)
    return out


# --- businesses ---------------------------------------------------------------------------------------------------------------------------
@router.get("/tenants")
async def tenants(sess: AdminSession = ADMIN) -> dict[str, Any]:
    return {"items": await service.list_tenants()}


class NewTenant(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    timezone: str = Field(default="Asia/Ho_Chi_Minh", max_length=64)
    owner_email: str = Field(min_length=3, max_length=254)
    owner_name: str = Field(min_length=2, max_length=80)


@router.post("/tenants", status_code=201)
async def new_tenant(body: NewTenant, sess: AdminSession = ADMIN) -> dict[str, Any]:
    """The business, all its sandboxes, and its first owner invited by mail. Without mail nothing is made (checked first, so a business
    is never left without anyone who can open it)."""
    from cortex_leads.auth import links
    from cortex_leads.auth.users import AccountError, normalise_email

    if not links.enabled():
        raise _refuse(service.MAIL_OFF)
    try:
        normalise_email(body.owner_email)
        service.check_name(body.name), service.check_timezone(body.timezone)
    except AccountError as e:
        raise HTTPException(422, {"code": e.code, "message": e.message}) from None
    except AdminError as e:
        raise _refuse(e) from None
    tid, _ = await service.create_tenant(body.name, body.timezone, by=sess.actor)
    try:
        inv = await service.invite_owner(tid, body.owner_email, body.owner_name, by=sess.actor)
    except AdminError as e:  # e.g. the email already belongs to someone: the business stays, the page offers to invite another owner
        return {"id": str(tid), "owner": None, "owner_error": {"code": e.code, "message": e.message}}
    return {"id": str(tid), "owner": {"email": inv.email, "mail_sent": inv.mail_sent}}


@router.get("/tenants/{tenant_id}")
async def tenant(tenant_id: UUID, sess: AdminSession = ADMIN) -> dict[str, Any]:
    try:
        return await service.tenant_detail(tenant_id)
    except AdminError as e:
        raise _refuse(e) from None


@router.post("/tenants/{tenant_id}/sandboxes/ensure")
async def ensure(tenant_id: UUID, sess: AdminSession = ADMIN) -> dict[str, Any]:
    try:
        return {"added": await service.add_missing_sandboxes(tenant_id, by=sess.actor)}
    except AdminError as e:
        raise _refuse(e) from None


class Pause(BaseModel):
    paused: bool
    sandbox_id: UUID | None = None


@router.post("/tenants/{tenant_id}/ai")
async def pause(tenant_id: UUID, body: Pause, sess: AdminSession = ADMIN) -> dict[str, Any]:
    try:
        changed = await service.pause(tenant_id, body.paused, by=sess.actor, sandbox_id=body.sandbox_id)
    except AdminError as e:
        raise _refuse(e) from None
    return {"changed": changed}


class PauseAll(BaseModel):
    paused: bool
    code: str = Field(min_length=6, max_length=8)


@router.post("/ai")
async def pause_all(body: PauseAll, sess: AdminSession = ADMIN) -> dict[str, Any]:
    """Every business at once. Needs the admin's code from the app, now."""
    now = datetime.now(UTC)
    await auth.check_code(sess, body.code, now)
    out = await service.pause_all(body.paused, by=sess.actor, now=now)
    await record_new(None, actor=sess.actor, role=service.ROLE, category="control", action="killswitch.pause_all" if body.paused else "killswitch.resume_all",
                     summary=("Tạm dừng" if body.paused else "Cho chạy lại") + " AI của mọi doanh nghiệp", metadata=out)
    return out


class Owner(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=2, max_length=80)


@router.post("/tenants/{tenant_id}/owners", status_code=201)
async def add_owner(tenant_id: UUID, body: Owner, sess: AdminSession = ADMIN) -> dict[str, Any]:
    try:
        inv = await service.invite_owner(tenant_id, body.email, body.name, by=sess.actor)
    except AdminError as e:
        raise _refuse(e) from None
    return {"id": str(inv.user_id), "email": inv.email, "mail_sent": inv.mail_sent}


@router.post("/tenants/{tenant_id}/users/{user_id}/send-link")
async def send_link(tenant_id: UUID, user_id: UUID, sess: AdminSession = ADMIN) -> dict[str, Any]:
    try:
        inv = await service.send_link(tenant_id, user_id, by=sess.actor)
    except AdminError as e:
        raise _refuse(e) from None
    return {"email": inv.email, "mail_sent": inv.mail_sent, "kind": inv.kind}


class Edit(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    code: str | None = Field(default=None, min_length=6, max_length=6)  # needed only to move the email of an account already in use


@router.patch("/tenants/{tenant_id}/users/{user_id}")
async def edit_account(tenant_id: UUID, user_id: UUID, body: Edit, sess: AdminSession = ADMIN) -> dict[str, Any]:
    now = datetime.now(UTC)
    if body.code is not None:
        await auth.check_code(sess, body.code, now)
    try:
        r = await service.edit_account(tenant_id, user_id, name=body.name, email=body.email, by=sess.actor, code_ok=body.code is not None, now=now)
    except AdminError as e:
        raise _refuse(e) from None
    return {"email": r.email, "name": r.name, "email_moved": r.email_moved, "sessions_ended": r.sessions_ended, "mail_sent": r.mail_sent}


@router.post("/tenants/{tenant_id}/users/{user_id}/mfa/reset")
async def reset_mfa(tenant_id: UUID, user_id: UUID, body: Code, sess: AdminSession = ADMIN) -> dict[str, Any]:
    """Turning off someone's second step is how an attacker holding an admin session would take an account over: the admin's code, now."""
    now = datetime.now(UTC)
    await auth.check_code(sess, body.code, now)
    try:
        return {"sessions_ended": await service.reset_mfa(tenant_id, user_id, by=sess.actor, now=now)}
    except AdminError as e:
        raise _refuse(e) from None


@router.post("/tenants/{tenant_id}/users/{user_id}/end-sessions")
async def end_sessions(tenant_id: UUID, user_id: UUID, sess: AdminSession = ADMIN) -> dict[str, Any]:
    try:
        return {"ended": await service.end_sessions(tenant_id, user_id, by=sess.actor)}
    except AdminError as e:
        raise _refuse(e) from None
