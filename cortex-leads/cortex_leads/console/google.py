"""Kết nối Google (WP37), a section of Cài đặt: sign a Google account in from the console, once, and point Classroom courses and Drive targets at it. What
`classroom-login` + `add-classroom-source` + `add-drive-target` did on the command line is done here by clicks. An account is its own
record (so a teacher who owns both a class and a Drive connects once, and two teachers connect two accounts); a source only says which
account it uses. Only the owner manages them (`sources.manage`); the callback from Google carries no cookie, so it trusts only its signed `state`."""
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from cortex_leads.audit.service import record_new
from cortex_leads.auth.perms import Perm
from cortex_leads.auth.roles import Role
from cortex_leads.config import get_settings
from cortex_leads.connectors import google_accounts as ga
from cortex_leads.connectors.classroom import ClassroomError, open_classroom, valid_id
from cortex_leads.console.auth import Session, need
from cortex_leads.console.sandboxes import label_of
from cortex_leads.console.trail import audit
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

router = APIRouter()
Kind = Literal["classroom", "classroom_post", "classroom_create", "drive", "drive_read"]
KIND_LABEL = {"classroom": "Google Classroom (chấm bài, giao bài)", "classroom_post": "Đăng tổng kết buổi học lên Google Classroom",
              "classroom_create": "Tạo lớp mới trên Google Classroom", "drive": "Google Drive (lưu bản ghi buổi học)",
              "drive_read": "Đọc thư mục Drive có sẵn (ví dụ bản ghi Google Meet)"}
SETUP_LINES = {"NOT_CONFIGURED": "Máy chủ chưa bật đăng nhập Google. Nhờ người hỗ trợ kỹ thuật bật tính năng này",
               "BAD_STATE": "Phiên kết nối đã hết hạn hoặc không hợp lệ, hãy bấm kết nối lại", "DENIED": "Bạn đã không đồng ý cấp quyền",
               "NO_REFRESH_TOKEN": "Google không trả về mã làm mới: vào myaccount.google.com/permissions, gỡ quyền của ứng dụng này rồi kết nối lại",
               "LABEL_TAKEN": "Đã có tài khoản Google tên này, hãy đặt tên khác", "EXCHANGE_FAILED": "Google từ chối mã đăng nhập, hãy thử kết nối lại"}
COURSES_ERRORS = {"UNAUTHENTICATED": (409, "Phiên Google đã hết hạn hoặc bị thu hồi, hãy kết nối lại"), "PERMISSION_DENIED": (409, "Tài khoản này chưa cấp quyền Classroom"),
                  "RATE_LIMITED": (503, "Google đang giới hạn tốc độ, thử lại sau ít phút")}


def _classroom(secret: bytes) -> Any:
    return open_classroom(secret)  # looked up at call time, so a test can stand a fake Classroom in its place


async def watch_folder(s: Any, tenant_id: UUID, sandbox_id: UUID, account_id: UUID, folder_id: str, label: str | None) -> m.Class:
    """Make `folder_id` a place the recap sandbox reads recordings from, signed in as the account. Again for a folder it already knows: it is
    switched on and moved to this account, its lessons kept. Files older than the first time it was connected are never picked up."""
    cls = (await s.execute(select(m.Class).where(m.Class.recap_sandbox_id == sandbox_id, m.Class.source_kind == "drive",
                                                 m.Class.source_ref == folder_id))).scalar_one_or_none()
    if cls is None:
        cls = m.Class(tenant_id=tenant_id, name=label or folder_id, listed=bool(label), recap_sandbox_id=sandbox_id, source_kind="drive", source_ref=folder_id)
        s.add(cls)
    cls.active, cls.source_secret_enc, cls.drive_account_id = True, None, account_id
    if label:
        cls.name, cls.listed = label, True
    await s.flush()
    return cls


def _can(a: m.GoogleAccount) -> dict[str, bool]:
    return {k: a.status == "active" and not ga.missing_for(k, a.scopes) for k in ga.KINDS}


async def _uses(s: Any, account_id: UUID) -> list[dict[str, str]]:
    return [{"kind": x["kind"], "name": x["name"], "sandbox": x["sandbox"]} for x in await _sources(s) if x["account_id"] == str(account_id) and x["active"]]


