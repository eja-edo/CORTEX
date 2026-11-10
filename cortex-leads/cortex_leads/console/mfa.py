"""Two-step sign-in, turned on and off by the person themselves (Tài khoản → Bảo mật). Never required.

Setting it up is two calls so a mistyped QR scan cannot lock anyone out: `setup` (needs the password) makes a secret and keeps it aside,
`enable` (needs a code made from that secret) switches it on and hands out the ten recovery codes, once. Turning it off or making new recovery
codes needs the password and a current code, so a session left open on someone's desk cannot quietly remove it."""
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from cortex_leads.audit import context as audit_context
from cortex_leads.audit.service import record_new
from cortex_leads.auth import mfa, passwords, throttle
from cortex_leads.auth.perms import Perm
from cortex_leads.config import get_settings
from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import audit
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session

router = APIRouter(prefix="/account/mfa")

BAD_PASSWORD = HTTPException(403, {"code": "BAD_CURRENT_PASSWORD", "message": "Mật khẩu hiện tại không đúng."})
BAD_CODE = HTTPException(422, {"code": "BAD_MFA_CODE", "message": "Mã không đúng hoặc đã được dùng."})


class Password(BaseModel):
    password: str = Field(min_length=1, max_length=passwords.MAX_LEN)


class Code(BaseModel):
    code: str = Field(min_length=6, max_length=24)


class PasswordAndCode(Password, Code):
    pass


async def check_password(sess: Session, user: m.AppUser, password: str, now: datetime) -> None:
    """Wrong passwords here count toward the same lock as at sign-in: a session left open is not a way to guess the password."""
    async with system_session() as s:
        wait = await throttle.locked_for(s, [throttle.account_key(sess.email)], now)
    if wait:
        raise HTTPException(429, {"code": "LOGIN_LOCKED", "message": "Quá nhiều lần thử. Hãy đợi rồi thử lại.", "retry_after_s": wait})
    if not passwords.verify_password(password, user.password_hash):
        async with system_session() as s:
            await throttle.register_failure(s, sess.email, audit_context.current().ip, now)
        await record_new(sess.caller.tenant_id, actor=sess.actor, role=sess.caller.role, category="auth", action="mfa.password_failed",
                         result="failed", summary="Thao tác xác thực 2 lớp bị từ chối: sai mật khẩu")
        raise BAD_PASSWORD


async def spend_code(sess: Session, u: m.AppUser, code: str, now: datetime) -> str:
    """A current code, spent; wrong ones count toward the same lock as at sign-in."""
    key = mfa.throttle_key(u.id)
    async with system_session() as s:
        wait = await throttle.locked_for(s, [key], now)
    if wait:
        raise HTTPException(429, {"code": "LOGIN_LOCKED", "message": "Quá nhiều lần thử. Hãy đợi rồi thử lại.", "retry_after_s": wait})
    method = mfa.use_code(u, code, now)
    if method is None:
        cfg = get_settings()
        async with system_session() as s:
            await throttle.fail(s, key, now, limit=cfg.LOGIN_MAX_FAILURES, window=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES * 2),
                                lock=timedelta(minutes=cfg.LOGIN_LOCK_MINUTES))
        raise BAD_CODE
    return method


async def _me(s: Any, sess: Session) -> m.AppUser:
    return (await s.execute(select(m.AppUser).where(m.AppUser.id == sess.user_id).with_for_update())).scalar_one()


def _status(u: m.AppUser) -> dict[str, Any]:
    return {"enabled": u.mfa_enabled_at is not None, "enabled_at": wire(u.mfa_enabled_at) if u.mfa_enabled_at else None,
            "recovery_left": len(u.mfa_recovery or []) if u.mfa_enabled_at else 0}


@router.get("")
async def status(sess: Session = need(Perm.ACCOUNT_SELF)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        return _status(await s.get(m.AppUser, sess.user_id))


@router.post("/setup")
async def setup(body: Password, sess: Session = need(Perm.ACCOUNT_SELF)) -> dict[str, str]:
    """A new secret, kept aside until `enable` proves the app has it. Shown to this person only, on this answer only."""
    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await _me(s, sess)
        if u.mfa_enabled_at is not None:
            raise HTTPException(409, {"code": "MFA_ON", "message": "Xác thực 2 lớp đang bật rồi."})
        await check_password(sess, u, body.password, now)
        secret = mfa.new_secret()
        u.mfa_pending_enc = mfa.seal(secret)
        email = u.email
    return {"secret": secret, "uri": mfa.otpauth_uri(secret, email)}


@router.post("/enable")
async def enable(body: Code, sess: Session = need(Perm.ACCOUNT_SELF)) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await _me(s, sess)
        pending = mfa.unseal(u.mfa_pending_enc)
        if u.mfa_enabled_at is not None or pending is None:
            raise HTTPException(409, {"code": "MFA_NOT_PENDING", "message": "Hãy bắt đầu lại bước quét mã QR."})
        step = mfa.match(pending, body.code, now, None)
        if step is None:
            raise BAD_CODE
        codes, hashes = mfa.new_recovery_codes()
        u.mfa_secret_enc, u.mfa_pending_enc, u.mfa_enabled_at, u.mfa_last_step, u.mfa_recovery = u.mfa_pending_enc, None, now, step, hashes
        await audit(sess, s, "auth", "mfa.enabled", "Bật xác thực 2 lớp", obj=("user", str(u.id), u.display_name))
        out = _status(u)
    return {**out, "recovery_codes": codes}


@router.post("/disable")
async def disable(body: PasswordAndCode, sess: Session = need(Perm.ACCOUNT_SELF)) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await _me(s, sess)
        if u.mfa_enabled_at is None:
            return _status(u)
        await check_password(sess, u, body.password, now)
        await spend_code(sess, u, body.code, now)
        mfa.turn_off(u)
        await audit(sess, s, "auth", "mfa.disabled", "Tắt xác thực 2 lớp", obj=("user", str(u.id), u.display_name))
        return _status(u)


@router.post("/recovery-codes")
async def new_codes(body: PasswordAndCode, sess: Session = need(Perm.ACCOUNT_SELF)) -> dict[str, Any]:
    """Ten new codes; the old ones stop working. For someone who used most of them, or fears they were seen."""
    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await _me(s, sess)
        if u.mfa_enabled_at is None:
            raise HTTPException(409, {"code": "MFA_OFF", "message": "Xác thực 2 lớp đang tắt."})
        await check_password(sess, u, body.password, now)
        await spend_code(sess, u, body.code, now)
        codes, u.mfa_recovery = mfa.new_recovery_codes()
        await audit(sess, s, "auth", "mfa.recovery_renewed", "Tạo lại mã dự phòng xác thực 2 lớp", obj=("user", str(u.id), u.display_name))
        out = _status(u)
    return {**out, "recovery_codes": codes}
