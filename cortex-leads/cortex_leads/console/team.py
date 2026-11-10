"""Nhân viên & quyền (WP30): the owner makes accounts, changes roles, disables people and sends password links. no one is ever handed a password: a new account is *invited* and the person chooses their own through a link sent to their email
(auth/links.py). Nothing here can read or set a password, and nobody can lock the business out of its own owner. A teacher is given their classes here (WP46)."""
import re
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from cortex_leads.audit.service import diff
from cortex_leads.auth import links, passwords, sessions
from cortex_leads.auth.perms import Perm
from cortex_leads.auth.roles import Role
from cortex_leads.auth.users import (
    AccountError,
    change_role_or_status,
    create_user,
    is_invited,
    normalise_email,
)
from cortex_leads.config import get_settings
from cortex_leads.console import auth
from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import audit
from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import wire, wire_date
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

router = APIRouter()
PHONE = re.compile(r"^\+?[0-9][0-9 .()\-]{6,18}[0-9]$")
NATIONAL_ID = re.compile(r"^(\d{9}|\d{12})$")  # the old 9-digit ID card or the 12-digit citizen card


def _fernet() -> Fernet:
    return Fernet(get_settings().CONNECTOR_SECRET_KEY)


def _read_id(enc: str | None) -> str | None:
    """The ID number, for the owner's account screen only. A value that cannot be decrypted (the key changed) reads as empty."""
    if not enc:
        return None
    try:
        return _fernet().decrypt(enc.encode()).decode()
    except InvalidToken:
        return None
ROLE_NAMES = {Role.OWNER: "chủ", Role.STAFF: "nhân viên", Role.TEACHER: "giáo viên"}


def _refuse(e: AccountError) -> HTTPException:
    return HTTPException(409 if e.code in ("LAST_OWNER", "EMAIL_TAKEN") else 422, {"code": e.code, "message": e.message})


def _item(u: m.AppUser, active_sessions: int, me: UUID, classes: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"id": str(u.id), "email": u.email, "name": u.display_name, "role": u.role, "staff_ref": u.staff_ref, "status": u.status,
            "invited": is_invited(u), "last_login_at": wire(u.last_login_at) if u.last_login_at else None,
            "created_at": wire(u.created_at), "sessions": active_sessions, "you": u.id == me, "classes": classes or [],
            "phone": u.phone, "birth_date": wire_date(u.birth_date), "national_id": _read_id(u.national_id_enc), "mfa": u.mfa_enabled_at is not None}


async def _classes_of(s: Any, user_id: UUID | None = None) -> dict[UUID, list[dict[str, str]]]:
    """Which classes each teacher is in charge of, by name."""
    q = select(m.ClassTeacher.user_id, m.Class.id, m.Class.name).join(m.Class, m.Class.id == m.ClassTeacher.class_id).order_by(m.Class.name)
    out: dict[UUID, list[dict[str, str]]] = {}
    for uid, cid, name in (await s.execute(q if user_id is None else q.where(m.ClassTeacher.user_id == user_id))).all():
        out.setdefault(uid, []).append({"id": str(cid), "name": name})
    return out


@router.get("/team")
async def list_team(sess: Session = need(Perm.TEAM_MANAGE)) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        users = (await s.execute(select(m.AppUser).order_by(m.AppUser.role.asc(), m.AppUser.created_at))).scalars().all()
        counts = dict((await s.execute(select(m.AuthSession.user_id, func.count()).where(
            m.AuthSession.revoked_at.is_(None), m.AuthSession.expires_at > now).group_by(m.AuthSession.user_id))).all())
        classes = await _classes_of(s)
    return {"items": [_item(u, counts.get(u.id, 0), sess.user_id, classes.get(u.id)) for u in users], "min_password": passwords.MIN_LEN}


class NewUser(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=2, max_length=80)
    role: Role = Role.STAFF


MAIL_OFF = {"code": "MAIL_OFF", "message": "Máy chủ chưa cấu hình gửi thư (SMTP và địa chỉ công khai) nên chưa mời người mới được."}


