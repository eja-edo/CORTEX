"""Grading and assignments (WP33): what the grader suggested, and the two things a teacher can do with it, from the console. Every
decision is a person's, made here: approving is the only way a grade reaches Classroom. The student's work is served one item at a
time, to a signed-in person of this business (RLS), never in a list."""
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from cortex_leads.console.assistant import get_gateway
from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import audit
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.grader import assignments, job
from cortex_leads.grader.assignments import AssignmentOut
from cortex_leads.grader.guide import GuideError, guide_of
from cortex_leads.grader.writeback import DecisionRefused, decide
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.skills.registry import live_skills_for

router = APIRouter()
LIMIT = 100


def _client(cls: m.Class) -> Any:
    return job.open_source(cls)  # looked up at call time, so a test can stand a fake Classroom in its place
STATUS = {"pending": "Chờ giáo viên bấm chấm", "queued": "Đang chờ chấm", "working": "Đang chấm", "proposed": "Chờ giáo viên duyệt", "approved": "Đã duyệt",
          "rejected": "Đã bỏ", "skipped": "Bỏ qua", "failed": "Lỗi"}
WAITING = ("queued", "working")
REASONS = {"UNSUPPORTED_ATTACHMENT": "Bài nộp có tệp chưa đọc được (đọc được: Google Docs, văn bản, PDF có chữ, Word, âm thanh, video)", "EMPTY_SUBMISSION": "Bài nộp trống",
           "NO_GUIDE": "Bài tập chưa có thang điểm", "BAD_SHAPE": "AI trả lời sai khuôn, sẽ thử lại", "LLM_ERROR": "AI không trả lời được, sẽ thử lại",
           "READ_FAILED": "Không đọc được bài nộp từ Classroom", "SOURCE_UNAVAILABLE": "Không mở được khoá học",
           "PERMISSION_DENIED": "Google không cho phép thao tác này với tài khoản đã nối", "NOT_FOUND": "Không tìm thấy trên Classroom",
           "NO_TEXT_LAYER": "PDF là ảnh chụp hoặc bản scan, không có chữ để đọc (chưa hỗ trợ đọc chữ viết tay)",
           "TOO_LONG": "Bản ghi âm hoặc video dài quá 15 phút", "TOO_LARGE": "Tệp quá lớn để đọc",
           "NO_SPEECH": "Không nghe ra lời nói trong bản ghi", "FILE_UNREADABLE": "Không mở được tệp (hỏng hoặc có mật khẩu)"}
REFUSALS = {
    "NOT_FOUND": (404, "Không tìm thấy mục này"), "ALREADY_DECIDED": (409, "Mục này đã được quyết định rồi"),
    "BAD_SCORES": (422, "Điểm không hợp lệ: mỗi tiêu chí phải từ 0 đến điểm tối đa của nó"),
    "NOT_OURS": (409, "Bài tập này không do ứng dụng tạo nên Google không cho ghi điểm; hãy nhập tay trên Classroom"),
    "NO_GUIDE": (409, "Bài tập này chưa có thang điểm"), "BAD_DUE": (422, "Hạn nộp phải ở tương lai"),
    "PERMISSION_DENIED": (502, "Google không cho phép: tài khoản đã nối không đủ quyền hoặc bài không do ứng dụng tạo"),
    "UNAUTHENTICATED": (502, "Phiên kết nối Google của lớp này đã hết hạn hoặc bị thu hồi. Hãy vào Cài đặt → Kết nối Google, kết nối lại tài khoản rồi nối lại lớp"),
    "UPSTREAM": (502, "Google không trả lời, hãy thử lại sau ít phút"), "NOT_FOUND_COURSE": (404, "Không tìm thấy khoá học trên Classroom"),
    "BAD_SHAPE": (502, "AI soạn chưa đúng khuôn, hãy thử lại"), "LLM_ERROR": (503, "Chưa gọi được AI"),
}


def refuse(e: DecisionRefused) -> HTTPException:
    status, message = REFUSALS.get(e.code, (502, "Không thực hiện được trên Classroom"))
    return HTTPException(status, {"code": e.code, "message": message + (f": {e.detail}" if e.detail and status == 422 else "")})


async def _works(s: Any, items: list[m.GradeItem]) -> dict[Any, m.Assignment]:
    ids = {i.assignment_id for i in items}
    return {a.id: a for a in (await s.execute(select(m.Assignment).where(m.Assignment.id.in_(ids)))).scalars()} if ids else {}


