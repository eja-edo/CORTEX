"""The classroom_grader loop (WP33): find submissions handed in on course work that has a grading guide, suggest a grade for each,
tell the team how many wait. Short database turns around the slow part (Classroom and the model), as in the lesson loop, and the
same shared queue rules (`work/queue.py`). Opting a piece of work in is the guide: no guide, no grading, whatever was handed in. How far it goes by itself is the class's
`grading_mode`: manual (waits for a click), review (suggests, a person decides), auto_write (also writes the grade when `auto.auto_ok` says it is safe)."""
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.config import get_settings
from cortex_leads.connectors.classroom import (
    ClassroomClient,
    ClassroomError,
    open_classroom,
    valid_id,
)
from cortex_leads.connectors.google_accounts import secret_of_account
from cortex_leads.connectors.speech import Transcriber, open_transcriber
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import list_active_tenants, system_session, tenant_session
from cortex_leads.grader.auto import auto_ok
from cortex_leads.grader.extract import ExtractError, extract, extracted_from_row
from cortex_leads.grader.grade import GradeFailed, propose
from cortex_leads.grader.guide import Guide, GuideError, guide_of
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.notify import service as notify
from cortex_leads.sandbox.policy import check_budget
from cortex_leads.skills.registry import LoadedSkill, live_skills_for
from cortex_leads.work import queue

log = logging.getLogger(__name__)
PURPOSE = "classroom_grader"
EVENT = "submission.turned_in"
PER_PASS = 5  # submissions graded per pass and sandbox
SKIP = {"UNSUPPORTED_ATTACHMENT", "EMPTY_SUBMISSION", "NO_TEXT_LAYER", "TOO_LONG", "TOO_LARGE", "NO_SPEECH", "FILE_UNREADABLE"}  # a second try would change nothing: the teacher is told, no more tries
ClientFactory = Callable[[m.Class], ClassroomClient]


def open_source(cls: m.Class) -> ClassroomClient:
    return open_classroom(secret_of_account(cls.classroom_account, ClassroomError("UNAUTHENTICATED")))


@dataclass(frozen=True)
class Job:
    id: Any
    class_id: Any
    assignment_id: Any
    coursework_id: str
    submission_id: str
    student_name: str | None
    content: str | None  # kept from an earlier try
    content_kind: str | None
    language: str | None  # of a spoken answer, from the assignment's guide
    token: datetime


async def discover(session: AsyncSession, sandbox: m.Sandbox, cls: m.Class, client: ClassroomClient, now: datetime) -> int:
    """Queue what was handed in on course work that has a guide (an assignment with criteria). Idempotent on (sandbox, assignment, submission).
    In `manual` mode the submissions wait as `pending`: nothing is graded until a person asks."""
    if not valid_id(cls.course_id or ""):
        return 0
    guides = {a.coursework_id: a for a in (await session.execute(select(m.Assignment).where(
        m.Assignment.class_id == cls.id, m.Assignment.coursework_id.is_not(None), m.Assignment.criteria.is_not(None)))).scalars()}
    names: dict[str, str] = {}
    try:
        if name := await client.course_name(cls.course_id):
            (await session.get(m.Class, cls.id)).course_name = name  # as Classroom names it now; the team's message uses it
    except ClassroomError:
        pass  # the name is for the team's message; failing to read it must not stop the grading
    status = "pending" if cls.grading_mode == "manual" else "queued"
    n = 0
    for work in await client.coursework(cls.course_id):
        if work.id not in guides or not valid_id(work.id):
            continue
        guides[work.id].origin = "app" if work.ours else "classroom"  # Google knows which work this app made: a grade may be written only into that
        guides[work.id].title = work.title  # the title the team and the students see in Classroom
        for sub in await client.submissions(cls.course_id, work.id):
            if sub.user_id not in names:
                try:
                    names[sub.user_id] = await client.student_name(cls.course_id, sub.user_id)
                except ClassroomError:
                    names[sub.user_id] = ""  # the name is a convenience for the teacher; its absence is not a reason to skip the work
            got = await session.execute(insert(m.GradeItem).values(
                id=uuid7(), tenant_id=sandbox.tenant_id, sandbox_id=sandbox.id, assignment_id=guides[work.id].id, submission_id=sub.id,
                student_ref=sub.user_id, student_name=names[sub.user_id] or None, link=sub.link, status=status, created_at=now)
                .on_conflict_do_nothing().returning(m.GradeItem.id))
            n += got.scalar() is not None
    return n


async def claim(session: AsyncSession, sandbox: m.Sandbox, now: datetime) -> list[Job]:
    rows = await queue.claim(session, m.GradeItem, [m.GradeItem.sandbox_id == sandbox.id], now, limit=PER_PASS)
    works = {a.id: a for a in (await session.execute(select(m.Assignment).where(m.Assignment.id.in_({r.assignment_id for r in rows})))).scalars()}
    return [Job(r.id, works[r.assignment_id].class_id, r.assignment_id, works[r.assignment_id].coursework_id, r.submission_id, r.student_name,
                r.content, r.content_kind, works[r.assignment_id].language, now) for r in rows]


async def _end(tenant_id: Any, job: Job, now: datetime, *, code: str, skip: bool = False) -> None:
    async with tenant_session(tenant_id) as s:
        if (row := await queue.mine(s, m.GradeItem, job.id, job.token)) is None:
            return
        if skip:
            row.error, row.status, row.finished_at = code, "skipped", now
        else:
            queue.fail(row, code, now)


