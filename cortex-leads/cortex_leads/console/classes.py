"""Lớp học (WP38): a `class` is a Drive folder with its own team channel, and the Classroom course it posts to and grades. Its recordings are read
from the folder, uploads go into it, and its recaps are posted to its own Mezon webhook, so one class's lessons never mix with another's.
Two policies live on the class: `recap_mode` (a finished recap goes out by itself, or waits for a person) and `grading_mode` (manual, review,
auto_write). Everyone on the teaching team sees the list, a teacher only their own classes (WP46). Only the owner makes a class, connects it to
Google or to a channel, or lets the machine write grades by itself; a teacher changes the rest of their own class (a webhook address is a secret: only its host is shown)."""
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from cortex_leads.auth.perms import Perm
from cortex_leads.connectors import google_accounts as ga
from cortex_leads.connectors.classroom import ClassroomError, open_classroom, valid_id
from cortex_leads.connectors.drive_store import DriveError, open_uploader
from cortex_leads.connectors.egress import EgressError, ensure_callable
from cortex_leads.console.auth import Session, need
from cortex_leads.console.google import watch_folder
from cortex_leads.console.sandboxes import label_of
from cortex_leads.console.scope import my_classes, need_class
from cortex_leads.console.trail import audit, audit_new
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

router = APIRouter()
WAITING = ("queued", "working")
DRIVE_ERRORS = {"UNAUTHENTICATED": (409, "Phiên Google đã hết hạn hoặc bị thu hồi, hãy kết nối lại tài khoản"),
                "PERMISSION_DENIED": (409, "Tài khoản này không được phép tạo thư mục trong Drive"), "STORAGE_FULL": (507, "Drive đã hết dung lượng"),
                "RATE_LIMITED": (503, "Google đang giới hạn tốc độ, thử lại sau ít phút")}
COURSE_ERRORS = {"UNAUTHENTICATED": (409, "Phiên Google đã hết hạn hoặc bị thu hồi, hãy kết nối lại tài khoản"),
                 "PERMISSION_DENIED": (409, "Google không cho tài khoản này tạo lớp trên Classroom (thường gặp với Gmail cá nhân, hoặc tài khoản trường chưa được quản trị viên cho làm giáo viên). Hãy chọn lớp có sẵn hoặc dùng tài khoản khác"),
                 "RATE_LIMITED": (503, "Google đang giới hạn tốc độ, thử lại sau ít phút")}


def _classroom(secret: bytes) -> Any:
    return open_classroom(secret)  # looked up at call time, so a test can stand a fake Classroom in its place


def is_class() -> Any:
    """What the console lists as a class: a `class` a person made or connected, not one kept only because lessons point at a source made on the command line."""
    return (m.Class.listed.is_(True),)


def webhook_host(t: m.NotifyTarget | None) -> str | None:
    return (urlsplit(t.address).hostname or "") if t is not None else None