def _row(i: m.GradeItem, a: m.Assignment) -> dict[str, Any]:
    p = i.proposal or {}
    f = i.final or {}
    return {"id": str(i.id), "class_id": str(a.class_id), "assignment_id": str(a.id), "work_title": a.title, "student": i.student_name or "Học sinh (chưa có tên)", "status": i.status,
            "status_label": STATUS[i.status], "ours": a.origin == "app", "max_points": float(a.max_points) if a.max_points is not None else None,
            "total": f.get("total", p.get("total")), "flags": p.get("flags", []), "problems": len(p.get("problems", [])),
            "reason": REASONS.get(i.error or "", i.error) if i.status in ("skipped", "failed") or i.error else None,
            "written": i.written_at is not None, "created_at": wire(i.created_at)}


@router.get("/grading")
async def list_grading(status: Literal["pending", "proposed", "approved", "rejected", "skipped", "failed", "waiting", "all"] = "proposed",
                       class_id: UUID | None = None, assignment_id: UUID | None = None,
                       sess: Session = need("grading.use")) -> dict[str, Any]:
    """`class_id` / `assignment_id` narrow the list and its counts to one class or one piece of work."""
    async with tenant_session(sess.caller.tenant_id) as s:
        scope = []
        if assignment_id is not None:
            scope.append(m.GradeItem.assignment_id == assignment_id)
        elif class_id is not None:
            scope.append(m.GradeItem.assignment_id.in_(select(m.Assignment.id).where(m.Assignment.class_id == class_id)))
        q = select(m.GradeItem).where(*scope).order_by(m.GradeItem.created_at.desc()).limit(LIMIT)
        if status == "waiting":
            q = q.where(m.GradeItem.status.in_(WAITING))
        elif status != "all":
            q = q.where(m.GradeItem.status == status)
        rows = list((await s.execute(q)).scalars())
        works = await _works(s, rows)
        items = [_row(i, works[i.assignment_id]) for i in rows]
        by = dict((await s.execute(select(m.GradeItem.status, func.count()).where(*scope).group_by(m.GradeItem.status))).all())
    counts = {k: by.get(k, 0) for k in ("pending", "proposed", "approved", "rejected", "skipped", "failed")} | {"waiting": sum(by.get(k, 0) for k in WAITING)}
    return {"items": items, "counts": counts, "limit": LIMIT}


