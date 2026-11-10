"""Choosing a Drive file in Google's own dialog (the Picker) to attach to an assignment (WP44). The dialog runs in the browser and needs an access
token there. That token is the ONE part of a Google sign-in that leaves the server, and only in this shape: minted fresh for the call, narrowed to
the single permission `drive.file` (a file the teacher picks is then granted to this app, nothing else in their Drive), about an hour of life, never
written to a log or the trail. The refresh token stays here. Which Drive opens is the Drive of the connected Google account, not of whoever is
signed in to the browser.

A teacher (WP46) gets the dialog of their own class's account only, and with `browse` off the page offers an upload from their computer and no way
to look through that Drive: on an account shared by every class, it holds the other classes' files. That is a limit on the page, not on the token,
which still reaches whatever this app made or was given on that account while it lives (REVIEW R165)."""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from cortex_leads.config import get_settings
from cortex_leads.connectors import google_accounts as ga
from cortex_leads.console.auth import Session, need
from cortex_leads.console.scope import ALL, ensure_class
from cortex_leads.console.trail import audit
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

router = APIRouter()
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"


def _configured() -> bool:
    s = get_settings()
    return bool(s.GOOGLE_PICKER_API_KEY and s.GOOGLE_PROJECT_NUMBER)


def _can_pick(a: m.GoogleAccount) -> bool:
    return a.status == "active" and not ga.missing_for("drive", a.scopes)


@router.get("/google/picker")
async def picker_info(class_id: UUID | None = None, sess: Session = need("grading.use")) -> dict[str, Any]:
    """Whether the Picker is switched on here, which connected accounts can open it, and the one to start with: for a class, the account that acts
    in its Classroom course (it creates the work, so it must be able to open the files), else the account of its Drive, else the first that can."""
    async with tenant_session(sess.caller.tenant_id) as s:
        rows = (await s.execute(select(m.GoogleAccount).where(m.GoogleAccount.status == "active").order_by(m.GoogleAccount.created_at))).scalars().all()
        wanted = None
        if class_id is not None:
            await ensure_class(s, sess, class_id)
            cls = await s.get(m.Class, class_id)
            if cls is None:
                raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có lớp này"})
            wanted = cls.classroom_account_id or cls.drive_account_id
    browse = sess.can(ALL)
    if not browse:  # no other account's address, and without a class, none at all
        rows = [a for a in rows if a.id == wanted]
    items = [{"id": str(a.id), "label": a.label, "email": a.email, "can_pick": _can_pick(a)} for a in rows]
    usable = [a for a in rows if _can_pick(a)]
    first = next((a for a in usable if a.id == wanted), usable[0] if usable else None)
    return {"configured": _configured(), "accounts": items, "default_account_id": str(first.id) if first else None, "browse": browse}


class PickerTokenIn(BaseModel):
    account_id: UUID
    class_id: UUID | None = None  # the class it is for: a teacher must say, and it must be theirs


@router.post("/google/picker/token")
async def picker_token(body: PickerTokenIn, sess: Session = need("grading.use")) -> dict[str, Any]:
    if not _configured():
        raise HTTPException(409, {"code": "PICKER_NOT_CONFIGURED", "message": "Máy chủ này chưa bật chọn tệp từ Google Drive"})
    gone = HTTPException(404, {"code": "NOT_FOUND", "message": "Không có tài khoản Google này, hoặc tài khoản đã bị ngắt kết nối"})
    async with tenant_session(sess.caller.tenant_id) as s:
        if not sess.can(ALL):
            if body.class_id is None:
                raise gone
            await ensure_class(s, sess, body.class_id)
            cls = await s.get(m.Class, body.class_id)
            if cls is None or (cls.classroom_account_id or cls.drive_account_id) != body.account_id:
                raise gone
        a = await s.get(m.GoogleAccount, body.account_id)
        if a is None or a.status != "active":
            raise gone
        if not _can_pick(a):
            raise HTTPException(409, {"code": "MISSING_SCOPE", "message": "Tài khoản này chưa cấp quyền Drive. Hãy kết nối lại Google và tick quyền Drive"})
        secret, label, email = ga.account_secret(a), a.label, a.email
    try:
        token, ttl = await ga.short_lived_token(secret, DRIVE_FILE)
    except ga.GoogleSetupError:
        raise HTTPException(409, {"code": "UNAUTHENTICATED", "message": "Phiên kết nối Google của tài khoản này đã hết hạn hoặc bị thu hồi. Hãy kết nối lại Google"}) from None
    async with tenant_session(sess.caller.tenant_id) as s:
        await audit(sess, s, "config", "google.picker_token", f"Mở hộp chọn tệp Drive của «{label}»", obj=("google_account", str(body.account_id), label),
                    metadata={"scope": "drive.file", **({"class_id": str(body.class_id)} if body.class_id else {})})  # never the token
    st = get_settings()
    return {"token": token, "expires_in": ttl, "api_key": st.GOOGLE_PICKER_API_KEY, "app_id": st.GOOGLE_PROJECT_NUMBER, "email": email}