async def _send_invite(sess: Session, user_id: UUID, *, new: bool) -> dict[str, Any]:
    """Issues a link for this person and mails it. Invited and not yet opened -> an invitation; otherwise a password reset link."""
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await s.get(m.AppUser, user_id)
        if u is None:
            raise HTTPException(404, "user not found")
        if u.status != "active":
            raise HTTPException(409, {"code": "DISABLED", "message": "Tài khoản đang bị khoá; hãy mở lại trước khi gửi liên kết."})
        invite = is_invited(u)
        cfg_minutes = links.invite_minutes() if invite else get_settings().RESET_LINK_MINUTES
        token = await links.issue(s, u, minutes=cfg_minutes)
        email, name = u.email, u.display_name
        if not new:  # the creation already has its own line in the log
            await audit(sess, s, "auth", "password.link_sent", f"Gửi liên kết {'kích hoạt' if invite else 'đặt lại mật khẩu'} tới {email}",
                        obj=("user", str(u.id), name), metadata={"kind": "invite" if invite else "reset"})
        link = links.url(token, invite=invite)
        subject, body = links.invite_mail(name, link, sess.name, sess.tenant_name) if invite else links.reset_mail(name, link, cfg_minutes)
    sent = await links.deliver(email, subject, body)  # after the commit: the link must exist before anyone can open it
    return {"id": str(user_id), "email": email, "mail_sent": sent, "kind": "invite" if invite else "reset"}


@router.post("/team", status_code=201)
async def add_member(body: NewUser, sess: Session = need(Perm.TEAM_MANAGE)) -> dict[str, Any]:
    """Makes the account without a password and mails the person a link to choose one. With no way to send mail nothing is made."""
    if not links.enabled():
        raise HTTPException(409, MAIL_OFF)
    async with tenant_session(sess.caller.tenant_id) as s:
        try:
            user = await create_user(s, sess.caller.tenant_id, email=body.email, name=body.name, role=body.role, created_by=sess.actor)
        except AccountError as e:
            raise _refuse(e) from None
        await audit(sess, s, "config", "user.created", f"Mời {user.email} ({ROLE_NAMES[user.role]})",
                    obj=("user", str(user.id), user.display_name), metadata={"role": user.role, "email": user.email})
        user_id, staff_ref = user.id, user.staff_ref
    return {**await _send_invite(sess, user_id, new=True), "staff_ref": staff_ref}


class Patch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None
    phone: str | None = Field(default=None, max_length=30)  # for these three, a field that is sent empty clears the value
    birth_date: date | None = None
    national_id: str | None = Field(default=None, max_length=20)


def _personal(body: Patch, u: m.AppUser) -> list[str]:
    """Applies phone / date of birth / ID number from the request and returns the names of the fields that changed. Values stay out of the log."""
    changed = []
    sent = body.model_fields_set
    if "phone" in sent:
        phone = (body.phone or "").strip() or None
        if phone and not PHONE.match(phone):
            raise HTTPException(422, {"code": "BAD_PHONE", "message": "Số điện thoại không hợp lệ."})
        if phone != u.phone:
            u.phone = phone
            changed.append("phone")
    if "birth_date" in sent:
        if body.birth_date and not date(1900, 1, 1) <= body.birth_date <= datetime.now(UTC).date():
            raise HTTPException(422, {"code": "BAD_BIRTH_DATE", "message": "Ngày sinh không hợp lệ."})
        if body.birth_date != u.birth_date:
            u.birth_date = body.birth_date
            changed.append("birth_date")
    if "national_id" in sent:
        nid = re.sub(r"\s", "", body.national_id or "") or None
        if nid and not NATIONAL_ID.match(nid):
            raise HTTPException(422, {"code": "BAD_NATIONAL_ID", "message": "Số CCCD gồm 12 chữ số (hoặc 9 chữ số với CMND cũ)."})
        if nid != _read_id(u.national_id_enc):
            u.national_id_enc = _fernet().encrypt(nid.encode()).decode() if nid else None
            changed.append("national_id")
    return changed