@router.get("/grading/{item_id}")
async def get_grading(item_id: UUID, sess: Session = need("grading.use")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        item = await s.get(m.GradeItem, item_id)
        if item is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có bài nộp này"})
        work = await s.get(m.Assignment, item.assignment_id)
    try:
        guide: dict[str, Any] | None = guide_of(work).model_dump()
    except GuideError:
        guide = None
    return {**_row(item, work), "content": item.content, "content_kind": (item.content_kind or "").split(",") if item.content_kind else [], "guide": guide, "proposal": item.proposal, "final": item.final,
            "decided_by": item.decided_by, "decided_at": wire(item.decided_at)}


async def _queue_pending(s: Any, where: list[Any]) -> int:
    """`pending` (a class set to `manual` waits for a click) -> `queued`: the grader picks it up on its next pass."""
    got = await s.execute(update(m.GradeItem).where(*where, m.GradeItem.status == "pending").values(status="queued", error=None))
    return got.rowcount


@router.post("/grading/{item_id}/grade")
async def grade_one(item_id: UUID, sess: Session = need("grading.use")) -> dict[str, Any]:
    """Asks the AI to grade one submission that is waiting for that (a class in `manual` mode)."""
    async with tenant_session(sess.caller.tenant_id) as s:
        item = await s.get(m.GradeItem, item_id)
        if item is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có bài nộp này"})
        if await _queue_pending(s, [m.GradeItem.id == item_id]) == 0:
            raise HTTPException(409, {"code": "NOT_PENDING", "message": "Bài này không chờ bấm chấm"})
        await audit(sess, s, "config", "grade.requested", "Yêu cầu AI chấm một bài nộp", obj=("grade_item", str(item_id), ""))
    return {"queued": 1}


@router.post("/assignments/{assignment_id}/grade")
async def grade_all(assignment_id: UUID, sess: Session = need("grading.use")) -> dict[str, Any]:
    """Asks the AI to grade every submission of one piece of work that is waiting for that."""
    async with tenant_session(sess.caller.tenant_id) as s:
        work = await s.get(m.Assignment, assignment_id)
        if work is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có bài tập này"})
        n = await _queue_pending(s, [m.GradeItem.assignment_id == assignment_id])
        await audit(sess, s, "config", "grade.requested", f"Yêu cầu AI chấm {n} bài nộp của «{work.title}»", obj=("assignment", str(work.id), work.title),
                    metadata={"count": n})
    return {"queued": n}


class Decision(BaseModel):
    action: Literal["approve", "reject"]
    scores: dict[str, float] | None = None
    feedback: str | None = Field(default=None, max_length=1500)
    write: Literal["none", "draft", "return"] | None = None  # left out: the grade is returned to the student when Cortex made the work, else only kept here


@router.post("/grading/{item_id}/decision")
async def grading_decision(item_id: UUID, body: Decision, sess: Session = need("grading.use")) -> dict[str, Any]:
    write = body.write
    if write is None:
        async with tenant_session(sess.caller.tenant_id) as s:
            item = await s.get(m.GradeItem, item_id)
            work = await s.get(m.Assignment, item.assignment_id) if item is not None else None
        write = "return" if work is not None and work.origin == "app" else "none"
    try:
        out = await decide(sess.caller.tenant_id, item_id, action=body.action, by=sess.actor, scores=body.scores, feedback=body.feedback,
                           write=write, client_factory=_client)
    except DecisionRefused as e:
        raise refuse(e) from None
    async with tenant_session(sess.caller.tenant_id) as s:
        item = await s.get(m.GradeItem, item_id)
        title = (await s.get(m.Assignment, item.assignment_id)).title
        verb = "Duyệt" if body.action == "approve" else "Bỏ"
        await audit(sess, s, "config", f"grade.{body.action}", f"{verb} đề xuất điểm bài «{title}»" + (" và ghi lên Classroom" if out.get("written") else ""),
                    obj=("grade_item", str(item.id), title), metadata={"write": write, "total": out.get("total")})
    return out


# --- assignments ------------------------------------------------------------------------------
def _draft(d: m.Assignment, course: str | None = None) -> dict[str, Any]:
    return {"id": str(d.id), "class_id": str(d.class_id), "course": course, "title": d.title, "description": d.description, "max_points": d.max_points and float(d.max_points), "criteria": d.criteria,
            "answer_key": d.answer_key, "check_prompt": d.check_prompt, "language": d.language, "materials": d.materials, "origin": d.authored_by, "status": d.state, "due": wire(d.due_at), "publish": d.publish, "error": d.error,
            "created_by": d.created_by, "created_at": wire(d.created_at)}


async def _class_and_sandbox(s: Any, class_id: UUID) -> tuple[m.Class, m.Sandbox]:
    cls = await s.get(m.Class, class_id)
    if cls is None or not cls.active or cls.grader_sandbox_id is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có lớp này hoặc lớp chưa nối khoá học để chấm bài"})
    return cls, await s.get(m.Sandbox, cls.grader_sandbox_id)


@router.get("/assignments")
async def list_assignments(class_id: UUID | None = None, sess: Session = need("grading.use")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        classes = {x.id: x for x in (await s.execute(select(m.Class).where(m.Class.active.is_(True), m.Class.grader_sandbox_id.is_not(None)))).scalars()}
        sources = [{"id": str(x.id), "label": x.course_name or x.name} for x in classes.values()]
        items = [_draft(d, classes[d.class_id].name) for d in await assignments.drafts(s, class_id) if d.class_id in classes]  # a class that is switched off has no drafts to act on
    return {"items": items, "sources": sources}


@router.get("/classes/{class_id}/assignments")
async def class_assignments(class_id: UUID, sess: Session = need("grading.use")) -> dict[str, Any]:
    """Every piece of work of a class (Cortex's drafts and the ones a teacher made in Classroom) with where its submissions stand."""
    async with tenant_session(sess.caller.tenant_id) as s:
        cls = await s.get(m.Class, class_id)
        if cls is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có lớp này"})
        rows = list((await s.execute(select(m.Assignment).where(m.Assignment.class_id == class_id, m.Assignment.state.in_(("draft", "created")))
                                     .order_by(m.Assignment.created_at.desc()))).scalars())
        by: dict[Any, dict[str, int]] = {}
        for aid, st, n in (await s.execute(select(m.GradeItem.assignment_id, m.GradeItem.status, func.count()).where(
                m.GradeItem.assignment_id.in_([a.id for a in rows])).group_by(m.GradeItem.assignment_id, m.GradeItem.status))).all():
            by.setdefault(aid, {})[st] = n
    out = []
    for a in rows:
        c = by.get(a.id, {})
        out.append({"id": str(a.id), "title": a.title, "state": a.state, "ours": a.origin == "app", "gradable": bool(a.criteria and a.coursework_id),
                    "max_points": float(a.max_points) if a.max_points is not None else None, "due": wire(a.due_at), "created_at": wire(a.created_at),
                    "counts": {k: c.get(k, 0) for k in ("pending", "proposed", "approved", "rejected", "skipped", "failed")} | {"waiting": sum(c.get(k, 0) for k in WAITING)},
                    "submissions": sum(c.values()), "description": a.description, "criteria": a.criteria or [], "materials": a.materials or [],
                    "answer_key": a.answer_key, "check_prompt": a.check_prompt, "language": a.language})
    return {"class": {"id": str(cls.id), "name": cls.name, "grading_mode": cls.grading_mode}, "items": out}


class NewAssignment(BaseModel):
    class_id: UUID
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=10, max_length=6000)
    max_points: int = Field(ge=1, le=100)
    criteria: list[dict[str, Any]] = Field(min_length=1, max_length=12)
    answer_key: str | None = Field(default=None, max_length=8000)
    check_prompt: str | None = Field(default=None, max_length=4000)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    materials: list[assignments.MaterialIn] = Field(default_factory=list, max_length=assignments.MAX_MATERIALS)


@router.post("/assignments", status_code=201)
async def create_assignment(body: NewAssignment, sess: Session = need("grading.use")) -> dict[str, Any]:
    try:
        out = AssignmentOut(title=body.title, description=body.description, max_points=body.max_points, criteria=body.criteria,
                            answer_key=body.answer_key, language=body.language, check_prompt=body.check_prompt)
    except ValueError as e:
        raise HTTPException(422, {"code": "BAD_GUIDE", "message": f"Thang điểm chưa đúng: {e.errors()[0]['msg'] if hasattr(e, 'errors') else e}"}) from None
    try:
        materials = assignments.to_materials(body.materials)
    except ValueError as e:
        raise HTTPException(422, {"code": "BAD_MATERIAL", "message": f"Tệp đính kèm chưa đúng: {e}"}) from None
    async with tenant_session(sess.caller.tenant_id) as s:
        cls, sb = await _class_and_sandbox(s, body.class_id)
        d = assignments.add_draft(s, sb, cls, out, origin="teacher", by=sess.actor, now=datetime.now(UTC), materials=materials)
        await s.flush()
        await audit(sess, s, "config", "assignment.drafted", f"Soạn bài tập «{d.title}»", obj=("assignment", str(d.id), d.title))
        return _draft(d, cls.name)


class AiRequest(BaseModel):
    class_id: UUID
    topic: str = Field(min_length=3, max_length=500)
    level: str = Field(default="", max_length=80)
    minutes: int = Field(default=20, ge=5, le=180)


@router.post("/assignments/ai", status_code=201)
async def ai_assignment(body: AiRequest, sess: Session = need("grading.use"), gateway: LLMGateway = Depends(get_gateway)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        cls, sb = await _class_and_sandbox(s, body.class_id)
        skills = await live_skills_for(s, sb.id, "assignment.requested")
        if not skills:
            raise HTTPException(409, {"code": "NO_SKILL", "message": "Sandbox chưa bật kỹ năng soạn bài tập"})
        try:
            d = await assignments.ai_draft(s, sb, skills[0], cls, topic=body.topic, level=body.level or "chưa nêu", minutes=body.minutes,
                                           by=sess.actor, gateway=gateway, now=datetime.now(UTC))
        except DecisionRefused as e:
            raise refuse(e) from None
        await s.flush()
        await audit(sess, s, "config", "assignment.drafted", f"AI soạn bài tập «{d.title}»", obj=("assignment", str(d.id), d.title))
        return _draft(d, cls.name)


class AssignmentDecision(BaseModel):
    action: Literal["approve", "reject"]
    publish: bool = False
    due: datetime | None = None


@router.post("/assignments/{draft_id}/decision")
async def assignment_decision(draft_id: UUID, body: AssignmentDecision, sess: Session = need("grading.use")) -> dict[str, Any]:
    try:
        if body.action == "reject":
            await assignments.reject(sess.caller.tenant_id, draft_id, by=sess.actor)
            out: dict[str, Any] = {"status": "rejected"}
        else:
            out = await assignments.approve(sess.caller.tenant_id, draft_id, by=sess.actor, publish=body.publish, due=body.due, client_factory=_client)
    except DecisionRefused as e:
        raise refuse(e) from None
    async with tenant_session(sess.caller.tenant_id) as s:
        d = await s.get(m.Assignment, draft_id)
        text = f"Tạo bài tập «{d.title}» trên Classroom" if out["status"] == "created" else f"Bỏ bản nháp bài tập «{d.title}»"
        await audit(sess, s, "config", f"assignment.{out['status']}", text, obj=("assignment", str(d.id), d.title),
                    metadata={"publish": body.publish})
    return out
