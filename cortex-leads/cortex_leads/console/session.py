"""Sign-in (password, then the 6-digit code for someone who turned two-step sign-in on), who am I, my password, my sessions, and the
kill switch (sidebar state)."""
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from cortex_leads.audit import context as audit_context
from cortex_leads.audit.service import record_new
from cortex_leads.auth import mfa, passwords, sessions, throttle, tokens
from cortex_leads.auth.perms import Perm
from cortex_leads.auth.users import AccountError, lookup_for_login, set_password
from cortex_leads.config import get_settings
from cortex_leads.console import auth
from cortex_leads.console.auth import ANY, Session, need
from cortex_leads.console.killswitch import set_paused
from cortex_leads.console.trail import audit
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session

router = APIRouter()


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=passwords.MAX_LEN)


async def _state(sess: Session) -> dict[str, Any]:
    """What the sidebar shows: is the AI running, in which mode, how many customers need a person."""
    async with tenant_session(sess.caller.tenant_id) as s:
        sbs = (await s.execute(select(m.Sandbox).where(m.Sandbox.purpose == "customer_care"))).scalars().all()
        need_ = (await s.execute(select(func.count(func.distinct(m.Draft.conversation_id))).where(
            m.Draft.status == "proposed", m.Draft.needs_human.is_(True)))).scalar_one()
    paused = bool(sbs) and all(x.status == "paused" for x in sbs)
    modes = {x.send_mode for x in sbs}
    return {"ai": "paused" if paused else "running" if sbs else "none",
            "mode": "auto" if modes == {"auto"} else "manual" if modes <= {"manual"} else "mixed",
            "needs_person": need_ if sess.can(Perm.INBOX_USE) else 0}


async def _me(sess: Session) -> dict[str, Any]:
    return {"role": sess.caller.role, "staff_ref": sess.caller.staff_ref, "tenant": sess.tenant_name, "timezone": str(sess.tz), "csrf": sess.csrf,
            "email": sess.email, "name": sess.name, "permissions": sess.permissions,
            **(await _state(sess))}


def _email_for_log(email: str) -> str:
    """The address typed, for tracing. Anything that does not look like one (a password pasted into the wrong box) is never kept."""
    e = email.strip().lower()
    return e[:120] if "@" in e and " " not in e and len(e) <= 120 else "(không phải email)"


GENERIC = HTTPException(401, {"code": "BAD_CREDENTIALS", "message": "Email hoặc mật khẩu không đúng."})  # the same answer for every cause


@router.post("/session/login")
async def login(body: Login, response: Response, request: Request) -> dict[str, Any]:
    now = datetime.now(UTC)
    info = audit_context.current()
    email = body.email.strip().lower()
    keys = [throttle.account_key(email), throttle.ip_key(info.ip)]
    async with system_session() as s:
        wait = await throttle.locked_for(s, keys, now)
    if wait:  # no password is even looked at: guessing during a lock gets nothing, not even a timing
        raise HTTPException(429, {"code": "LOGIN_LOCKED", "message": "Quá nhiều lần thử. Hãy đợi rồi thử lại.", "retry_after_s": wait},
                            headers={"Retry-After": str(wait)})
    user = await lookup_for_login(email)
    ok = passwords.verify_password(body.password, user.password_hash if user else None)  # always hashes, so timing does not tell
    if not ok or user is None or user.status != "active":
        why = "unknown_email" if user is None else "disabled" if user.status != "active" and ok else "bad_password"
        async with system_session() as s:
            locked = await throttle.register_failure(s, email, info.ip, now)
        meta = {"reason": why, "email": _email_for_log(email), **({"locked": True} if locked else {})}
        await record_new(user.tenant_id if user else None, actor=f"staff:{user.staff_ref}" if user else "unknown", role=user.role if user else "unknown",
                         category="auth", action="login.failed", result="failed", obj=("user", str(user.id), user.display_name) if user else None,
                         summary="Đăng nhập thất bại: " + {"unknown_email": "không có tài khoản này", "disabled": "tài khoản đã bị khoá", "bad_password": "sai mật khẩu"}[why]
                         + (" (tài khoản bị khoá tạm)" if locked else ""), metadata=meta)
        raise GENERIC
    if user.mfa_enabled_at is not None:  # the password was right; the session waits for the code (see auth/mfa.py)
        response.set_cookie(mfa.CHALLENGE_COOKIE, mfa.challenge(user.id, user.tenant_id, user.token_version, now), httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=int(mfa.CHALLENGE_TTL.total_seconds()), path=mfa.CHALLENGE_PATH)
        return {"mfa_required": True}
    return await _sign_in(request, response, user.id, user.tenant_id, email, now)


