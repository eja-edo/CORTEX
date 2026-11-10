"""Lessons (WP31): the recordings a lesson_recap sandbox has picked up, and the recap made from each. Read only: a recap is
a draft for the teacher, and what leaves the system goes out through `notify`, not from here. The transcript is the words of
a classroom, so it is served only to a signed-in person of this business (RLS), one lesson at a time, never in the list."""
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from cortex_leads.auth.perms import Perm
from cortex_leads.config import get_settings
from cortex_leads.connectors.drive_store import CHUNK, FOLDER_NAME, DriveError, open_uploader
from cortex_leads.connectors.google_accounts import secret_of_account
from cortex_leads.console.auth import Session, need
from cortex_leads.console.classes import class_rows
from cortex_leads.console.sandboxes import label_of
from cortex_leads.console.scope import my_classes, need_class
from cortex_leads.console.trail import audit
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.lessons import uploads
from cortex_leads.lessons.job import release
from cortex_leads.lessons.recap import render_recap, video_url
from cortex_leads.notify import service as notify
from cortex_leads.skills.registry import live_skills_for

router = APIRouter()
LIMIT = 100
STATUS = {"queued": "Đang chờ", "working": "Đang xử lý", "done": "Xong", "failed": "Thất bại"}
ERRORS = {"TOO_SHORT": "Bản ghi gần như không có tiếng nói", "BAD_SHAPE": "AI trả lời sai khuôn, sẽ thử lại",
          "LLM_ERROR": "AI không trả lời được, sẽ thử lại", "LINK_IN_OUTPUT": "AI chèn đường dẫn, đã chặn",
          "SOURCE_UNAVAILABLE": "Không mở được nguồn", "NO_AUDIO": "Tệp không có âm thanh để chuyển thành chữ",
          "NOT_MEDIA": "Tệp này không phải video hay âm thanh đọc được"}
ORIGIN = {"upload": "Tải lên", "drive": "Google Drive", "local": "Thư mục máy chủ"}
REFUSALS = {"TOO_LARGE": (413, "Tệp quá lớn"), "BAD_TYPE": (415, "Chỉ nhận video hoặc âm thanh: mp4, mov, webm, mkv, mp3, m4a, wav, ogg"),
            "EMPTY": (422, "Tệp trống")}


def _kind_of_media(name: str) -> str:
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return "video" if uploads.MEDIA_TYPES.get(suffix, "").startswith("video") else "audio"


POST_ERRORS = {"UNAUTHENTICATED": "Phiên Google đã hết hạn, hãy kết nối lại tài khoản", "PERMISSION_DENIED": "Tài khoản chưa có quyền đăng lên lớp Classroom này, hãy kết nối lại và tick «Đăng tổng kết lên Classroom»",
               "NOT_FOUND": "Không thấy lớp Classroom này (đã bị xóa hoặc tài khoản không còn trong lớp)", "INVALID_ARGUMENT": "Mã lớp Classroom không hợp lệ", "RATE_LIMITED": "Google đang giới hạn tốc độ, hệ thống sẽ thử lại"}


def classroom_state(lesson: m.Lesson, source: m.Class | None) -> dict[str, Any] | None:
    """Where this recap stands in the class's Classroom course. None: the class does not post there (or there is nothing to post yet)."""
    if source is None or not source.course_id or lesson.recap is None:
        return None
    course = source.course_name
    if lesson.classroom_post_id:
        return {"state": "posted", "course": course, "published": True, "error": None}
    if lesson.classroom_error and lesson.classroom_attempts >= 3:
        return {"state": "failed", "course": course, "published": True, "error": POST_ERRORS.get(lesson.classroom_error, "Không đăng được lên Classroom")}
    if lesson.released_at is None:  # the class waits for a person: nothing is posted before the release
        return {"state": "held", "course": course, "published": True, "error": None}
    return {"state": "waiting", "course": course, "published": True, "error": None}


def _row(lesson: m.Lesson, sandbox: m.Sandbox, source: m.Class | None = None) -> dict[str, Any]:
    error = lesson.error
    in_drive = source is not None and source.source_kind == "drive"  # every recording is read from a Drive folder: that is where it stays
    return {"id": str(lesson.id), "name": lesson.name, "origin": ORIGIN.get(source.source_kind or "", source.source_kind) if source else None,
            "storage": "drive" if in_drive else None, "has_media": in_drive, "media_type": _kind_of_media(lesson.name) if in_drive else None,
            "language": lesson.language, "status": lesson.status, "status_label": STATUS[lesson.status],
            "class_id": str(lesson.class_id), "class_name": source.name if source else None,
            "released": lesson.released_at is not None, "released_at": wire(lesson.released_at), "released_by": lesson.released_by,
            "awaiting_release": lesson.status == "done" and lesson.released_at is None,
            "attempts": lesson.attempts, "sandbox": label_of(sandbox), "created_at": wire(lesson.created_at),
            "finished_at": wire(lesson.finished_at), "has_recap": lesson.recap is not None,
            "classroom": classroom_state(lesson, source),
            "problem": (ERRORS.get(error) or ("Lỗi khi chuyển giọng nói thành chữ" if error.startswith("TRANSCRIBE_") else error)) if error else None}


