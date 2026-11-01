"""Sign-in, who am I, my password, my sessions, and the kill switch (sidebar state)."""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from cortex_leads.audit import context as audit_context
from cortex_leads.audit.service import record_new
from cortex_leads.auth import passwords, sessions, throttle
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
            "needs_person": need_}


async def _me(sess: Session) -> dict[str, Any]:
    return {"role": sess.caller.role, "staff_ref": sess.caller.staff_ref, "tenant": sess.tenant_name, "timezone": str(sess.tz), "csrf": sess.csrf,
            "email": sess.email, "name": sess.name, "must_change_password": sess.must_change_password, "permissions": sess.permissions,
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
    async with tenant_session(user.tenant_id) as s:
        row = await s.get(m.AppUser, user.id)
        cookie = await sessions.create(s, row, ip=info.ip, user_agent=info.user_agent, now=now)
        row.last_login_at = now
        tenant = await s.get(m.Tenant, row.tenant_id)
    async with system_session() as s:
        await throttle.clear_account(s, email)
    cfg = get_settings()
    response.set_cookie(auth.COOKIE, cookie, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=cfg.SESSION_ABSOLUTE_HOURS * 3600, path="/")
    sid = UUID(cookie.split(".")[0])
    audit_context.current().session_id = f"s:{str(sid)[:8]}"
    await record_new(user.tenant_id, actor=f"staff:{user.staff_ref}", role=user.role, category="auth", action="login.ok", summary="Đăng nhập",
                     obj=("user", str(user.id), user.display_name), metadata={"email": email})
    from zoneinfo import ZoneInfo

    from cortex_leads.review.auth import Caller

    sess = auth.Session(Caller(user.tenant_id, user.role, user.staff_ref), tenant.name, ZoneInfo(tenant.timezone), auth.csrf_for(cookie), user.id, sid,
                        user.email, user.display_name, user.must_change_password)
    return await _me(sess)


@router.get("/session")
async def me(sess: Session = ANY) -> dict[str, Any]:
    return await _me(sess)


@router.post("/session/logout")
async def logout(response: Response, sess: Session = ANY) -> dict[str, str]:
    async with tenant_session(sess.caller.tenant_id) as s:
        await sessions.revoke(s, sess.session_id, "logout", datetime.now(UTC))
    response.delete_cookie(auth.COOKIE, path="/")
    await record_new(sess.caller.tenant_id, actor=sess.actor, role=sess.caller.role, category="auth", action="logout", summary="Đăng xuất")
    return {"status": "ok"}


class NewPassword(BaseModel):
    current: str = Field(min_length=1, max_length=passwords.MAX_LEN)
    new: str = Field(min_length=1, max_length=passwords.MAX_LEN)


@router.post("/session/password")
async def change_password(body: NewPassword, sess: Session = need("account.self")) -> dict[str, Any]:
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
            ended = await set_password(s, user, body.new, must_change=False, now=now, keep_session=sess.session_id)
        except AccountError as e:
            raise HTTPException(422, {"code": e.code, "message": e.message}) from None
        await audit(sess, s, "auth", "password.changed", "Đổi mật khẩu", obj=("user", str(user.id), user.display_name), metadata={"other_sessions_ended": ended})
    return {"status": "ok", "other_sessions_ended": ended}


@router.get("/session/sessions")
async def my_sessions(sess: Session = need("account.self")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        rows = await sessions.active_for(s, sess.user_id, datetime.now(UTC))
    return {"items": [{"id": str(r.id), "current": r.id == sess.session_id, "created_at": wire(r.created_at), "last_seen_at": wire(r.last_seen_at),
                       "ip": r.ip, "user_agent": r.user_agent} for r in rows]}


@router.post("/session/sessions/{session_id}/revoke")
async def revoke_one(session_id: UUID, sess: Session = need("account.self")) -> dict[str, str]:
    async with tenant_session(sess.caller.tenant_id) as s:
        row = await s.get(m.AuthSession, session_id)
        if row is None or row.user_id != sess.user_id:  # only your own
            raise HTTPException(404, "session not found")
        await sessions.revoke(s, session_id, "revoked_by_owner_of_session", datetime.now(UTC))
        await audit(sess, s, "auth", "session.revoked", "Đăng xuất một thiết bị", obj=("session", str(session_id), None))
    return {"status": "ok"}


@router.post("/session/logout-all")
async def logout_all(response: Response, sess: Session = need("account.self")) -> dict[str, int]:
    async with tenant_session(sess.caller.tenant_id) as s:
        n = await sessions.revoke_user(s, sess.user_id, "logout_all", datetime.now(UTC))
        await audit(sess, s, "auth", "logout.all", "Đăng xuất khỏi mọi thiết bị", obj=("user", str(sess.user_id), sess.name), metadata={"sessions": n})
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ended": n}


class Switch(BaseModel):
    paused: bool


@router.post("/kill-switch")
async def kill_switch(body: Switch, sess: Session = need("ai.pause")) -> dict[str, Any]:
    """Owner only. Pauses (or resumes) every sandbox of the business; the audit row names who did it."""
    async with tenant_session(sess.caller.tenant_id) as s:
        changed = await set_paused(s, sess.caller.tenant_id, body.paused, by=sess.actor, role=sess.caller.role, now=datetime.now(UTC))
    return {"changed": changed, **(await _state(sess))}