async def process(tenant_id: Any, sandbox_id: Any, job: Job, course_id: str, client: ClassroomClient, gateway: LLMGateway,
                  now: datetime, skill: LoadedSkill, transcriber: Callable[[], Transcriber] = open_transcriber) -> bool:
    """True when a suggestion was stored."""
    try:
        if job.content is not None:
            work = extracted_from_row(job.content, job.content_kind)
        else:
            work = await extract(client, await client.submission(course_id, job.coursework_id, job.submission_id), transcriber, job.language,
                                  allow_images=get_settings().GRADER_SEND_IMAGES)
    except (ClassroomError, ExtractError) as e:
        await _end(tenant_id, job, now, code=e.code, skip=e.code in SKIP)
        return False
    except Exception:
        log.exception("grade item %s: could not read the submission", job.id)
        await _end(tenant_id, job, now, code="READ_FAILED")
        return False
    async with tenant_session(tenant_id) as s:
        sandbox = await s.get(m.Sandbox, sandbox_id)
        row = await queue.mine(s, m.GradeItem, job.id, job.token)
        if row is None:
            log.warning("grade item %s was taken over by another worker: result dropped", job.id)
            return False
        row.content, row.content_kind = (None if work.images else work.text), ",".join(work.kinds)  # a photo is not kept: a retry reads it again
        assignment = await s.get(m.Assignment, row.assignment_id)
        try:
            guide: Guide | None = guide_of(assignment) if assignment else None
        except GuideError:
            guide = None
        if guide is None:
            row.error, row.status, row.finished_at = "NO_GUIDE", "skipped", now
            return False
        if await check_budget(s, sandbox, "tokens", now) or await check_budget(s, sandbox, "runs", now):
            queue.release(row)
            return False
        try:
            async with s.begin_nested():
                row.proposal = await propose(s, sandbox, skill, guide, work, row.student_name, gateway, now)
                if work.images:
                    row.content = row.proposal.get("transcript") or work.text  # what the model read, for the teacher to hold against the photo
        except GradeFailed as e:
            queue.fail(row, e.code, now)
            return False
        row.status, row.error, row.finished_at = "proposed", None, now
        cls = await s.get(m.Class, assignment.class_id)
        auto = cls.grading_mode == "auto_write" and auto_ok(row.proposal, assignment)
        if not auto:
            await notify.enqueue(s, tenant_id, "grading", row.id, now)
    if auto:
        await _auto_write(tenant_id, job, client, now)
    return True


async def _auto_write(tenant_id: Any, job: Job, client: ClassroomClient, now: datetime) -> None:
    """The class said `auto_write` and every check passed: the grade goes to the student as a teacher's approval would send it. If Google
    or the guide refuses, the item stays a suggestion and the team is told as for any other."""
    from cortex_leads.grader.writeback import (  # writeback imports this module's open_source
        DecisionRefused,
        decide,
    )
    try:
        await decide(tenant_id, job.id, action="approve", by="auto", write="return", client_factory=lambda _c: client, now=now)
    except DecisionRefused as e:
        log.warning("grade item %s: automatic write refused (%s)", job.id, e.code)
        async with tenant_session(tenant_id) as s:
            await notify.enqueue(s, tenant_id, "grading", job.id, now)


async def grader_once(now: datetime, gateway: LLMGateway, *, client_factory: ClientFactory = open_source,
                      transcriber: Callable[[], Transcriber] = open_transcriber) -> int:
    """Returns how many suggestions were made."""
    made = 0
    async with system_session() as sys_s:
        tenants = await list_active_tenants(sys_s)
    for tid in tenants:
        try:
            made += await _tenant_pass(tid, now, gateway, client_factory, transcriber)
        except Exception:
            log.exception("grader pass failed for a tenant")
    return made


async def _tenant_pass(tid: Any, now: datetime, gateway: LLMGateway, client_factory: ClientFactory, transcriber: Callable[[], Transcriber]) -> int:
    made = 0
    async with tenant_session(tid) as s:
        sandboxes = list((await s.execute(select(m.Sandbox).where(m.Sandbox.status == "active", m.Sandbox.purpose == PURPOSE))).scalars())
        sources = list((await s.execute(select(m.Class).where(m.Class.active.is_(True), m.Class.grader_sandbox_id.is_not(None)))).scalars())
    for sb in sandboxes:
        async with tenant_session(tid) as s:
            skills = [k for k in await live_skills_for(s, sb.id, EVENT)]
        if not skills:
            log.warning("sandbox %s has no live skill for %s: nothing to do", sb.id, EVENT)
            continue
        clients: dict[Any, ClassroomClient] = {}
        by_id = {x.id: x for x in sources if x.grader_sandbox_id == sb.id}
        for src in by_id.values():
            try:
                clients[src.id] = client_factory(src)
                async with tenant_session(tid) as s:
                    await discover(s, sb, src, clients[src.id], now)
            except Exception:
                log.exception("class %s: could not list", src.id)
        async with tenant_session(tid) as s:
            jobs = await claim(s, sb, now)
        for job in jobs:
            client = clients.get(job.class_id)
            if client is None:
                await _end(tid, job, now, code="SOURCE_UNAVAILABLE")
                continue
            made += await process(tid, sb.id, job, by_id[job.class_id].course_id, client, gateway, now, skills[0], transcriber)
    return made