async def _sign_in(request: Request, response: Response, user_id: UUID, tenant_id: UUID, email: str, now: datetime, method: str | None = None) -> dict[str, Any]:
    """The one way a sign-in is made, after the password alone or after the password and the code."""
    info = audit_context.current()
    async with tenant_session(tenant_id) as s:
        row = await s.get(m.AppUser, user_id)
        tenant = await s.get(m.Tenant, row.tenant_id)
        cookie, refresh_cookie = await sessions.create(s, row, tenant, ip=info.ip, user_agent=info.user_agent, now=now)
        row.last_login_at = now
        actor, role, name = f"staff:{row.staff_ref}", row.role, row.display_name
    async with system_session() as s:
        await throttle.clear_account(s, email)
        await throttle.clear(s, mfa.throttle_key(user_id))
    claims = tokens.decode(cookie, now)
    sid = claims.sid
    auth.set_cookie(response, request, cookie, now)
    auth.set_refresh_cookie(response, request, refresh_cookie, now + timedelta(days=get_settings().REFRESH_TOKEN_DAYS))
    audit_context.current().session_id = f"s:{str(sid)[:8]}"
    await record_new(tenant_id, actor=actor, role=role, category="auth", action="login.ok", summary="Đăng nhập" + (" (có mã xác thực 2 lớp)" if method else ""),
                     obj=("user", str(user_id), name), metadata={"email": email, **({"mfa": method} if method else {})})
    sess = auth.session_of(claims)
    return await _me(sess)


class Code(BaseModel):
    code: str = Field(min_length=6, max_length=24)


BAD_CODE = HTTPException(401, {"code": "BAD_MFA_CODE", "message": "Mã không đúng hoặc đã được dùng."})


@router.post("/session/mfa")
async def sign_in_code(body: Code, request: Request, response: Response) -> dict[str, Any]:
    """The second step: the 6-digit code from the app, or one recovery code (used up by this). Only the person who just gave the right
    password holds the cookie that lets this run; wrong codes count toward a lock of their own, as wrong passwords do."""
    now = datetime.now(UTC)
    info = audit_context.current()
    got = mfa.read_challenge(request.cookies.get(mfa.CHALLENGE_COOKIE), now)
    if got is None:
        raise HTTPException(401, {"code": "MFA_EXPIRED", "message": "Đã quá thời gian nhập mã. Hãy đăng nhập lại từ đầu."})
    user_id, tenant_id, version = got
    key = mfa.throttle_key(user_id)
    async with system_session() as s:
        wait = await throttle.locked_for(s, [key, throttle.ip_key(info.ip)], now)
    if wait:
        raise HTTPException(429, {"code": "LOGIN_LOCKED", "message": "Quá nhiều lần thử. Hãy đợi rồi thử lại.", "retry_after_s": wait},
                            headers={"Retry-After": str(wait)})
    method, email, actor, role, name, left = None, "", "unknown", "unknown", None, None
    async with tenant_session(tenant_id) as s:
        u = (await s.execute(select(m.AppUser).where(m.AppUser.id == user_id).with_for_update())).scalar_one_or_none()
        if u is not None and u.status == "active" and u.token_version == version and u.mfa_enabled_at is not None:
            method = mfa.use_code(u, body.code, now)
            email, actor, role, name, left = u.email, f"staff:{u.staff_ref}", u.role, u.display_name, len(u.mfa_recovery or [])
    if method is None:
        cfg = get_settings()
        async with system_session() as s:
            locked = await throttle.fail(s, key, now, limit=cfg.LOGIN_MAX_FAILURES, window=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES * 2),
                                         lock=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES))
            await throttle.fail(s, throttle.ip_key(info.ip), now, limit=cfg.LOGIN_IP_MAX_FAILURES, window=timedelta(minutes=cfg.LOGIN_IP_WINDOW_MINUTES),
                                lock=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES))
        await record_new(tenant_id, actor=actor, role=role, category="auth", action="login.mfa_failed", result="failed",
                         obj=("user", str(user_id), name) if name else None, summary="Đăng nhập thất bại: sai mã xác thực 2 lớp" + (" (khoá tạm)" if locked else ""),
                         metadata={"locked": True} if locked else None)
        raise BAD_CODE
    response.delete_cookie(mfa.CHALLENGE_COOKIE, path=mfa.CHALLENGE_PATH)
    me = await _sign_in(request, response, user_id, tenant_id, email, now, method)
    return {**me, **({"recovery_left": left} if method == "recovery" else {})}