@router.patch("/team/{user_id}")
async def update_member(user_id: UUID, body: Patch, response: Response, request: Request, sess: Session = need(Perm.TEAM_MANAGE)) -> dict[str, Any]:
    """Name, email, phone, date of birth, ID number, role and status. Your own account is editable too, except role and status (a business
    must not lose its last owner by accident).

    The email is both the sign-in name and where password links go, so moving it is guarded: the person is signed out everywhere (you
    keep your own session when it is yours), links sent to the old address stop working, the old address is told, and the change is in the log.
    If the person never opened their invitation, it simply goes again to the new address."""
    notify_old: tuple[str, str] | None = None
    resend = False
    fresh: str | None = None
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await s.get(m.AppUser, user_id)
        if u is None:
            raise HTTPException(404, "user not found")
        if user_id == sess.user_id and (body.role not in (None, u.role) or body.status not in (None, u.status)):
            raise HTTPException(409, {"code": "SELF_CHANGE", "message": "Bạn không tự đổi vai trò hay khoá chính mình được; nhờ một chủ khác."})
        new_email = None
        if body.email is not None:
            try:
                new_email = normalise_email(body.email)
            except AccountError as e:
                raise _refuse(e) from None
            if new_email == u.email:
                new_email = None
        before = {"name": u.display_name, "email": u.email, "role": u.role, "status": u.status}
        try:
            await change_role_or_status(s, u, role=body.role, status=body.status, now=datetime.now(UTC))
        except AccountError as e:
            raise _refuse(e) from None
        if body.name:
            u.display_name = body.name.strip()
        personal = _personal(body, u)
        email_moved = False
        if new_email:
            invited, old_email = is_invited(u), u.email
            u.email = new_email
            try:
                async with s.begin_nested():
                    await s.flush()
            except IntegrityError:
                raise _refuse(AccountError("EMAIL_TAKEN", "Email này đã có tài khoản.")) from None
            now = datetime.now(UTC)
            await s.execute(update(m.PasswordReset).where(m.PasswordReset.user_id == u.id, m.PasswordReset.used_at.is_(None)).values(used_at=now))
            if invited:
                resend = u.status == "active" and links.enabled()
            else:
                mine = user_id == sess.user_id
                await sessions.revoke_user(s, u.id, "email_changed", now, keep=sess.session_id if mine else None)
                if mine:  # the version was raised: the sign-in being used is given the new one, so the person who made the change stays in
                    fresh = await sessions.reissue(s, u.id, sess.session_id, sess.auth_time, now)
                if links.enabled():
                    notify_old = (old_email, u.display_name)
            email_moved = True
        after = {"name": u.display_name, "email": u.email, "role": u.role, "status": u.status}
        changes = diff(before, after) + [{"field": f, "before": "•••", "after": "•••"} for f in personal]  # that they changed, never to what
        if changes:
            verb = "Khoá" if after["status"] == "disabled" and before["status"] == "active" else "Mở lại" if before["status"] == "disabled" and after["status"] == "active" else "Sửa"
            await audit(sess, s, "config", "user.updated", f"{verb} tài khoản {u.email}", obj=("user", str(u.id), u.display_name), changes=changes,
                        metadata={"email_moved": True} if email_moved else None)
        item = _item(u, 0, sess.user_id, (await _classes_of(s, u.id)).get(u.id))
        new_address, who = u.email, u.display_name
    if fresh:
        auth.set_cookie(response, request, fresh, sess.auth_time)
    if resend:  # the invitation goes again, to the corrected address
        item["mail_sent"] = (await _send_invite(sess, user_id, new=True))["mail_sent"]
    if notify_old:
        subject, text_ = links.email_changed_mail(who, new_address, sess.name)
        await links.deliver(notify_old[0], subject, text_)
    return item


class TeacherClasses(BaseModel):
    class_ids: list[UUID] = Field(max_length=500)


@router.put("/team/{user_id}/classes")
async def set_teacher_classes(user_id: UUID, body: TeacherClasses, sess: Session = need(Perm.TEAM_MANAGE)) -> dict[str, Any]:
    """The whole list of classes this teacher is in charge of. It takes effect at their next request: every call reads it again."""
    wanted = set(body.class_ids)
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await s.get(m.AppUser, user_id, with_for_update=True)  # two owners saving at once take turns
        if u is None:
            raise HTTPException(404, "user not found")
        if u.role != Role.TEACHER:
            raise HTTPException(409, {"code": "NOT_TEACHER", "message": "Chỉ giao lớp cho tài khoản có vai trò giáo viên."})
        names = dict((await s.execute(select(m.Class.id, m.Class.name).where(m.Class.id.in_(wanted), m.Class.listed.is_(True)))).all()) if wanted else {}
        if set(names) != wanted:
            raise HTTPException(422, {"code": "BAD_CLASS", "message": "Có lớp không còn tồn tại, hãy tải lại trang."})
        had = {c["id"]: c["name"] for c in (await _classes_of(s, u.id)).get(u.id, [])}
        await s.execute(delete(m.ClassTeacher).where(m.ClassTeacher.user_id == u.id))
        s.add_all(m.ClassTeacher(id=uuid7(), tenant_id=sess.caller.tenant_id, class_id=c, user_id=u.id, assigned_by=sess.actor) for c in wanted)
        await s.flush()
        now = {str(k): v for k, v in names.items()}
        if set(had) != set(now):
            await audit(sess, s, "config", "user.classes_changed", f"Giao {len(now)} lớp cho {u.email}", obj=("user", str(u.id), u.display_name),
                        metadata={"added": sorted(v for k, v in now.items() if k not in had), "removed": sorted(v for k, v in had.items() if k not in now)})
        return _item(u, 0, sess.user_id, (await _classes_of(s, u.id)).get(u.id))