async def class_rows(s: Any, only_active: bool = False, only: set[UUID] | None = None) -> list[dict[str, Any]]:
    """`only`: limit to these classes (`scope.my_classes`); None is every class."""
    counts: dict[tuple[Any, str], int] = {(cid, st): n for cid, st, n in (await s.execute(
        select(m.Lesson.class_id, m.Lesson.status, func.count()).group_by(m.Lesson.class_id, m.Lesson.status))).all()}
    held: dict[Any, int] = dict((await s.execute(select(m.Lesson.class_id, func.count()).where(
        m.Lesson.status == "done", m.Lesson.released_at.is_(None)).group_by(m.Lesson.class_id))).all())
    grading: dict[Any, dict[str, int]] = {}
    for cid, st, n in (await s.execute(select(m.Assignment.class_id, m.GradeItem.status, func.count()).join(
            m.Assignment, m.Assignment.id == m.GradeItem.assignment_id).group_by(m.Assignment.class_id, m.GradeItem.status))).all():
        grading.setdefault(cid, {})[st] = n
    works: dict[Any, int] = dict((await s.execute(select(m.Assignment.class_id, func.count()).where(
        m.Assignment.state.in_(("draft", "created"))).group_by(m.Assignment.class_id))).all())
    sandboxes = {sb.id: label_of(sb) for sb in (await s.execute(select(m.Sandbox))).scalars()}
    targets = {t.id: t for t in (await s.execute(select(m.NotifyTarget))).scalars()}
    q = select(m.Class).where(*is_class()).order_by(m.Class.created_at)
    if only_active:
        q = q.where(m.Class.active.is_(True))
    if only is not None:
        q = q.where(m.Class.id.in_(only))
    out = []
    for c in (await s.execute(q)).scalars():
        g = grading.get(c.id, {})
        out.append({"id": str(c.id), "name": c.name, "sandbox_id": str(c.recap_sandbox_id) if c.recap_sandbox_id else None,
                    "sandbox": sandboxes.get(c.recap_sandbox_id, ""), "grader_sandbox_id": str(c.grader_sandbox_id) if c.grader_sandbox_id else None,
                    "account": c.drive_account.label if c.drive_account else None, "account_id": str(c.drive_account_id) if c.drive_account_id else None,
                    "linked": c.drive_account is not None and c.drive_account.status == "active", "active": c.active, "since": wire(c.created_at),
                    "folder": "Do Cortex tạo trong Drive" if c.owned else "Thư mục có sẵn (chỉ đọc)", "owned": c.owned,
                    "folder_url": f"https://drive.google.com/drive/folders/{c.source_ref}" if c.source_ref else None,
                    "can_upload": c.owned and c.active and c.drive_account is not None and c.drive_account.status == "active",
                    "webhook": webhook_host(targets.get(c.notify_target_id)), "has_webhook": c.notify_target_id is not None,
                    "classroom": {"course_id": c.course_id, "course": c.course_name, "account_id": str(c.classroom_account_id) if c.classroom_account_id else None} if c.course_id else None,
                    "policy": {"recap_mode": c.recap_mode, "grading_mode": c.grading_mode, "assignment_post_mode": c.assignment_post_mode},
                    "can_grade": c.grader_sandbox_id is not None,
                    "lessons": {"done": counts.get((c.id, "done"), 0), "failed": counts.get((c.id, "failed"), 0),
                                "waiting": sum(counts.get((c.id, st), 0) for st in WAITING), "held": held.get(c.id, 0)},
                    "grading": {"assignments": works.get(c.id, 0), "to_review": g.get("proposed", 0), "pending": g.get("pending", 0),
                                "waiting": sum(g.get(st, 0) for st in WAITING), "done": g.get("approved", 0) + g.get("rejected", 0)}})
    return out


