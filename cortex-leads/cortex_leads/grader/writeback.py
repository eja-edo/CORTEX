"""The only code that changes anything in Google Classroom (WP33), and only after a person decided. A teacher's approval reaches
`decide`; nothing the model said reaches Google without passing through it. The rules, each tested:
- the marks written are the teacher's, checked against the guide (0 to each criterion's points), not the model's;
- a grade is written only for course work this app created (Google refuses the rest; we do not even ask);
- an item is decided once: a second click finds it already decided;
- if Google refuses, the item stays as it was (a suggestion waiting for a teacher), and the reason comes back as a code."""
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from cortex_leads.audit.service import record
from cortex_leads.connectors.classroom import ClassroomClient, ClassroomError, CourseWork
from cortex_leads.core.errors import CortexError
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.grader.guide import GuideError, guide_of
from cortex_leads.grader.job import open_source
from cortex_leads.grader.validator import check_scores

Write = Literal["none", "draft", "return"]
ClientFactory = Callable[[m.Class], ClassroomClient]


class DecisionRefused(CortexError):
    """`.code`: NOT_FOUND | ALREADY_DECIDED | BAD_SCORES | NOT_OURS | NO_GUIDE | or a Classroom code (PERMISSION_DENIED, …)"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code, self.detail = code, detail


async def decide(tenant_id: UUID, item_id: UUID, *, action: Literal["approve", "reject"], by: str, scores: dict[str, float] | None = None,
                 feedback: str | None = None, write: Write = "none", client_factory: ClientFactory = open_source,
                 now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    async with tenant_session(tenant_id) as s:
        item = await s.get(m.GradeItem, item_id, with_for_update=True)
        if item is None:
            raise DecisionRefused("NOT_FOUND")
        if item.status != "proposed":
            raise DecisionRefused("ALREADY_DECIDED")
        if action == "reject":
            item.status, item.decided_by, item.decided_at = "rejected", by, now
            return {"status": "rejected"}
        assignment = await s.get(m.Assignment, item.assignment_id)
        try:
            guide = guide_of(assignment)
        except GuideError:
            raise DecisionRefused("NO_GUIDE") from None
        try:
            marks = check_scores(scores if scores is not None else {r["id"]: r["score"] for r in item.proposal["criteria"]}, guide)
        except ValueError as e:
            raise DecisionRefused("BAD_SCORES", str(e)) from None
        if write != "none" and assignment.origin != "app":
            raise DecisionRefused("NOT_OURS", "Bài tập này không do ứng dụng tạo nên Google không cho ghi điểm; hãy nhập tay trên Classroom.")
        total = round(sum(marks.values()), 2)
        item.final = {"scores": marks, "total": total, "max_points": float(guide.max_points), "write": write,
                      "feedback": (feedback if feedback is not None else item.proposal["feedback"]).strip()}
        item.status, item.decided_by, item.decided_at, item.write_mode = "approved", by, now, write  # decided before Google is called: a second click is refused
        cls = await s.get(m.Class, assignment.class_id)
        work = CourseWork(assignment.coursework_id, cls.course_id, assignment.title, "", float(guide.max_points), "PUBLISHED", None, True)
        if by == "auto":
            await record(s, tenant_id, actor="system:grader-auto", role="system", category="grading", action="grade.auto_written",
                         summary=f"Tự ghi điểm bài «{assignment.title}» (lớp «{cls.name}»)", obj=("grade_item", str(item.id), assignment.title),
                         metadata={"total": total, "write": write})
        sub_id = item.submission_id
        client = client_factory(cls) if write != "none" else None
    if client is None:
        return {"status": "approved", "total": total, "written": False}
    error = None
    try:
        await client.set_grade(work, sub_id, total, assign=write == "return")
        if write == "return":
            try:
                await client.return_submission(work, sub_id)
            except ClassroomError as e:
                error = f"RETURN_{e.code}"
    except ClassroomError as e:
        async with tenant_session(tenant_id) as s:  # Google said no: the item is a suggestion again, as if nothing had been clicked
            item = await s.get(m.GradeItem, item_id, with_for_update=True)
            item.status, item.final, item.decided_by, item.decided_at, item.write_mode, item.error = "proposed", None, None, None, None, e.code
        raise DecisionRefused(e.code) from None
    async with tenant_session(tenant_id) as s:
        item = await s.get(m.GradeItem, item_id, with_for_update=True)
        item.written_at, item.error = now, error
    return {"status": "approved", "total": total, "written": True, "returned": write == "return" and error is None, "error": error}