@router.get("/session")
async def me(sess: Session = ANY) -> dict[str, Any]:
    return await _me(sess)


@router.post("/session/refresh")
async def refresh(request: Request, response: Response) -> Any:
    """Swaps the refresh token for a new access token and a new refresh token. Public in the sense that the access token is exactly what is gone;
    the refresh token (cookie, SameSite=Strict, sent only to /api/v1/session) is the credential."""
    info = audit_context.current()
    got = await sessions.refresh(request.cookies.get(auth.REFRESH_COOKIE, ""), ip=info.ip, user_agent=info.user_agent)
    if got.access is None:
        if got.reason == "reused" and got.tenant_id:
            await record_new(got.tenant_id, actor="system:refresh", role="system", category="access", action="refresh.reused", result="denied",
                             summary="Một mã làm mới đã dùng được đưa lại: đăng nhập đó bị kết thúc", obj=("user", str(got.user_id), None))
        refused = JSONResponse({"detail": {"code": "REFRESH_INVALID", "message": "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại."}}, status_code=401)
        auth.clear_cookies(refused)  # an exception would drop the cookies being cleared
        return refused
    claims = tokens.decode(got.access)
    auth.set_cookie(response, request, got.access, claims.auth_time)
    if got.refresh:  # None: two tabs raced and the other one already holds the new refresh token
        auth.set_refresh_cookie(response, request, got.refresh, got.refresh_ends)
    return await _me(auth.session_of(claims))


@router.post("/session/logout")
async def logout(request: Request, response: Response) -> Any:
    """Ends this sign-in. Works with only the refresh token too, so a person whose access token has run out can still sign out for good."""
    now = datetime.now(UTC)
    try:
        sess: Session | None = await auth.session_dep(request, response)
    except HTTPException as e:
        if e.status_code != 401:
            raise  # a bad CSRF token is refused, as for any state-changing call
        sess = None
    if sess is not None:
        sid, tenant_id, actor, role = sess.session_id, sess.caller.tenant_id, sess.actor, sess.caller.role
    else:
        found = await sessions.sign_in_of_refresh(request.cookies.get(auth.REFRESH_COOKIE, ""))
        sid, tenant_id, actor, role = (found[0], found[1], "staff:?", "unknown") if found else (None, None, "", "")
    if sid is None:  # nothing here names a sign-in: there is nothing to end (the cookies are cleared all the same)
        nobody = JSONResponse({"detail": "not signed in"}, status_code=401)
        auth.clear_cookies(nobody)
        return nobody
    async with tenant_session(tenant_id) as s:
        await sessions.revoke(s, sid, "logout", now)
    await record_new(tenant_id, actor=actor, role=role, category="auth", action="logout", summary="Đăng xuất")
    auth.clear_cookies(response)
    return {"status": "ok"}


class NewPassword(BaseModel):
    current: str = Field(min_length=1, max_length=passwords.MAX_LEN)
    new: str = Field(min_length=1, max_length=passwords.MAX_LEN)


