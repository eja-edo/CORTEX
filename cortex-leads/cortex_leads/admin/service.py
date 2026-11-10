"""What the operator does to businesses (WP47): one set of functions for the admin page and the command line.

Everything inside a business still goes through `tenant_session` (RLS, DESIGN A1): the admin page names the business in its path, and
that name is believed only after the admin's own sign-in was checked (A3). What is read is metadata: counts, the business's accounts,
the state of its sandboxes. No conversation, customer, phone number or price list is read here. Every change leaves a line in the
activity log OF THE BUSINESS it touched, so its owner sees who did what to their accounts."""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from cortex_leads.audit.service import record
from cortex_leads.auth import links, mfa, passwords, sessions
from cortex_leads.auth.roles import Role
from cortex_leads.auth.users import AccountError, create_user, is_invited, normalise_email
from cortex_leads.config import get_settings
from cortex_leads.console.killswitch import set_paused
from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.sandbox.bringup import create_sandbox, ensure_sandboxes
from cortex_leads.sandbox.kinds import KINDS

ROLE = "platform"


class AdminError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


NOT_FOUND = AdminError(404, "NOT_FOUND", "Không tìm thấy.")
MAIL_OFF = AdminError(409, "MAIL_OFF", "Máy chủ chưa cấu hình gửi thư (SMTP và địa chỉ công khai). Dùng `cli create-user --password` cho trường hợp này.")


def check_timezone(tz: str) -> str:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise AdminError(422, "BAD_TIMEZONE", "Múi giờ không hợp lệ (ví dụ: Asia/Ho_Chi_Minh).") from None
    return tz


def check_name(name: str) -> str:
    name = " ".join(name.split())
    if not 2 <= len(name) <= 120:
        raise AdminError(422, "BAD_NAME", "Tên doanh nghiệp cần 2–120 ký tự.")
    return name


async def _tenant(tenant_id: UUID) -> m.Tenant:
    async with system_session() as s:
        t = await s.get(m.Tenant, tenant_id)
    if t is None:
        raise NOT_FOUND
    return t


# --- a new business ------------------------------------------------------------------------------------------------------------------------
async def create_tenant(name: str, timezone: str, *, by: str, role: str = ROLE) -> tuple[UUID, UUID]:
    """The business and every sandbox it comes with (a business is useless without them, and a sandbox without its skills does nothing).
    Returns (business, its customer-care sandbox)."""
    name, timezone = check_name(name), check_timezone(timezone)
    tid, sid = uuid7(), uuid7()
    async with system_session() as s:
        s.add(m.Tenant(id=tid, name=name, timezone=timezone))
    async with tenant_session(tid) as s:
        await create_sandbox(s, tid, KINDS["customer_care"], name="customer_care", sandbox_id=sid)
        added = await ensure_sandboxes(s, tid)
        await record(s, tid, actor=by, role=role, category="config", action="tenant.created", summary=f"Tạo doanh nghiệp {name}",
                     obj=("tenant", str(tid), name), metadata={"timezone": timezone, "sandboxes": 1 + len(added)})
    return tid, sid


@dataclass
class Invite:
    user_id: UUID
    email: str
    staff_ref: str
    mail_sent: bool
    kind: str  # "invite" (never opened) or "reset"


async def _mail_link(tenant: m.Tenant, user_id: UUID, *, by: str, new: bool) -> Invite:
    """Issues a link for this person and mails it, after the commit (the link must exist before anyone can open it)."""
    async with tenant_session(tenant.id) as s:
        u = await s.get(m.AppUser, user_id)
        if u is None:
            raise NOT_FOUND
        if u.status != "active":
            raise AdminError(409, "DISABLED", "Tài khoản đang bị khoá; chủ doanh nghiệp phải mở lại trước.")
        invite = is_invited(u)
        minutes = links.invite_minutes() if invite else get_settings().RESET_LINK_MINUTES
        token = await links.issue(s, u, minutes=minutes)
        if not new:
            await record(s, tenant.id, actor=by, role=ROLE, category="auth", action="password.link_sent",
                         summary=f"Quản trị nền tảng gửi liên kết {'kích hoạt' if invite else 'đặt lại mật khẩu'} tới {u.email}",
                         obj=("user", str(u.id), u.display_name), metadata={"kind": "invite" if invite else "reset"})
        email, name, ref = u.email, u.display_name, u.staff_ref
    link = links.url(token, invite=invite)
    subject, body = links.invite_mail(name, link, "Quản trị viên Cortex", tenant.name) if invite else links.reset_mail(name, link, minutes)
    sent = await links.deliver(email, subject, body)
    return Invite(user_id, email, ref, sent, "invite" if invite else "reset")


