"""Nhân viên & quyền (WP30): the owner makes accounts, changes roles, disables people and resets passwords. A password is shown
once, to the owner, as a temporary one the person must replace at their first sign-in. Nothing here can read or set a password
the person chose, and nobody can lock the business out of its own owner."""
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from cortex_leads.audit.service import diff
from cortex_leads.auth import passwords, sessions
from cortex_leads.auth.users import AccountError, change_role_or_status, create_user, set_password
from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import audit
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

router = APIRouter()


def _refuse(e: AccountError) -> HTTPException:
    return HTTPException(409 if e.code in ("LAST_OWNER", "EMAIL_TAKEN") else 422, {"code": e.code, "message": e.message})


def _item(u: m.AppUser, active_sessions: int, me: UUID) -> dict[str, Any]:
    return {"id": str(u.id), "email": u.email, "name": u.display_name, "role": u.role, "staff_ref": u.staff_ref, "status": u.status,
            "must_change_password": u.must_change_password, "last_login_at": wire(u.last_login_at) if u.last_login_at else None,
            "created_at": wire(u.created_at), "sessions": active_sessions, "you": u.id == me}


@router.get("/team")
async def list_team(sess: Session = need("team.manage")) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        users = (await s.execute(select(m.AppUser).order_by(m.AppUser.role.asc(), m.AppUser.created_at))).scalars().all()
        counts = dict((await s.execute(select(m.AuthSession.user_id, func.count()).where(
            m.AuthSession.revoked_at.is_(None), m.AuthSession.expires_at > now).group_by(m.AuthSession.user_id))).all())
    return {"items": [_item(u, counts.get(u.id, 0), sess.user_id) for u in users], "min_password": passwords.MIN_LEN}


class NewUser(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=2, max_length=80)
    role: Literal["owner", "staff"] = "staff"


@router.post("/team", status_code=201)
async def add_member(body: NewUser, sess: Session = need("team.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        try:
            user, temp = await create_user(s, sess.caller.tenant_id, email=body.email, name=body.name, role=body.role, created_by=sess.actor)
        except AccountError as e:
            raise _refuse(e) from None
        await audit(sess, s, "config", "user.created", f"Thêm tài khoản {user.email} ({'chủ' if user.role == 'owner' else 'nhân viên'})",
                    obj=("user", str(user.id), user.display_name), metadata={"role": user.role, "email": user.email})
        return {"id": str(user.id), "email": user.email, "staff_ref": user.staff_ref, "temporary_password": temp}


class Patch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    role: Literal["owner", "staff"] | None = None
    status: Literal["active", "disabled"] | None = None


@router.patch("/team/{user_id}")
async def update_member(user_id: UUID, body: Patch, sess: Session = need("team.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await s.get(m.AppUser, user_id)
        if u is None:
            raise HTTPException(404, "user not found")
        if user_id == sess.user_id and (body.role not in (None, u.role) or body.status not in (None, u.status)):
            raise HTTPException(409, {"code": "SELF_CHANGE", "message": "Bạn không tự đổi vai trò hay khoá chính mình được; nhờ một chủ khác."})
        before = {"name": u.display_name, "role": u.role, "status": u.status}
        try:
            await change_role_or_status(s, u, role=body.role, status=body.status, now=datetime.now(UTC))
        except AccountError as e:
            raise _refuse(e) from None
        if body.name:
            u.display_name = body.name.strip()
        after = {"name": u.display_name, "role": u.role, "status": u.status}
        if before != after:
            verb = "Khoá" if after["status"] == "disabled" and before["status"] == "active" else "Mở lại" if before["status"] == "disabled" and after["status"] == "active" else "Sửa"
            await audit(sess, s, "config", "user.updated", f"{verb} tài khoản {u.email}", obj=("user", str(u.id), u.display_name), changes=diff(before, after))
        return _item(u, 0, sess.user_id)


@router.post("/team/{user_id}/reset-password")
async def reset_password(user_id: UUID, sess: Session = need("team.manage")) -> dict[str, str]:
    """A new temporary password, shown once. Every sign-in of that person ends and they must choose their own password."""
    if user_id == sess.user_id:
        raise HTTPException(409, {"code": "SELF_CHANGE", "message": "Hãy đổi mật khẩu của chính bạn ở trang Tài khoản."})
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await s.get(m.AppUser, user_id)
        if u is None:
            raise HTTPException(404, "user not found")
        temp = passwords.temporary_password()
        ended = await set_password(s, u, temp, must_change=True, now=datetime.now(UTC))
        await audit(sess, s, "auth", "password.reset", f"Đặt lại mật khẩu của {u.email}", obj=("user", str(u.id), u.display_name), metadata={"sessions_ended": ended})
        return {"temporary_password": temp, "email": u.email}


@router.post("/team/{user_id}/end-sessions")
async def end_sessions(user_id: UUID, sess: Session = need("team.manage")) -> dict[str, int]:
    async with tenant_session(sess.caller.tenant_id) as s:
        u = await s.get(m.AppUser, user_id)
        if u is None:
            raise HTTPException(404, "user not found")
        n = await sessions.revoke_user(s, u.id, "ended_by_owner", datetime.now(UTC))
        await audit(sess, s, "auth", "sessions.ended", f"Đăng xuất mọi thiết bị của {u.email}", obj=("user", str(u.id), u.display_name), metadata={"sessions": n})
    return {"ended": n}