@dataclass
class Ref:
    """One thing that signs in as an account: a class's Drive folder, the Classroom course a class posts to, a graded course, or an old Drive target."""
    kind: str  # folder | post | classroom | target
    row: Any
    column: str
    name: str
    active: bool

    def public(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": str(self.row.id), "name": self.name, "active": self.active}


async def _refs(s: Any, account_id: UUID) -> list[Ref]:
    out: list[Ref] = []
    for c in (await s.execute(select(m.Class).where(m.Class.source_kind == "drive", m.Class.drive_account_id == account_id))).scalars():
        out.append(Ref("folder", c, "drive_account_id", c.name, c.active))
    for c in (await s.execute(select(m.Class).where(m.Class.classroom_account_id == account_id))).scalars():
        out.append(Ref("classroom" if c.grader_sandbox_id else "post", c, "classroom_account_id", c.name, c.active))
    for c in (await s.execute(select(m.DriveTarget).where(m.DriveTarget.google_account_id == account_id))).scalars():
        out.append(Ref("target", c, "google_account_id", c.label, c.active))
    return out


async def _sources(s: Any) -> list[dict[str, Any]]:
    """Every place a recap or grading sandbox reads from or stores to, whichever way it was connected: `account` says who it signs in as, and
    `legacy` marks the ones made on the command line with a key of their own."""
    sandboxes = {sb.id: label_of(sb) for sb in (await s.execute(select(m.Sandbox))).scalars()}
    out = []
    for c in (await s.execute(select(m.Class).order_by(m.Class.created_at))).scalars():
        if c.recap_sandbox_id and c.source_kind == "drive":  # a folder on the worker's disk, or the old `upload` placeholder, is not a Google source
            out.append({"kind": "folder", "id": str(c.id), "name": c.name, "sandbox": sandboxes.get(c.recap_sandbox_id, ""), "active": c.active,
                        "account": c.drive_account.label if c.drive_account else None, "account_id": str(c.drive_account_id) if c.drive_account_id else None,
                        "legacy": c.drive_account_id is None})
        if c.grader_sandbox_id:
            out.append({"kind": "classroom", "id": str(c.id), "name": c.name, "sandbox": sandboxes.get(c.grader_sandbox_id, ""), "active": c.active,
                        "account": c.classroom_account.label if c.classroom_account else None, "account_id": str(c.classroom_account_id) if c.classroom_account_id else None,
                        "legacy": c.classroom_account_id is None})
    return out


async def _row(s: Any, a: m.GoogleAccount) -> dict[str, Any]:
    return {"id": str(a.id), "label": a.label, "email": a.email, "status": a.status, "can": _can(a), "connected_at": wire(a.created_at),
            "connected_by": a.connected_by, "used_by": await _uses(s, a.id), "refs": [r.public() for r in await _refs(s, a.id)]}


@router.get("/google/accounts")
async def list_accounts(sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        rows = (await s.execute(select(m.GoogleAccount).order_by(m.GoogleAccount.created_at))).scalars().all()
        items = [await _row(s, a) for a in rows]
        sources = await _sources(s)
        sandboxes = [{"id": str(sb.id), "title": label_of(sb), "purpose": sb.purpose} for sb in (await s.execute(
            select(m.Sandbox).where(m.Sandbox.purpose.in_(("classroom_grader", "lesson_recap"))).order_by(m.Sandbox.created_at))).scalars()]
    try:
        ga.client()
        configured = True
    except ga.GoogleSetupError:
        configured = False
    return {"configured": configured, "items": items, "sources": sources, "sandboxes": sandboxes, "kinds": [{"id": k, "label": v} for k, v in KIND_LABEL.items()]}


class Connect(BaseModel):
    label: str = Field(min_length=2, max_length=60)
    kinds: list[Kind] = Field(min_length=1, max_length=5)


@router.post("/google/accounts/connect")
async def connect(body: Connect, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, str]:
    label = body.label.strip()
    async with tenant_session(sess.caller.tenant_id) as s:
        if (await s.execute(select(m.GoogleAccount.id).where(m.GoogleAccount.label == label))).first():
            raise HTTPException(409, {"code": "LABEL_TAKEN", "message": "Đã có tài khoản Google tên này, hãy đặt tên khác"})
    try:
        url = ga.begin(sess.caller.tenant_id, sess.actor, label, sorted(set(body.kinds)))
    except ga.GoogleSetupError as e:
        raise HTTPException(409, {"code": e.code, "message": SETUP_LINES[e.code]}) from None
    return {"url": url}


def _back(**query: str) -> RedirectResponse:
    from urllib.parse import urlencode

    return RedirectResponse("/app/settings?" + urlencode(query), status_code=303)


@router.get("/google/callback", include_in_schema=True)
async def callback(state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    """Google sends the person back here. No cookie is sent (SameSite=Strict), so `state` alone says who started this and for which business."""
    try:
        pending = ga.read_state(state)
    except ga.GoogleSetupError as e:
        return _back(error=e.code)
    if error or not code:
        return _back(error="DENIED")
    try:
        signed = await ga.finish(pending, code)
    except ga.GoogleSetupError as e:
        return _back(error=e.code)
    needs = [k for k in pending.kinds if ga.missing_for(k, signed.scopes)]
    enc = Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(signed.secret)
    async with tenant_session(pending.tenant_id) as s:
        if pending.reconnect is not None:  # the same account signed in again: its classes and courses keep pointing at it
            a = await s.get(m.GoogleAccount, pending.reconnect)
            if a is None:
                return _back(error="BAD_STATE")
            if a.email and signed.email and a.email.lower() != signed.email.lower():
                return _back(error="OTHER_ACCOUNT")  # a different Google user cannot see the folders the first one made
            a.secret_enc, a.scopes, a.status = enc, signed.scopes, "active"
            a.email = signed.email or a.email
            pending_label = a.label
        elif (await s.execute(select(m.GoogleAccount.id).where(m.GoogleAccount.label == pending.label))).first():  # taken while the person was at Google
            return _back(error="LABEL_TAKEN")
        else:
            s.add(m.GoogleAccount(tenant_id=pending.tenant_id, label=pending.label, email=signed.email, scopes=signed.scopes, secret_enc=enc,
                                  connected_by=pending.actor))
            pending_label = pending.label
    await record_new(pending.tenant_id, actor=pending.actor, role=Role.OWNER, category="config", action="google.reconnected" if pending.reconnect else "google.connected",
                     summary=f"{'Kết nối lại' if pending.reconnect else 'Kết nối'} tài khoản Google «{pending_label}»", obj=("google_account", pending_label, pending_label),
                     metadata={"scopes": signed.scopes})
    return _back(connected=pending_label, **({"partial": ",".join(needs)} if needs else {}))


async def _account(s: Any, account_id: UUID) -> m.GoogleAccount:
    a = await s.get(m.GoogleAccount, account_id)
    if a is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có tài khoản Google này"})
    return a


@router.post("/google/accounts/{account_id}/revoke")
async def revoke(account_id: UUID, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        a = await _account(s, account_id)
        if a.status == "revoked":
            return await _row(s, a)
        secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(a.secret_enc)
        a.status, a.secret_enc = "revoked", b""
        await audit(sess, s, "config", "google.revoked", f"Ngắt kết nối tài khoản Google «{a.label}»", obj=("google_account", str(a.id), a.label))
        out = await _row(s, a)
    await ga.revoke_at_google(secret)
    return out


class Reconnect(BaseModel):
    kinds: list[Kind] = Field(min_length=1, max_length=5)


@router.post("/google/accounts/{account_id}/reconnect")
async def reconnect(account_id: UUID, body: Reconnect, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, str]:
    """Sign the same account in again (it was cut off, or more permissions are wanted): its secret and permissions are replaced and everything
    that points at it keeps working. Only the same Google user is accepted."""
    async with tenant_session(sess.caller.tenant_id) as s:
        a = await _account(s, account_id)
        label = a.label
    try:
        url = ga.begin(sess.caller.tenant_id, sess.actor, label, sorted(set(body.kinds)), reconnect=account_id)
    except ga.GoogleSetupError as e:
        raise HTTPException(409, {"code": e.code, "message": SETUP_LINES[e.code]}) from None
    return {"url": url}


@router.delete("/google/accounts/{account_id}")
async def delete_account(account_id: UUID, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    """Removes the account for good. What signed in as it keeps its data (lessons, recaps, graded work) but loses its sign-in: it says so on its own
    page and is linked to another account there. Nothing here moves or blocks anything."""
    async with tenant_session(sess.caller.tenant_id) as s:
        a = await _account(s, account_id)
        refs = await _refs(s, a.id)
        secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(a.secret_enc) if a.status == "active" and a.secret_enc else None
        for r in refs:
            setattr(r.row, r.column, None)
        await s.flush()
        await audit(sess, s, "config", "google.deleted", f"Xóa tài khoản Google «{a.label}»", obj=("google_account", str(a.id), a.label),
                    metadata={"sources": len(refs)})
        await s.delete(a)
    if secret:
        await ga.revoke_at_google(secret)
    return {"deleted": str(account_id), "sources": len(refs)}


async def _active(s: Any, account_id: UUID, kind: Kind) -> m.GoogleAccount:
    a = await _account(s, account_id)
    if a.status != "active":
        raise HTTPException(409, {"code": "ACCOUNT_REVOKED", "message": "Tài khoản Google này đã bị ngắt, hãy kết nối lại"})
    if ga.missing_for(kind, a.scopes):
        raise HTTPException(409, {"code": "MISSING_SCOPE", "message": f"Tài khoản này chưa cấp quyền cho {KIND_LABEL[kind]}. Hãy kết nối lại và tick mục đó"})
    return a


@router.get("/google/accounts/{account_id}/courses")
async def courses(account_id: UUID, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        a = await _account(s, account_id)
        if a.status == "active" and ga.missing_for("classroom", a.scopes) and not ga.missing_for("classroom_post", a.scopes):
            pass  # signed in only to post recaps: it may list the courses it can post to
        else:
            a = await _active(s, account_id, "classroom")
        secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(a.secret_enc)
        connected = {r.course_id for r in (await s.execute(select(m.Class).where(
            m.Class.classroom_account_id == a.id, m.Class.grader_sandbox_id.is_not(None), m.Class.active.is_(True)))).scalars()}
    try:
        found = await _classroom(secret).courses()
    except ClassroomError as e:
        status, message = COURSES_ERRORS.get(e.code, (502, "Không đọc được danh sách lớp từ Google"))
        raise HTTPException(status, {"code": e.code, "message": message}) from None
    return {"items": [{"id": c["id"], "name": c.get("name", ""), "section": c.get("section", ""), "connected": c["id"] in connected} for c in found]}


class NewClassroom(BaseModel):
    sandbox_id: UUID
    account_id: UUID
    course_id: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=80)


@router.post("/google/classroom-sources", status_code=201)
async def add_classroom_source(body: NewClassroom, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    if not valid_id(body.course_id):
        raise HTTPException(422, {"code": "BAD_COURSE", "message": "Mã lớp không hợp lệ"})
    tid = sess.caller.tenant_id
    async with tenant_session(tid) as s:
        sb = await s.get(m.Sandbox, body.sandbox_id)
        if sb is None or sb.purpose != "classroom_grader":
            raise HTTPException(422, {"code": "BAD_SANDBOX", "message": "Chọn một sandbox Chấm bài"})
        a = await _active(s, body.account_id, "classroom")
        # the class that already has this course (its recordings are read from a folder, or it was connected before) takes the grading side;
        # only a course nobody has becomes a new class
        src = (await s.execute(select(m.Class).where(m.Class.course_id == body.course_id, or_(m.Class.grader_sandbox_id == sb.id, m.Class.grader_sandbox_id.is_(None)))
                               .order_by(m.Class.grader_sandbox_id.is_(None), m.Class.created_at).limit(1))).scalar_one_or_none()
        if src is None:
            src = m.Class(tenant_id=tid, name=body.label or body.course_id, course_id=body.course_id)  # a course a person connected is a class they see
            s.add(src)
        else:  # connecting a course again (another teacher, a new sign-in): keep its history, change who it is read as
            src.active = True
            src.listed = True
            if body.label:
                src.name = body.label
        src.grader_sandbox_id, src.auth_kind, src.subject, src.classroom_secret_enc, src.classroom_account_id = sb.id, "oauth", None, None, a.id
        await s.flush()
        await audit(sess, s, "config", "classroom.connected", f"Nối lớp «{src.name}» bằng tài khoản Google «{a.label}»",
                    obj=("class", str(src.id), src.name), metadata={"account": a.label})
        return {"id": str(src.id), "course_id": src.course_id, "account": a.label}


@router.get("/google/accounts/{account_id}/folders")
async def folders(account_id: UUID, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        a = await _account(s, account_id)
        if a.status != "active" or not (_can(a)["drive"] or _can(a)["drive_read"]):
            raise HTTPException(409, {"code": "MISSING_SCOPE", "message": "Tài khoản này chưa cấp quyền Drive. Hãy kết nối lại và tick mục Drive"})
        secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(a.secret_enc)
        watched = {r.source_ref for r in (await s.execute(select(m.Class).where(m.Class.drive_account_id == a.id, m.Class.active.is_(True)))).scalars()}
    try:
        found = await _classroom(secret).folders()
    except ClassroomError as e:
        status, message = COURSES_ERRORS.get(e.code, (502, "Không đọc được danh sách thư mục từ Google"))
        raise HTTPException(status, {"code": e.code, "message": message}) from None
    return {"items": [{**f, "connected": f["id"] in watched} for f in found], "full": _can(a)["drive_read"]}


class NewFolder(BaseModel):
    sandbox_id: UUID
    account_id: UUID
    folder_id: str = Field(min_length=10, max_length=80, pattern=r"^[\w-]+$")
    label: str | None = Field(default=None, max_length=80)


@router.post("/google/lesson-sources", status_code=201)
async def add_lesson_source(body: NewFolder, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    tid = sess.caller.tenant_id
    async with tenant_session(tid) as s:
        sb = await s.get(m.Sandbox, body.sandbox_id)
        if sb is None or sb.purpose != "lesson_recap":
            raise HTTPException(422, {"code": "BAD_SANDBOX", "message": "Chọn một sandbox Tổng kết buổi học"})
        a = await _account(s, body.account_id)
        if a.status != "active" or not (_can(a)["drive"] or _can(a)["drive_read"]):
            raise HTTPException(409, {"code": "MISSING_SCOPE", "message": "Tài khoản này chưa cấp quyền Drive. Hãy kết nối lại và tick mục Drive"})
        src = await watch_folder(s, tid, sb.id, a.id, body.folder_id, body.label)
        await audit(sess, s, "config", "lesson_source.connected", f"Theo dõi thư mục «{src.name}» bằng tài khoản Google «{a.label}»",
                    obj=("class", str(src.id), src.name), metadata={"account": a.label})
        return {"id": str(src.id), "folder_id": src.source_ref, "account": a.label}


class Switch(BaseModel):
    active: bool


@router.post("/google/sources/{kind}/{source_id}/active")
async def switch_source(kind: Literal["classroom", "folder"], source_id: UUID, body: Switch, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    """Turn a source off (nothing more is read from it or stored to it; its history stays) or back on."""
    async with tenant_session(sess.caller.tenant_id) as s:
        row = await s.get(m.Class, source_id)
        if row is None or (kind == "classroom" and row.grader_sandbox_id is None) or (kind == "folder" and row.recap_sandbox_id is None):
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có nguồn này"})
        if body.active and (row.drive_account_id if kind == "folder" else row.classroom_account_id) is None:  # made before WP37 with a key of its own: nothing reads those any more
            raise HTTPException(409, {"code": "LEGACY_SOURCE", "message": "Nguồn cũ đã ngừng hẳn. Hãy nối lại bằng tài khoản Google ở trên"})
        row.active = body.active  # the class is one thing: switching it off pauses its recordings and its grading together
        await audit(sess, s, "config", "google_source.on" if body.active else "google_source.off",
                    f"{'Bật' if body.active else 'Tắt'} nguồn «{row.name}»", obj=("class", str(row.id), row.name))
        return {"id": str(row.id), "active": row.active}