async def invite_owner(tenant_id: UUID, email: str, name: str, *, by: str) -> Invite:
    """An owner for a business: the first one, or another one when the only owner left. Made with no usable password; the person
    chooses theirs from the mailed link (DESIGN §5.15). No mail, no account: there is no fallback to a password someone else reads."""
    if not links.enabled():
        raise MAIL_OFF
    tenant = await _tenant(tenant_id)
    async with tenant_session(tenant_id) as s:
        try:
            user = await create_user(s, tenant_id, email=email, name=name, role=Role.OWNER, created_by=by)
        except AccountError as e:
            raise AdminError(409 if e.code == "EMAIL_TAKEN" else 422, e.code, e.message) from None
        await record(s, tenant_id, actor=by, role=ROLE, category="config", action="user.created", summary=f"Quản trị nền tảng mời {user.email} làm chủ",
                     obj=("user", str(user.id), user.display_name), metadata={"role": user.role, "email": user.email})
        user_id = user.id
    return await _mail_link(tenant, user_id, by=by, new=True)


# --- looking ------------------------------------------------------------------------------------------------------------------------------
def _ai_state(sandboxes: list[m.Sandbox]) -> str:
    if not sandboxes:
        return "none"
    paused = sum(1 for x in sandboxes if x.status == "paused")
    return "paused" if paused == len(sandboxes) else "partial" if paused else "running"


async def _summary(t: m.Tenant, now: datetime) -> dict[str, Any]:
    async with tenant_session(t.id) as s:
        sbs = list((await s.execute(select(m.Sandbox))).scalars())
        users = (await s.execute(select(m.AppUser.role, m.AppUser.status, m.AppUser.password_hash, m.AppUser.last_login_at))).all()
        active_7d = (await s.execute(select(func.count()).select_from(m.Conversation)
                                     .where(m.Conversation.last_customer_at > now - timedelta(days=7)))).scalar_one()
    logins = [u.last_login_at for u in users if u.last_login_at]
    return {"id": str(t.id), "name": t.name, "timezone": t.timezone, "created_at": wire(t.created_at),
            "ai": _ai_state(sbs), "sandboxes": len(sbs), "sandboxes_paused": sum(1 for x in sbs if x.status == "paused"),
            "accounts": sum(1 for u in users if u.status == "active"),
            "owners": sum(1 for u in users if u.role == Role.OWNER and u.status == "active"),
            "owners_waiting": sum(1 for u in users if u.role == Role.OWNER and u.status == "active" and u.password_hash == passwords.UNUSABLE),
            "conversations_7d": active_7d, "last_login_at": wire(max(logins)) if logins else None}


async def list_tenants(now: datetime | None = None) -> list[dict[str, Any]]:
    """One small transaction per business: RLS stays the filter, and there are tens of businesses, not thousands."""
    now = now or datetime.now(UTC)
    async with system_session() as s:
        tenants = list((await s.execute(select(m.Tenant).order_by(m.Tenant.created_at.desc()))).scalars())
    return [await _summary(t, now) for t in tenants]


