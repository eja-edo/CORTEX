"""The emailed link that lets a person choose their own password: for a new account (an invitation) or a forgotten one (a reset).
One token table (`password_reset`), one way to use it (`POST /auth/reset`). The token is random, only its hash is stored, it works once,
it expires, and it travels in the link's fragment. The mail holds the link, never a password: no password exists for anyone else to read."""
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.auth.passwords import MIN_LEN
from cortex_leads.config import get_settings
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.notify.mailer import MailError, get_mailer

log = logging.getLogger(__name__)


def enabled() -> bool:
    """A link needs somewhere to send the mail from and a public address to put in it."""
    return get_mailer() is not None and bool(get_settings().PUBLIC_BASE_URL)


def token_hash(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


async def issue(s: AsyncSession, user: m.AppUser, *, minutes: int, ip: str | None = None) -> str:
    """A fresh link for `user`; any link sent earlier stops working. Returns the token (the only time it exists in clear)."""
    now = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    await s.execute(update(m.PasswordReset).where(m.PasswordReset.user_id == user.id, m.PasswordReset.used_at.is_(None)).values(used_at=now))
    s.add(m.PasswordReset(id=uuid7(), tenant_id=user.tenant_id, user_id=user.id, token_hash=token_hash(token),
                          expires_at=now + timedelta(minutes=minutes), ip=ip))
    await s.flush()
    return token


def url(token: str, *, invite: bool) -> str:
    base = (get_settings().PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}/app/reset#token={token}" + ("&kind=invite" if invite else "")


def invite_minutes() -> int:
    return get_settings().INVITE_LINK_HOURS * 60


def invite_mail(name: str, link: str, inviter: str, tenant: str) -> tuple[str, str]:
    hours = get_settings().INVITE_LINK_HOURS
    body = (f"Xin chào {name},\n\n{inviter} vừa tạo cho bạn một tài khoản Cortex tại {tenant}. "
            f"Mở liên kết dưới đây trong {hours} giờ để tự chọn mật khẩu (ít nhất {MIN_LEN} ký tự), sau đó đăng nhập:\n\n{link}\n\n"
            "Liên kết chỉ dùng được một lần và chỉ mở cho địa chỉ email này. Nếu bạn không mong đợi thư này, hãy bỏ qua: tài khoản sẽ không dùng được khi chưa ai đặt mật khẩu.\n")
    return "Lời mời tham gia Cortex", body


def email_changed_mail(name: str, new_email: str, by: str) -> tuple[str, str]:
    """To the address the account used to have: whoever reads it should know their sign-in name was moved."""
    body = (f"Xin chào {name},\n\nEmail đăng nhập của tài khoản Cortex của bạn vừa được {by} đổi sang {new_email}. "
            "Từ giờ thư của hệ thống gửi tới địa chỉ mới, và mọi thiết bị của bạn đã bị đăng xuất.\n\n"
            "Nếu bạn không biết về việc này, hãy liên hệ chủ trung tâm ngay.\n")
    return "Email đăng nhập Cortex của bạn đã được đổi", body


def reset_mail(name: str, link: str, minutes: int) -> tuple[str, str]:
    body = (f"Xin chào {name},\n\nCó người (hy vọng là bạn) vừa xin đặt lại mật khẩu của tài khoản Cortex này. "
            f"Mở liên kết dưới đây trong {minutes} phút để chọn mật khẩu mới:\n\n{link}\n\n"
            "Liên kết chỉ dùng được một lần. Nếu không phải bạn xin, hãy bỏ qua thư này: mật khẩu hiện tại vẫn dùng được và không ai đổi được nó.\n")
    return "Đặt lại mật khẩu Cortex", body


async def deliver(to: str, subject: str, body: str) -> bool:
    """True when the mail was handed over. A failure is logged without the address and reported to the caller, who says so."""
    mailer = get_mailer()
    if mailer is None:
        return False
    try:
        await mailer.send(to, subject, body)
    except MailError as e:
        log.warning("mail was not sent (%s)", e)
        return False
    return True