@router.get("/lessons")
async def list_lessons(class_id: UUID | None = None, sess: Session = need(Perm.LESSONS_READ)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        mine = await my_classes(s, sess)
        q = (select(m.Lesson, m.Sandbox, m.Class).join(m.Sandbox, m.Sandbox.id == m.Lesson.sandbox_id)
             .join(m.Class, m.Class.id == m.Lesson.class_id).order_by(m.Lesson.created_at.desc()).limit(LIMIT))
        if mine is not None:
            q = q.where(m.Lesson.class_id.in_(mine))
        found = (await s.execute(q.where(m.Lesson.class_id == class_id) if class_id else q)).all()
        sandbox_ok = (await s.execute(select(m.Sandbox.id).where(m.Sandbox.purpose == "lesson_recap", m.Sandbox.status == "active").limit(1))).first() is not None
        classes = [c for c in await class_rows(s, only=mine) if c["active"]]
    return {"items": [_row(lesson, sandbox, source) for lesson, sandbox, source in found], "limit": LIMIT,
            "can_upload": sandbox_ok and any(c["can_upload"] for c in classes), "max_mb": uploads.get_settings().UPLOAD_MAX_MB,
            "classes": [{"id": c["id"], "name": c["name"], "can_upload": c["can_upload"], "lessons": c["lessons"]["done"] + c["lessons"]["failed"] + c["lessons"]["waiting"]} for c in classes]}


@router.get("/lessons/{lesson_id}")
async def get_lesson(lesson_id: UUID, sess: Session = need_class(Perm.LESSONS_READ)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        lesson = await s.get(m.Lesson, lesson_id)
        if lesson is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có buổi học này"})
        sandbox = await s.get(m.Sandbox, lesson.sandbox_id)
        source = await s.get(m.Class, lesson.class_id)
    video = video_url(source.source_kind or "", lesson.file_id)
    return {**_row(lesson, sandbox, source), "recap": lesson.recap, "video_url": video,
            "message": render_recap(lesson.name, lesson.recap, video, class_name=source.name) if lesson.recap else None,
            "transcript": lesson.transcript}


def _refuse(e: uploads.UploadRefused) -> HTTPException:
    status, message = REFUSALS.get(e.code, (422, "Không nhận được tệp này"))
    return HTTPException(status, {"code": e.code, "message": message})


UPLOAD_REFUSALS = {"UNAUTHENTICATED": (502, "Phiên Google của giáo viên đã hết hạn: cần đăng nhập lại"), "PERMISSION_DENIED": (502, "Tài khoản đã nối không có quyền ghi vào thư mục này"),
                   "NOT_FOUND": (502, "Không thấy thư mục trong Drive"), "STORAGE_FULL": (507, "Drive của giáo viên đã hết dung lượng")}


class NewUpload(BaseModel):
    name: str = Field(min_length=1, max_length=400)
    size: int = Field(ge=0)  # what the browser says it will send; Google holds the upload to it
    language: str = "auto"
    class_id: UUID | None = None  # which class the recording is for; the only one when there is just one


LOOPBACK = ("localhost", "127.0.0.1", "::1")


def upload_origin(request: Request) -> str:
    """The page the bytes will be sent from: scheme://host[:port] of CL_PUBLIC_BASE_URL when it is set (the safe way: a page that is not the
    console is refused). Unset (running locally), it is the address this very request came to, which is the console the person is using.
    One allowance: when the configured address is the machine itself (`127.0.0.1`), the same console opened as `localhost` is the same page, so
    that spelling, on the same port, is taken as it came."""
    base = get_settings().PUBLIC_BASE_URL
    u = urlsplit(base) if base else request.url
    sent = urlsplit(request.headers.get("origin") or "")
    if base and u.hostname in LOOPBACK and sent.hostname in LOOPBACK and (sent.scheme, sent.port) == (u.scheme, u.port):
        return f"{sent.scheme}://{sent.netloc}"
    return f"{u.scheme}://{u.netloc}"


@router.post("/lessons/upload/session", status_code=201)
async def start_upload(body: NewUpload, request: Request, sess: Session = need(Perm.LESSONS_UPLOAD)) -> dict[str, Any]:
    """Opens an upload to the teacher's Drive and hands the browser its session URL; the browser then sends the recording straight to Google,
    so it never passes through this server. The URL lets its holder write ONE new file, in the folder, under the name and with the properties
    fixed here, until it is finished or expires; nothing more, and it is given only to this signed-in person. Nothing is processed here: the
    watcher finds the file in the folder and is the one pipeline (it also checks the bytes, which this server never sees)."""
    if body.language not in uploads.LANGUAGES:
        raise HTTPException(422, {"code": "BAD_LANGUAGE", "message": "Ngôn ngữ chỉ nhận vi, en hoặc auto"})
    origin = upload_origin(request)
    if request.headers.get("origin") not in (None, origin):  # a page that is not the console asking for a ticket
        raise HTTPException(403, {"code": "BAD_ORIGIN", "message": "Yêu cầu không đến từ trang của Cortex"})
    try:
        suffix = uploads.suffix_of(body.name)
        if body.size == 0:
            raise uploads.UploadRefused("EMPTY")
        if body.size > uploads.max_bytes():
            raise uploads.UploadRefused("TOO_LARGE")
    except uploads.UploadRefused as e:
        raise _refuse(e) from None
    tid = sess.caller.tenant_id
    async with tenant_session(tid) as s:
        sandbox = (await s.execute(select(m.Sandbox).where(m.Sandbox.purpose == "lesson_recap", m.Sandbox.status == "active")
                                   .order_by(m.Sandbox.created_at).limit(1))).scalar_one_or_none()
        if sandbox is None:
            raise HTTPException(409, {"code": "NO_SANDBOX", "message": "Chưa có sandbox Tổng kết buổi học đang chạy"})
        if not await live_skills_for(s, sandbox.id, "lesson.recorded"):
            raise HTTPException(409, {"code": "NO_SKILL", "message": "Sandbox chưa bật kỹ năng tổng kết buổi học"})
        mine = await my_classes(s, sess)
        classes = [c for c in (await s.execute(select(m.Class).where(
            m.Class.recap_sandbox_id == sandbox.id, m.Class.source_kind == "drive", m.Class.active.is_(True), m.Class.owned.is_(True),
            m.Class.drive_account_id.is_not(None)))).scalars() if mine is None or c.id in mine]
        chosen = next((c for c in classes if c.id == body.class_id), None) if body.class_id is not None else (classes[0] if len(classes) == 1 else None)
        if chosen is None:
            raise HTTPException(409 if not classes else 422, {"code": "NO_CLASS" if not classes else "BAD_CLASS",
                                                              "message": "Chưa có lớp nào để tải bản ghi lên. Chủ tạo lớp ở trang này" if not classes else "Hãy chọn lớp cho bản ghi"})
        since = datetime.now(UTC) - timedelta(days=1)
        started = m.AuditEvent.action == "lesson.upload_started"
        mine = (await s.execute(select(func.count()).select_from(m.AuditEvent).where(started, m.AuditEvent.at > since, m.AuditEvent.actor == sess.actor))).scalar_one()
        everyone = (await s.execute(select(func.count()).select_from(m.AuditEvent).where(started, m.AuditEvent.at > since))).scalar_one()
        settings = get_settings()
        if mine >= settings.UPLOAD_PER_USER_DAY or everyone >= settings.UPLOAD_PER_TENANT_DAY:
            raise HTTPException(429, {"code": "TOO_MANY", "message": "Hôm nay đã tải lên quá nhiều bản ghi, thử lại vào ngày mai"})
        try:
            secret = secret_of_account(chosen.drive_account, DriveError("UNAUTHENTICATED"))
        except DriveError as e:
            status, message = UPLOAD_REFUSALS[e.code]
            raise HTTPException(status, {"code": f"DRIVE_{e.code}", "message": message}) from None
        folder_id, class_name = chosen.source_ref, chosen.name
    label = uploads.clean_name(body.name)
    up = open_uploader(secret)
    try:
        folder_id = await up.ensure_folder(folder_id, class_name or FOLDER_NAME)  # still there; if someone deleted it, made again
        url = await up.start_session(label, uploads.MEDIA_TYPES.get(suffix, "application/octet-stream"), body.size, folder_id,
                                     {"cortex_language": body.language}, origin)
    except DriveError as e:
        status, message = UPLOAD_REFUSALS.get(e.code, (502, "Google không nhận tệp, hãy thử lại"))
        raise HTTPException(status, {"code": f"DRIVE_{e.code}", "message": message}) from None
    async with tenant_session(tid) as s:
        if folder_id != chosen.source_ref:  # the class's folder was gone: the new one is the class's now, its lessons stay with the class
            (await s.get(m.Class, chosen.id)).source_ref = folder_id
        await audit(sess, s, "config", "lesson.upload_started", f"Bắt đầu tải lên bản ghi «{label}» vào lớp «{class_name}»",
                    obj=("class", str(chosen.id), class_name or ""), metadata={"bytes": body.size, "language": body.language})
    return {"name": label, "upload_url": url, "chunk_bytes": CHUNK}


DRIVE_REFUSALS = {"UNAUTHENTICATED": (502, "Phiên Google để xem bản ghi đã hết hạn: cần đăng nhập lại"), "NOT_FOUND": (404, "Tệp không còn trong Drive"),
                  "PERMISSION_DENIED": (502, "Tài khoản đã nối không có quyền đọc tệp này"), "BAD_RANGE": (416, "Đoạn yêu cầu không hợp lệ"),
                  "RATE_LIMITED": (503, "Google đang giới hạn tốc độ, thử lại sau ít phút")}


@router.get("/lessons/{lesson_id}/media", response_model=None)
async def lesson_media(lesson_id: UUID, request: Request, sess: Session = need_class(Perm.LESSONS_READ)) -> StreamingResponse:
    """The recording, for the player (Range works, so it can seek), private to this business's signed-in people. It is streamed THROUGH Cortex
    from the Drive folder it sits in (the folder's service account) and is not kept: nothing here stores the recording."""
    async with tenant_session(sess.caller.tenant_id) as s:
        lesson = await s.get(m.Lesson, lesson_id)
        source = await s.get(m.Class, lesson.class_id) if lesson else None
    if lesson is None or source is None or source.source_kind != "drive":
        raise HTTPException(404, {"code": "NO_MEDIA", "message": "Không có bản ghi gốc của buổi này"})
    try:
        stream = await open_uploader(secret_of_account(source.drive_account, DriveError("UNAUTHENTICATED"))).open_stream(lesson.file_id, request.headers.get("range"))
    except DriveError as e:
        status, message = DRIVE_REFUSALS.get(e.code, (502, "Google không trả lời, hãy thử lại"))
        raise HTTPException(status, {"code": e.code, "message": message}) from None
    return StreamingResponse(stream.chunks(), status_code=stream.status, media_type=stream.media_type, headers={**stream.headers, "Cache-Control": "private, no-store"})


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(lesson_id: UUID, sess: Session = need_class(Perm.LESSONS_UPLOAD)) -> dict[str, Any]:
    """Removes a recording: it goes to the bin of the class's Drive folder and its transcript and recap are dropped here. Only in a folder Cortex made:
    in a folder the teacher already had, the file would be found again and summarised again, so that one is deleted in Drive."""
    async with tenant_session(sess.caller.tenant_id) as s:
        lesson = await s.get(m.Lesson, lesson_id)
        source = await s.get(m.Class, lesson.class_id) if lesson else None
        if lesson is None or source is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có buổi học này"})
        if not source.owned:
            raise HTTPException(409, {"code": "READ_ONLY", "message": "Thư mục này có sẵn và chỉ đọc: hãy xoá tệp ngay trong Drive"})
        if lesson.status == "working":
            raise HTTPException(409, {"code": "BUSY", "message": "Tệp đang được xử lý, thử lại sau ít phút"})
        try:
            await open_uploader(secret_of_account(source.drive_account, DriveError("UNAUTHENTICATED"))).trash_file(lesson.file_id)
        except DriveError as e:
            status, message = UPLOAD_REFUSALS.get(e.code, (502, "Google không xoá được tệp, hãy thử lại"))
            raise HTTPException(status, {"code": f"DRIVE_{e.code}", "message": message}) from None
        name = lesson.name
        await s.delete(lesson)
        await audit(sess, s, "config", "lesson.deleted", f"Xoá bản ghi «{name}» của lớp «{source.name}»", obj=("class", str(source.id), source.name))
    return {"deleted": str(lesson_id)}


@router.post("/lessons/{lesson_id}/release")
async def release_lesson(lesson_id: UUID, sess: Session = need_class(Perm.LESSONS_RELEASE)) -> dict[str, Any]:
    """A teacher has read the recap and lets it go out: to the class's Mezon channel now, and to its Classroom course on the next pass. Only for a
    recap that waits (a class set to `review`); once released it cannot be taken back, because it has been sent."""
    tid = sess.caller.tenant_id
    async with tenant_session(tid) as s:
        lesson = await s.get(m.Lesson, lesson_id, with_for_update=True)
        if lesson is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có buổi học này"})
        if lesson.status != "done" or lesson.recap is None:
            raise HTTPException(409, {"code": "NOT_READY", "message": "Buổi học này chưa có bản tổng kết"})
        if lesson.released_at is not None:
            raise HTTPException(409, {"code": "ALREADY_RELEASED", "message": "Bản tổng kết này đã được gửi đi rồi"})
        now = datetime.now(UTC)
        release(lesson, sess.actor, now)
        await notify.enqueue(s, tid, "lesson", lesson.id, now)
        await audit(sess, s, "config", "lesson.released", f"Duyệt và gửi tổng kết «{lesson.name}»", obj=("lesson", str(lesson.id), lesson.name))
    return {"released": str(lesson_id)}