async def tenant_detail(tenant_id: UUID, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    t = await _tenant(tenant_id)
    async with tenant_session(tenant_id) as s:
        sbs = list((await s.execute(select(m.Sandbox).order_by(m.Sandbox.created_at))).scalars())
        users = list((await s.execute(select(m.AppUser).order_by(m.AppUser.created_at))).scalars())
        live = dict((await s.execute(select(m.AuthSession.user_id, func.count()).where(
            m.AuthSession.revoked_at.is_(None), m.AuthSession.expires_at > now, m.AuthSession.refresh_expires_at > now)
            .group_by(m.AuthSession.user_id))).all())
    missing = [k.purpose for k in KINDS.values() if k.profile and k.available and k.purpose not in {x.purpose for x in sbs}]
    return {**await _summary(t, now),
            "sandboxes_missing": missing,
            "sandbox_list": [{"id": str(x.id), "purpose": x.purpose, "label": KINDS[x.purpose].label if x.purpose in KINDS else x.purpose,
                              "title": x.title, "status": x.status, "send_mode": x.send_mode} for x in sbs],
            # who works there: enough to help them sign in, nothing of their personal profile (phone, birth date, ID number)
            "account_list": [{"id": str(u.id), "email": u.email, "name": u.display_name, "role": u.role, "status": u.status,
                              "invited": is_invited(u), "mfa": u.mfa_enabled_at is not None, "sessions": live.get(u.id, 0),
                              "last_login_at": wire(u.last_login_at), "created_at": wire(u.created_at)} for u in users]}


# --- changing ------------------------------------------------------------------------------------------------------------------------------
async def add_missing_sandboxes(tenant_id: UUID, *, by: str) -> list[str]:
    await _tenant(tenant_id)
    async with tenant_session(tenant_id) as s:
        added = await ensure_sandboxes(s, tenant_id)
        if added:
            await record(s, tenant_id, actor=by, role=ROLE, category="config", action="sandbox.created",
                         summary=f"Quản trị nền tảng bổ sung {len(added)} sandbox còn thiếu", metadata={"purposes": [x.purpose for x in added]})
        return [x.purpose for x in added]


async def pause(tenant_id: UUID, paused: bool, *, by: str, sandbox_id: UUID | None = None, now: datetime | None = None) -> int:
    await _tenant(tenant_id)
    async with tenant_session(tenant_id) as s:
        if sandbox_id is not None and await s.get(m.Sandbox, sandbox_id) is None:
            raise NOT_FOUND
        return await set_paused(s, tenant_id, paused, by=by, role=ROLE, now=now or datetime.now(UTC), sandbox_id=sandbox_id)


async def pause_all(paused: bool, *, by: str, now: datetime | None = None) -> dict[str, int]:
    """Every business at once, for an incident (a model saying something it must not, a leaked key). One business per transaction:
    a failure part way leaves the ones already done done, and the answer says how far it got."""
    now = now or datetime.now(UTC)
    async with system_session() as s:
        ids = list((await s.execute(select(m.Tenant.id))).scalars())
    changed = 0
    for tid in ids:
        async with tenant_session(tid) as s:
            changed += await set_paused(s, tid, paused, by=by, role=ROLE, now=now)
    return {"tenants": len(ids), "sandboxes_changed": changed}


async def _user(s: Any, user_id: UUID) -> m.AppUser:
    u = await s.get(m.AppUser, user_id)
    if u is None:
        raise NOT_FOUND
    return u


async def send_link(tenant_id: UUID, user_id: UUID, *, by: str) -> Invite:
    """The invitation again for someone who never opened it, a reset link otherwise. Their current password keeps working until they use it."""
    if not links.enabled():
        raise MAIL_OFF
    return await _mail_link(await _tenant(tenant_id), user_id, by=by, new=False)


async def reset_mfa(tenant_id: UUID, user_id: UUID, *, by: str, now: datetime | None = None) -> int:
    """For anyone who lost both phone and recovery codes, owners included (an owner cannot do it for another owner). Every device is
    signed out (one may be the lost phone) and the person is told by mail. Nothing secret is shown to the admin."""
    now = now or datetime.now(UTC)
    tenant = await _tenant(tenant_id)
    async with tenant_session(tenant_id) as s:
        u = await _user(s, user_id)
        if u.mfa_enabled_at is None:
            return 0
        mfa.turn_off(u)
        ended = await sessions.revoke_user(s, u.id, "mfa_reset_by_platform", now)
        await record(s, tenant_id, actor=by, role=ROLE, category="auth", action="mfa.reset", summary=f"Quản trị nền tảng tắt xác thực 2 lớp của {u.email}",
                     obj=("user", str(u.id), u.display_name), metadata={"sessions_ended": ended})
        to = u.email
    await links.deliver(to, "Xác thực 2 lớp của bạn đã được tắt",
                        f"Quản trị viên Cortex vừa tắt xác thực 2 lớp cho tài khoản của bạn tại {tenant.name}, theo yêu cầu hỗ trợ, và mọi thiết bị "
                        "của bạn đã bị đăng xuất.\n\nBạn đăng nhập lại bằng mật khẩu như thường, rồi nên bật lại ở Tài khoản → Xác thực 2 lớp.\n"
                        "Nếu bạn không nhờ việc này, hãy đổi mật khẩu ngay và báo cho chúng tôi.")
    return ended


@dataclass
class Edited:
    email: str
    name: str
    email_moved: bool
    sessions_ended: int
    mail_sent: bool | None  # the invitation again (to the corrected address) or the notice to the old one; None when nothing was mailed


async def edit_account(tenant_id: UUID, user_id: UUID, *, name: str | None, email: str | None, by: str, code_ok: bool,
                       now: datetime | None = None) -> Edited:
    """Name and sign-in email: the usual fix is a typo in the address of an owner who was just invited. Role, status and personal details
    stay the owner's to change in the console.

    Moving the email of an account that is already in use is how an admin session could take that account over (move it, then send a reset
    link to the new address), so it needs the admin's code (`code_ok`), signs the person out everywhere, voids links already sent, and tells
    the old address. For an invitation never opened, the invitation simply goes again to the corrected address."""
    now = now or datetime.now(UTC)
    tenant = await _tenant(tenant_id)
    if name is not None:
        name = check_name(name)
    new_email = None
    if email is not None:
        try:
            new_email = normalise_email(email)
        except AccountError as e:
            raise AdminError(422, e.code, e.message) from None
    ended, resend, notify = 0, False, None
    async with tenant_session(tenant_id) as s:
        u = await _user(s, user_id)
        if new_email == u.email:
            new_email = None
        invited, old_email, old_name = is_invited(u), u.email, u.display_name
        if new_email and not invited and not code_ok:
            raise AdminError(403, "CODE_REQUIRED", "Đổi email của tài khoản đang dùng cần mã 6 số trong ứng dụng xác thực của bạn.")
        if new_email and not links.enabled():
            raise MAIL_OFF  # the person could not be told, nor a corrected invitation sent
        changes = []
        if name and name != u.display_name:
            u.display_name = name
            changes.append({"field": "name", "before": old_name, "after": name})
        if new_email:
            u.email = new_email
            try:
                async with s.begin_nested():
                    await s.flush()
            except IntegrityError:
                raise AdminError(409, "EMAIL_TAKEN", "Email này đã có tài khoản.") from None
            await s.execute(update(m.PasswordReset).where(m.PasswordReset.user_id == u.id, m.PasswordReset.used_at.is_(None)).values(used_at=now))
            if invited:
                resend = u.status == "active"
            else:
                ended = await sessions.revoke_user(s, u.id, "email_changed_by_platform", now)
                notify = old_email
            changes.append({"field": "email", "before": old_email, "after": new_email})
        if changes:
            await record(s, tenant_id, actor=by, role=ROLE, category="config", action="user.updated", summary=f"Quản trị nền tảng sửa tài khoản {u.email}",
                         obj=("user", str(u.id), u.display_name), changes=changes, metadata={"email_moved": True} if new_email else None)
        out = Edited(u.email, u.display_name, bool(new_email), ended, None)
    if resend:
        out.mail_sent = (await _mail_link(tenant, user_id, by=by, new=True)).mail_sent
    elif notify:
        subject, text_ = links.email_changed_mail(out.name, out.email, "Quản trị viên Cortex")
        out.mail_sent = await links.deliver(notify, subject, text_)
    return out


async def end_sessions(tenant_id: UUID, user_id: UUID, *, by: str, now: datetime | None = None) -> int:
    await _tenant(tenant_id)
    async with tenant_session(tenant_id) as s:
        u = await _user(s, user_id)
        n = await sessions.revoke_user(s, u.id, "ended_by_platform", now or datetime.now(UTC))
        await record(s, tenant_id, actor=by, role=ROLE, category="auth", action="sessions.ended", summary=f"Quản trị nền tảng đăng xuất mọi thiết bị của {u.email}",
                     obj=("user", str(u.id), u.display_name), metadata={"sessions": n})
    return n