@router.get("/classes")
async def list_classes(sess: Session = need(Perm.LESSONS_READ)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        return {"items": await class_rows(s, only=await my_classes(s, sess))}


async def _webhook(s: Any, tenant_id: UUID, url: str, label: str) -> m.NotifyTarget:
    """The Mezon channel behind `url`, made once: two classes may post to the same channel."""
    try:
        await ensure_callable(url)
    except EgressError:
        raise HTTPException(422, {"code": "BAD_WEBHOOK", "message": "Địa chỉ webhook không dùng được: phải là https, thuộc máy chủ Mezon được cho phép, không chứa tài khoản đăng nhập"}) from None
    t = (await s.execute(select(m.NotifyTarget).where(m.NotifyTarget.kind == "mezon", m.NotifyTarget.address == url))).scalar_one_or_none()
    if t is None:
        t = m.NotifyTarget(tenant_id=tenant_id, kind="mezon", address=url, label=label)
        s.add(t)
        await s.flush()
    t.active = True
    return t


class NewClass(BaseModel):
    sandbox_id: UUID
    account_id: UUID
    name: str = Field(min_length=2, max_length=60)
    folder: str = Field(default="new", min_length=3, max_length=80, pattern=r"^[\w-]+$")  # "new": Cortex makes it in the account's Drive; else the id of a folder to watch
    webhook_url: str | None = Field(default=None, max_length=600)
    classroom_course_id: str | None = Field(default=None, max_length=64)  # post each recap to this Classroom course (the account must allow it)
    classroom_account_id: UUID | None = None  # who posts; the class's own account if left out
    classroom_course_name: str | None = Field(default=None, max_length=200)
    recap_mode: Literal["auto", "review"] = "review"
    classroom_new: bool = False  # make a new Classroom course named like the class (needs an account signed in to create courses), instead of picking one
    grade_sandbox_id: UUID | None = None  # also let the AI grade this course's work: the Chấm bài sandbox to read it through


async def set_classroom(s: Any, c: m.Class, account_id: UUID | None, course_id: str | None, name: str | None) -> None:
    """Point the class at a Classroom course, or take it off (empty id). Posting needs the account to have been signed in with that permission."""
    if course_id is None:
        return
    if not course_id:
        if c.grader_sandbox_id is not None:
            raise HTTPException(409, {"code": "GRADES_THERE", "message": "Lớp này đang chấm bài trên khoá học đó, không thể gỡ"})
        c.course_id = c.course_name = c.classroom_account_id = None
        return
    if not valid_id(course_id):
        raise HTTPException(422, {"code": "BAD_COURSE", "message": "Mã lớp Classroom không hợp lệ"})
    a = await s.get(m.GoogleAccount, account_id or c.classroom_account_id or c.drive_account_id)
    if a is None or a.status != "active" or ga.missing_for("classroom_post", a.scopes):
        raise HTTPException(409, {"code": "MISSING_SCOPE", "message": "Tài khoản này chưa cấp quyền đăng lên Classroom. Hãy kết nối lại và tick «Đăng tổng kết lên Classroom»"})
    c.classroom_account_id = a.id
    await s.execute(update(m.Lesson).where(m.Lesson.class_id == c.id, m.Lesson.classroom_post_id.is_(None)).values(classroom_attempts=0, classroom_error=None))  # a new sign-in earns the unposted recaps a fresh start
    c.course_id, c.course_name = course_id, (name or "").strip()[:200] or None


@router.post("/classes", status_code=201)
async def add_class(body: NewClass, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    tid, name = sess.caller.tenant_id, body.name.strip()
    async with tenant_session(tid) as s:
        sb = await s.get(m.Sandbox, body.sandbox_id)
        if sb is None or sb.purpose != "lesson_recap":
            raise HTTPException(422, {"code": "BAD_SANDBOX", "message": "Chọn một sandbox Tổng kết buổi học"})
        a = await s.get(m.GoogleAccount, body.account_id)
        if a is None or a.status != "active":
            raise HTTPException(409, {"code": "ACCOUNT_UNAVAILABLE", "message": "Tài khoản Google này không dùng được, hãy kết nối lại"})
        make = body.folder == "new"
        if make and ga.missing_for("drive", a.scopes):
            raise HTTPException(409, {"code": "MISSING_SCOPE", "message": "Tài khoản này chưa cấp quyền Drive để tạo thư mục. Hãy kết nối lại và tick «Drive»"})
        if not make and ga.missing_for("drive_read", a.scopes):
            raise HTTPException(409, {"code": "MISSING_SCOPE", "message": "Tài khoản này chưa cấp quyền đọc thư mục có sẵn. Hãy kết nối lại và tick «Đọc thư mục Drive có sẵn»"})
        if (await s.execute(select(m.Class.id).where(m.Class.recap_sandbox_id == sb.id, m.Class.name == name, m.Class.active.is_(True)))).first():
            raise HTTPException(409, {"code": "NAME_TAKEN", "message": "Đã có lớp tên này"})
        ca = None  # the account that works in Classroom: the one named for it, else the class's own
        if body.classroom_course_id or body.classroom_new:
            ca = await s.get(m.GoogleAccount, body.classroom_account_id or a.id)
            if ca is None or ca.status != "active":
                raise HTTPException(409, {"code": "ACCOUNT_UNAVAILABLE", "message": "Tài khoản Google dùng cho Classroom không dùng được, hãy kết nối lại"})
            if body.classroom_new and (ga.missing_for("classroom_create", ca.scopes) or ga.missing_for("classroom_post", ca.scopes)):
                raise HTTPException(409, {"code": "MISSING_SCOPE", "message": "Tài khoản này chưa cấp quyền tạo lớp trên Classroom. Hãy kết nối lại và tick «Tạo lớp mới trên Classroom»"})
        grader = None
        if body.grade_sandbox_id:
            grader = await s.get(m.Sandbox, body.grade_sandbox_id)
            if grader is None or grader.purpose != "classroom_grader":
                raise HTTPException(422, {"code": "BAD_SANDBOX", "message": "Chọn một sandbox Chấm bài"})
            if ca is None:
                raise HTTPException(422, {"code": "NO_COURSE", "message": "Muốn AI chấm bài thì lớp phải có khoá học Classroom"})
            if ga.missing_for("classroom", ca.scopes):
                raise HTTPException(409, {"code": "MISSING_SCOPE", "message": "Tài khoản này chưa cấp quyền chấm bài Classroom. Hãy kết nối lại và tick «Classroom: chấm bài, giao bài»"})
        course: dict[str, str] | None = None
        if body.classroom_new:  # first: it is the step Google refuses most often, and a refusal then leaves nothing behind in Drive
            try:
                course = await _classroom(ga.account_secret(ca)).create_course((body.classroom_course_name or name).strip())
            except ClassroomError as e:
                status, message = COURSE_ERRORS.get(e.code, (502, "Google không tạo được lớp trên Classroom, hãy thử lại"))
                raise HTTPException(status, {"code": f"CLASSROOM_{e.code}", "message": message}) from None
        folder_id = body.folder
        if make:
            try:
                folder_id = await open_uploader(ga.account_secret(a)).ensure_folder(None, name)
            except DriveError as e:
                status, message = DRIVE_ERRORS.get(e.code, (502, "Google không tạo được thư mục, hãy thử lại"))
                raise HTTPException(status, {"code": f"DRIVE_{e.code}", "message": message}) from None
        target = await _webhook(s, tid, body.webhook_url.strip(), name) if body.webhook_url and body.webhook_url.strip() else None
        src = await watch_folder(s, tid, sb.id, a.id, folder_id, name)
        src.owned, src.notify_target_id, src.recap_mode = make, target.id if target else None, body.recap_mode
        if course is not None:
            await set_classroom(s, src, ca.id, course["id"], course["name"])
        elif body.classroom_course_id:
            await set_classroom(s, src, ca.id, body.classroom_course_id, body.classroom_course_name)
        if grader is not None:
            src.grader_sandbox_id, src.auth_kind, src.subject, src.classroom_secret_enc, src.classroom_account_id = grader.id, "oauth", None, None, ca.id
        await audit(sess, s, "config", "class.created", f"Tạo lớp «{name}»" + (" với webhook riêng" if target else "") + (" và lớp mới trên Classroom" if course else ""),
                    obj=("class", str(src.id), name), metadata={"account": a.label, "folder": "created" if make else "existing", "recap_mode": body.recap_mode,
                                                               "classroom": "created" if course else "existing" if body.classroom_course_id else None, "grading": grader is not None})
        return {"id": str(src.id), "name": name, "folder_url": f"https://drive.google.com/drive/folders/{folder_id}" if make else None,
                "classroom": {"course_id": src.course_id, "course": src.course_name, "url": course["url"] if course else None, "created": course is not None} if src.course_id else None,
                "grading": grader is not None}


class EditClass(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    webhook_url: str | None = Field(default=None, max_length=600)  # "" or null (sent): take the channel off the class
    active: bool | None = None
    classroom_course_id: str | None = Field(default=None, max_length=64)  # "" (sent): stop posting to Classroom
    classroom_account_id: UUID | None = None
    classroom_course_name: str | None = Field(default=None, max_length=200)
    recap_mode: Literal["auto", "review"] | None = None  # a finished recap goes out by itself, or waits for a person to release it
    grading_mode: Literal["manual", "review", "auto_write"] | None = None  # only a class connected to a Classroom course to grade can leave `review`


OWNER_ONLY_FIELDS = {"webhook_url", "active", "classroom_course_id", "classroom_account_id", "classroom_course_name"}  # where a class reaches outside itself, and whether it runs


async def _keep_to_teacher_fields(sess: Session, body: EditClass) -> None:
    """A teacher runs their class but does not rewire it: another Google account or course would reach another class's work, and letting the
    machine write grades by itself stays the owner's explicit choice (DESIGN 2026-10-30). Taking that back to `review` is theirs to do."""
    if sess.can(Perm.SOURCES_MANAGE):
        return
    if body.model_fields_set & OWNER_ONLY_FIELDS or body.grading_mode == "auto_write":
        await audit_new(sess, "access", "permission.refused", "Thử đổi phần chỉ chủ được đổi của lớp", result="denied", metadata={"fields": sorted(body.model_fields_set)})
        raise HTTPException(403, {"code": "FORBIDDEN", "message": "Chỉ chủ trung tâm đổi được phần này của lớp."})


async def _own(s: Any, class_id: UUID) -> m.Class:
    c = await s.get(m.Class, class_id)
    if c is None or not c.listed:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có lớp này"})
    return c


@router.patch("/classes/{class_id}")
async def edit_class(class_id: UUID, body: EditClass, sess: Session = need_class(Perm.CLASSES_EDIT)) -> dict[str, Any]:
    await _keep_to_teacher_fields(sess, body)
    async with tenant_session(sess.caller.tenant_id) as s:
        c = await _own(s, class_id)
        said = body.model_fields_set
        changes: dict[str, Any] = {}
        if body.name is not None:
            c.name = body.name.strip()
        if "webhook_url" in said:
            url = (body.webhook_url or "").strip()
            c.notify_target_id = (await _webhook(s, sess.caller.tenant_id, url, c.name)).id if url else None
        if body.active is not None:
            c.active = body.active
        if "classroom_course_id" in said:
            await set_classroom(s, c, body.classroom_account_id, body.classroom_course_id, body.classroom_course_name)
        if body.recap_mode is not None and body.recap_mode != c.recap_mode:
            if body.recap_mode == "auto" and c.recap_sandbox_id is None:
                raise HTTPException(409, {"code": "NO_RECAP", "message": "Lớp này không tổng kết bài giảng"})
            changes["recap_mode"] = (c.recap_mode, body.recap_mode)
            c.recap_mode = body.recap_mode
        if body.grading_mode is not None and body.grading_mode != c.grading_mode:
            if c.grader_sandbox_id is None:
                raise HTTPException(409, {"code": "NO_GRADER", "message": "Lớp này chưa nối khoá học Classroom để chấm bài"})
            changes["grading_mode"] = (c.grading_mode, body.grading_mode)
            c.grading_mode = body.grading_mode
            if body.grading_mode != "manual":  # leaving manual: what waited for a click is now the grader's to take
                await s.execute(update(m.GradeItem).where(m.GradeItem.status == "pending", m.GradeItem.assignment_id.in_(
                    select(m.Assignment.id).where(m.Assignment.class_id == c.id))).values(status="queued"))
        for what, (old, new) in changes.items():  # a looser policy is its own line in the trail: who let the machine do more, and when
            await audit(sess, s, "config", f"class.{what}", f"Lớp «{c.name}»: {what} {old} → {new}", obj=("class", str(c.id), c.name),
                        metadata={"from": old, "to": new})
        await audit(sess, s, "config", "class.edited", f"Sửa lớp «{c.name}»", obj=("class", str(c.id), c.name), metadata={"changed": sorted(said)})
        await s.flush()
        return next(x for x in await class_rows(s) if x["id"] == str(c.id))


@router.delete("/classes/{class_id}")
async def delete_class(class_id: UUID, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    """Takes the class and its lessons (recaps, transcripts) out of Cortex. The Drive folder and the recordings in it are left alone: they are the teacher's."""
    async with tenant_session(sess.caller.tenant_id) as s:
        c = await _own(s, class_id)
        name = c.name
        if (await s.execute(select(m.Assignment.id).where(m.Assignment.class_id == c.id).limit(1))).first():
            raise HTTPException(409, {"code": "HAS_ASSIGNMENTS", "message": "Lớp này đã có bài tập và bài nộp được chấm. Hãy tắt lớp thay vì xoá"})
        gone = (await s.execute(delete(m.Lesson).where(m.Lesson.class_id == c.id))).rowcount
        await s.delete(c)
        await audit(sess, s, "config", "class.deleted", f"Xoá lớp «{name}»", obj=("class", str(class_id), name), metadata={"lessons": gone})
        await s.flush()
    return {"deleted": str(class_id), "lessons": gone}


class Relink(BaseModel):
    account_id: UUID
    folder: str = Field(default="new", min_length=3, max_length=80, pattern=r"^[\w-]+$")  # "new": Cortex makes a folder; else the id of a folder to watch


@router.post("/classes/{class_id}/relink")
async def relink_class(class_id: UUID, body: Relink, sess: Session = need(Perm.SOURCES_MANAGE)) -> dict[str, Any]:
    """Gives a class whose Google account is gone (deleted or cut off) a new account and a Drive folder, new or existing. Its lessons, recaps and webhook stay."""
    async with tenant_session(sess.caller.tenant_id) as s:
        c = await _own(s, class_id)
        a = await s.get(m.GoogleAccount, body.account_id)
        if a is None or a.status != "active":
            raise HTTPException(409, {"code": "ACCOUNT_UNAVAILABLE", "message": "Tài khoản Google này không dùng được, hãy kết nối lại"})
        make = body.folder == "new"
        need_kind = "drive" if make else "drive_read"
        if ga.missing_for(need_kind, a.scopes):
            raise HTTPException(409, {"code": "MISSING_SCOPE", "message": "Tài khoản này chưa cấp quyền Drive" + ("" if make else " để đọc thư mục có sẵn") + ". Hãy kết nối lại và tick đủ quyền"})
        folder_id = body.folder
        if make:
            try:
                folder_id = await open_uploader(ga.account_secret(a)).ensure_folder(None, c.name)
            except DriveError as e:
                status, message = DRIVE_ERRORS.get(e.code, (502, "Google không tạo được thư mục, hãy thử lại"))
                raise HTTPException(status, {"code": f"DRIVE_{e.code}", "message": message}) from None
        taken = (await s.execute(select(m.Class.id).where(m.Class.recap_sandbox_id == c.recap_sandbox_id, m.Class.source_kind == "drive",
                                                          m.Class.source_ref == folder_id, m.Class.id != c.id))).first()
        if taken:
            raise HTTPException(409, {"code": "FOLDER_TAKEN", "message": "Thư mục này đang được một lớp khác dùng"})
        c.drive_account_id, c.source_secret_enc, c.source_ref, c.owned = a.id, None, folder_id, make
        await audit(sess, s, "config", "class.relinked", f"Nối lại lớp «{c.name}» với tài khoản Google «{a.label}»", obj=("class", str(c.id), c.name),
                    metadata={"account": a.label, "folder": "created" if make else "existing"})
        await s.flush()
        await s.refresh(c)
        return next(x for x in await class_rows(s) if x["id"] == str(c.id))