@router.post("/session/password")
async def change_password(body: NewPassword, response: Response, request: Request, sess: Session = need(Perm.ACCOUNT_SELF)) -> dict[str, Any]:
    """The person's own password. Needs the current one (a stolen session alone cannot take the account over), and ends every other
    sign-in of theirs. Wrong current passwords count toward the same lock as at sign-in."""
    now = datetime.now(UTC)
    info = audit_context.current()
    async with system_session() as s:
        wait = await throttle.locked_for(s, [throttle.account_key(sess.email)], now)
    if wait:
        raise HTTPException(429, {"code": "LOGIN_LOCKED", "message": "Quá nhiều lần thử. Hãy đợi rồi thử lại.", "retry_after_s": wait})
    async with tenant_session(sess.caller.tenant_id) as s:
        user = await s.get(m.AppUser, sess.user_id)
        if not passwords.verify_password(body.current, user.password_hash):
            async with system_session() as t:
                await throttle.register_failure(t, sess.email, info.ip, now)
            await record_new(sess.caller.tenant_id, actor=sess.actor, role=sess.caller.role, category="auth", action="password.change_failed",
                             result="failed", summary="Đổi mật khẩu thất bại: sai mật khẩu hiện tại")
            raise HTTPException(403, {"code": "BAD_CURRENT_PASSWORD", "message": "Mật khẩu hiện tại không đúng."})
        if passwords.verify_password(body.new, user.password_hash):
            raise HTTPException(422, {"code": "WEAK_PASSWORD", "message": "Mật khẩu mới phải khác mật khẩu cũ."})
        try:
            ended = await set_password(s, user, body.new, now=now, keep_session=sess.session_id)
        except AccountError as e:
            raise HTTPException(422, {"code": e.code, "message": e.message}) from None
        await audit(sess, s, "auth", "password.changed", "Đổi mật khẩu", obj=("user", str(user.id), user.display_name), metadata={"other_sessions_ended": ended})
        fresh = await sessions.reissue(s, user.id, sess.session_id, sess.auth_time, now)  # the version was raised: this sign-in, and only it, is given the new one
    auth.set_cookie(response, request, fresh, sess.auth_time)
    return {"status": "ok", "other_sessions_ended": ended}


@router.get("/session/sessions")
async def my_sessions(sess: Session = need(Perm.ACCOUNT_SELF)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        rows = await sessions.active_for(s, sess.user_id, datetime.now(UTC))
    return {"items": [{"id": str(r.id), "current": r.id == sess.session_id, "created_at": wire(r.created_at), "last_seen_at": wire(r.last_seen_at),
                       "ip": r.ip, "user_agent": r.user_agent} for r in rows]}


@router.post("/session/sessions/{session_id}/revoke")
async def revoke_one(session_id: UUID, sess: Session = need(Perm.ACCOUNT_SELF)) -> dict[str, str]:
    async with tenant_session(sess.caller.tenant_id) as s:
        row = await s.get(m.AuthSession, session_id)
        if row is None or row.user_id != sess.user_id:  # only your own
            raise HTTPException(404, "session not found")
        await sessions.revoke(s, session_id, "revoked_by_owner_of_session", datetime.now(UTC))
        await audit(sess, s, "auth", "session.revoked", "Đăng xuất một thiết bị", obj=("session", str(session_id), None))
    return {"status": "ok"}


@router.post("/session/logout-all")
async def logout_all(response: Response, sess: Session = need(Perm.ACCOUNT_SELF)) -> dict[str, int]:
    async with tenant_session(sess.caller.tenant_id) as s:
        n = await sessions.revoke_user(s, sess.user_id, "logout_all", datetime.now(UTC))
        await audit(sess, s, "auth", "logout.all", "Đăng xuất khỏi mọi thiết bị", obj=("user", str(sess.user_id), sess.name), metadata={"sessions": n})
    auth.clear_cookies(response)
    return {"ended": n}


class Switch(BaseModel):
    paused: bool


@router.post("/kill-switch")
async def kill_switch(body: Switch, sess: Session = need(Perm.AI_PAUSE)) -> dict[str, Any]:
    """Owner only. Pauses (or resumes) every sandbox of the business; the audit row names who did it."""
    async with tenant_session(sess.caller.tenant_id) as s:
        changed = await set_paused(s, sess.caller.tenant_id, body.paused, by=sess.actor, role=sess.caller.role, now=datetime.now(UTC))
    return {"changed": changed, **(await _state(sess))}
