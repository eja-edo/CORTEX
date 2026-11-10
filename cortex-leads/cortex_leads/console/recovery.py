"""Forgotten password, by email. Three public calls: is it switched on, ask for a link, use the link.

Asking never tells whether the address has an account: the answer is the same, it comes at the same speed (whatever depends on the
account runs after the answer has been sent), and the limits count every ask. The link carries a random token in its fragment (so it
reaches neither a server log nor a Referer header); only a hash of the token is stored; it works once, for `RESET_LINK_MINUTES`; and
the mail holds the link, never a password. Using it ends every sign-in of that person."""
import hashlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text, update

from cortex_leads.audit import context as audit_context
from cortex_leads.audit.service import record
from cortex_leads.auth import links, passwords, throttle
from cortex_leads.auth.links import enabled, token_hash
from cortex_leads.auth.users import AccountError, lookup_for_login, set_password
from cortex_leads.config import get_settings
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.notify.mailer import MailError, get_mailer

router = APIRouter(prefix="/auth")
log = logging.getLogger(__name__)
HOUR = timedelta(hours=1)
GENERIC = {"status": "ok"}  # the whole answer to "send me a link", whoever asks


def _key(prefix: str, value: str | None) -> str:
    return prefix + hashlib.sha256((value or "unknown").strip().lower().encode()).hexdigest()[:32]


@router.get("/recovery")
async def recovery_status() -> dict[str, bool]:
    return {"enabled": enabled()}


class Forgot(BaseModel):
    email: str = Field(min_length=3, max_length=254)


async def _send_link(email: str, ip: str | None) -> None:
    """Runs after the answer. Nothing here can change what the person asking saw."""
    try:
        user = await lookup_for_login(email)
        mailer = get_mailer()
        if user is None or user.status != "active" or mailer is None:
            return
        cfg = get_settings()
        async with tenant_session(user.tenant_id) as s:
            token = await links.issue(s, user, minutes=cfg.RESET_LINK_MINUTES, ip=ip)
            await record(s, user.tenant_id, actor="system:recovery", role="system", category="auth", action="password.reset_requested",
                         summary="Có yêu cầu đặt lại mật khẩu qua email", obj=("user", str(user.id), user.display_name))
        subject, body = links.reset_mail(user.display_name, links.url(token, invite=False), cfg.RESET_LINK_MINUTES)
        await mailer.send(user.email, subject, body)
    except MailError as e:
        log.warning("password reset mail was not sent (%s)", e)  # never the address
    except Exception:
        log.exception("password reset failed")


@router.post("/forgot")
async def forgot(body: Forgot, tasks: BackgroundTasks) -> dict[str, str]:
    if not enabled():
        raise HTTPException(503, {"code": "RECOVERY_OFF", "message": "Chưa bật gửi thư. Hãy nhờ chủ trung tâm đặt lại mật khẩu cho bạn."})
    cfg = get_settings()
    now = datetime.now(UTC)
    ip = audit_context.current().ip
    email = body.email.strip().lower()
    ip_key, mail_key = _key("resetip:", ip), _key("resetmail:", email)
    async with system_session() as s:
        if await throttle.locked_for(s, [ip_key], now):
            raise HTTPException(429, {"code": "RESET_LIMITED", "message": "Bạn đã xin quá nhiều lần. Hãy thử lại sau ít phút."})
        if await throttle.fail(s, ip_key, now, limit=cfg.RESET_MAX_PER_IP_HOUR + 1, window=HOUR, lock=HOUR):
            raise HTTPException(429, {"code": "RESET_LIMITED", "message": "Bạn đã xin quá nhiều lần. Hãy thử lại sau ít phút."})
        # One address gets a few mails an hour. Past that it is silent, so a stranger cannot tell the limit from "no such account".
        mail_ok = not await throttle.locked_for(s, [mail_key], now) and not await throttle.fail(
            s, mail_key, now, limit=cfg.RESET_MAX_PER_EMAIL_HOUR + 1, window=HOUR, lock=HOUR)
    if mail_ok:
        tasks.add_task(_send_link, email, ip)
    return GENERIC


class Reset(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=passwords.MAX_LEN)


BAD_LINK = HTTPException(400, {"code": "BAD_RESET_TOKEN", "message": "Liên kết không dùng được hoặc đã hết hạn. Hãy xin liên kết mới."})  # one answer for every cause


@router.post("/reset")
async def reset(body: Reset) -> dict[str, str]:
    now = datetime.now(UTC)
    cfg = get_settings()
    ip_key = _key("resettry:", audit_context.current().ip)
    async with system_session() as s:
        if await throttle.locked_for(s, [ip_key], now) or await throttle.fail(s, ip_key, now, limit=cfg.RESET_MAX_PER_IP_HOUR * 3 + 1, window=HOUR, lock=HOUR):
            raise HTTPException(429, {"code": "RESET_LIMITED", "message": "Quá nhiều lần thử. Hãy đợi rồi thử lại."})
        digest = token_hash(body.token)
        await s.execute(text("select set_config('app.reset_token', :h, true)"), {"h": digest})  # exactly the row of this token is visible
        found = (await s.execute(m.PasswordReset.__table__.select().where(m.PasswordReset.token_hash == digest))).first()
    if found is None or found.used_at is not None or found.expires_at <= now:
        raise BAD_LINK
    async with tenant_session(found.tenant_id) as s:
        claimed = (await s.execute(update(m.PasswordReset).where(m.PasswordReset.id == found.id, m.PasswordReset.used_at.is_(None),
                                                                 m.PasswordReset.expires_at > now).values(used_at=now).returning(m.PasswordReset.id))).first()
        user = await s.get(m.AppUser, found.user_id)
        if claimed is None or user is None or user.status != "active":
            raise BAD_LINK
        try:
            ended = await set_password(s, user, body.password, now=now)
        except AccountError as e:  # a weak password: the link is not spent (this transaction rolls back), so they can try again
            raise HTTPException(422, {"code": e.code, "message": e.message}) from None
        await s.execute(update(m.PasswordReset).where(m.PasswordReset.user_id == user.id, m.PasswordReset.used_at.is_(None)).values(used_at=now))
        await record(s, user.tenant_id, actor=f"staff:{user.staff_ref}", role=user.role, category="auth", action="password.reset_by_email",
                     summary="Đặt lại mật khẩu bằng liên kết gửi qua email", obj=("user", str(user.id), user.display_name), metadata={"sessions_ended": ended})
        email = user.email
    async with system_session() as s:
        await throttle.clear_account(s, email)  # someone locked out by guesses can come back in with the new password
    return GENERIC
