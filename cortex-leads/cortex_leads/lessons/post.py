"""A lesson recap posted to the class's Google Classroom course (the main place a recap goes; a Mezon webhook is the optional extra).
Runs after the recap is made. Only a released recap is posted (a person's click for recap_mode review, at once for auto), and it is posted published:
the teacher's look at what the AI wrote (Luật AI Điều 11) is the release itself. One announcement per lesson: `classroom_post_id`
is set once and never posted again. A failure is a short code and is tried again, up to MAX_TRIES times, never as the exception's text."""
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from cortex_leads.connectors.classroom import (
    ClassroomClient,
    ClassroomError,
    open_classroom,
    valid_id,
)
from cortex_leads.connectors.google_accounts import account_secret
from cortex_leads.db import models as m
from cortex_leads.db.session import list_active_tenants, system_session, tenant_session
from cortex_leads.lessons.recap import render_recap, video_url

log = logging.getLogger(__name__)
MAX_TRIES = 3
PER_PASS = 20
Opener = Any  # (secret: bytes) -> ClassroomClient; a test stands a fake Google in its place


def announcement_text(lesson: m.Lesson, src: m.Class) -> str:
    return render_recap(lesson.name, lesson.recap or {}, video_url(src.source_kind or "", lesson.file_id), class_name=src.name)


async def post_once(now: datetime, *, opener: Opener = open_classroom) -> int:
    """Returns how many recaps were posted."""
    async with system_session() as sys_s:
        tenants = await list_active_tenants(sys_s)
    posted = 0
    for tid in tenants:
        try:
            posted += await _tenant_pass(tid, now, opener)
        except Exception:
            log.exception("classroom post pass failed for a tenant")
    return posted


async def _tenant_pass(tid, now: datetime, opener: Opener) -> int:
    done = 0
    async with tenant_session(tid) as s:
        todo = list((await s.execute(
            select(m.Lesson.id).join(m.Class, m.Class.id == m.Lesson.class_id).where(
                m.Lesson.status == "done", m.Lesson.recap.is_not(None), m.Lesson.released_at.is_not(None), m.Lesson.classroom_post_id.is_(None),
                m.Lesson.classroom_attempts < MAX_TRIES, m.Class.active.is_(True), m.Class.course_id.is_not(None))
            .order_by(m.Lesson.finished_at).limit(PER_PASS))).scalars())
    for lesson_id in todo:
        async with tenant_session(tid) as s:
            lesson = await s.get(m.Lesson, lesson_id, with_for_update=True)
            if lesson is None or lesson.classroom_post_id is not None or lesson.classroom_attempts >= MAX_TRIES:
                continue
            src = await s.get(m.Class, lesson.class_id)
            lesson.classroom_attempts += 1
            try:
                if not valid_id(src.course_id or ""):
                    raise ClassroomError("INVALID_ARGUMENT")
                who = await s.get(m.GoogleAccount, src.classroom_account_id) if src.classroom_account_id else None
                if who is None or who.status != "active":
                    raise ClassroomError("UNAUTHENTICATED")
                client: ClassroomClient = opener(account_secret(who))
                lesson.classroom_post_id = await client.create_announcement(src.course_id, text=announcement_text(lesson, src),
                                                                            published=True)  # a person released it (review) or the class said auto: the draft step is the release
                lesson.classroom_error = None
                done += 1
            except ClassroomError as e:
                lesson.classroom_error = e.code
            except Exception as e:  # a down network costs this lesson a try, not the pass
                log.exception("lesson %s: could not post to Classroom", lesson.id)
                lesson.classroom_error = f"POST_{type(e).__name__}"[:80]
    return done