@router.post("/team/{user_id}/send-link")
async def send_link(user_id: UUID, sess: Session = need(Perm.TEAM_MANAGE)) -> dict[str, Any]:
    """Mails this person a link to choose a password: the invitation again if they never opened it, a reset link otherwise.
    Their current password keeps working until they use the link; to cut a sign-in now, end their sessions."""
    if user_id == sess.user_id:
        raise HTTPException(409, {"code": "SELF_CHANGE", "message": "Hãy đổi mật khẩu của chính bạn ở trang Tài khoản."})
    if not links.enabled():
        raise HTTPException(409, MAIL_OFF)
    return await _send_invite(sess, user_id, new=False)


class OwnPassword(BaseModel):
    password: str = Field(min_length=1, max_length=passwords.MAX_LEN)


@router.post("/team/{user_id}/mfa/disable")
async def disable_mfa(user_id: UUID, body: OwnPassword, sess: Session = need(Perm.TEAM_MANAGE)) -> dict[str, Any]:
    """For a staff member or teacher who lost their phone and their recovery codes. The owner confirms with their own password; nothing
    secret is shown to the owner: the person signs in with their password and, if they want, sets it up again on their own screen. Their
    devices are signed out (one of them may be the lost phone), they get a mail saying so, and the trail keeps who did it. Another owner's
    is not turned off from here: that goes through the operator (`cli reset-mfa`)."""
    from cortex_leads.auth import mfa
    from cortex_leads.console.mfa import check_password
    from cortex_leads.notify.mailer import MailError, get_mailer

    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        me = await s.get(m.AppUser, sess.user_id)
        u = await s.get(m.AppUser, user_id)
        if u is None:
            raise HTTPException(404, "user not found")
        if u.id == sess.user_id:
            raise HTTPException(409, {"code": "USE_ACCOUNT_PAGE", "message": "Tắt xác thực 2 lớp của chính bạn ở trang Tài khoản."})
        if u.role == Role.OWNER:
            raise HTTPException(409, {"code": "OWNER_MFA", "message": "Không tắt được xác thực 2 lớp của một chủ khác ở đây. Nhờ người hỗ trợ kỹ thuật."})
        if u.mfa_enabled_at is None:
            return {"mfa": False, "sessions_ended": 0}
        await check_password(sess, me, body.password, now)
        mfa.turn_off(u)
        ended = await sessions.revoke_user(s, u.id, "mfa_disabled_by_owner", now)
        await audit(sess, s, "auth", "mfa.disabled_by_owner", f"Tắt xác thực 2 lớp của {u.email}", obj=("user", str(u.id), u.display_name),
                    metadata={"sessions_ended": ended})
        to, who, business = u.email, sess.name, sess.tenant_name
    mailer = get_mailer()
    if mailer is not None:  # best effort: the change is made and logged whether or not the mail leaves
        try:
            await mailer.send(to, "Xác thực 2 lớp của bạn đã được tắt",
                              f"{who} ({business}) vừa tắt xác thực 2 lớp cho tài khoản của bạn, và mọi thiết bị của bạn đã bị đăng xuất.\n\n"
                              "Bạn đăng nhập lại bằng mật khẩu như thường, rồi có thể bật lại ở Tài khoản → Xác thực 2 lớp.\n"
                              "Nếu bạn không nhờ việc này, hãy báo ngay cho chủ trung tâm và đổi mật khẩu.")
        except MailError:
            pass
    return {"mfa": False, "sessions_ended": ended}


@router.post("/team/{user_id}/end-sessions")
async def end_sessions(user_id: UUID, sess: Session = need(Perm.TEAM_MANAGE)) -> dict[str, int]:
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await s.get(m.AppUser, user_id)
        if u is None:
            raise HTTPException(404, "user not found")
        n = await sessions.revoke_user(s, u.id, "ended_by_owner", datetime.now(UTC))
        await audit(sess, s, "auth", "sessions.ended", f"Đăng xuất mọi thiết bị của {u.email}", obj=("user", str(u.id), u.display_name), metadata={"sessions": n})
    return {"ended": n}
