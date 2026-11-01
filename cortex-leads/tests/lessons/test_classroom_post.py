"""A lesson recap is posted to the class's Classroom course: only once released (by the class's `auto` mode or a person), once, and a failure is
tried again a few times and then reported as a code. Google is a fake; the database (RLS included) is real."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from cortex_leads.connectors.classroom import ClassroomError
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.lessons import post

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
RECAP = {"summary": "Lớp học câu hỏi với Who.", "topics": ["Who"], "homework": [], "class_notes": "",
         "sections": [{"title": "Câu hỏi với Who", "points": ["Who + to be + danh từ. Ví dụ: Who is your teacher?"]}]}


class FakeClassroom:
    def __init__(self, fail: str | None = None) -> None:
        self.posts, self.fail = [], fail

    async def create_announcement(self, course_id, *, text, published):
        if self.fail:
            raise ClassroomError(self.fail)
        self.posts.append((course_id, text, published))
        return f"ann{len(self.posts)}"


@pytest.fixture
async def lab(tenant_factory, sandbox_factory, seed, monkeypatch):
    t = await tenant_factory()
    sb = await sandbox_factory(t, name="lesson_recap", purpose="lesson_recap", profile_ref="lesson_recapper@1", domain_pack={})
    monkeypatch.setattr(post, "account_secret", lambda who: b"{}")

    async def make(course="123", released=True, active=True, recap=RECAP, status="done"):
        who = await seed(m.GoogleAccount(tenant_id=t.id, label="cô Lan", scopes=["classroom.announcements"], connected_by="x", secret_enc=b"x"))
        src = await seed(m.Class(tenant_id=t.id, recap_sandbox_id=sb.id, source_kind="drive", source_ref="folder1", name="Lớp A1", active=active, classroom_account_id=who.id, course_id=course, course_name="IELTS A1", recap_mode="auto"))
        return src, await seed(m.Lesson(tenant_id=t.id, sandbox_id=sb.id, class_id=src.id, file_id="f1", name="buổi 1.mp4", status=status,
                                        recap=recap, finished_at=NOW - timedelta(minutes=5), released_at=NOW if released else None))
    return t, make


async def lesson_of(t):
    async with tenant_session(t.id) as s:
        return (await s.execute(select(m.Lesson))).scalar_one()


async def test_a_recap_is_posted_once_with_every_section(lab):
    t, make = lab
    await make()
    fake = FakeClassroom()
    assert await post.post_once(NOW, opener=lambda secret: fake) == 1
    assert await post.post_once(NOW, opener=lambda secret: fake) == 0  # never twice
    ((course, text, published),) = fake.posts
    assert course == "123" and published is True
    assert "1. Câu hỏi với Who" in text and "Who is your teacher?" in text
    assert (await lesson_of(t)).classroom_post_id == "ann1"


async def test_a_recap_nobody_has_released_is_not_posted_until_someone_does(lab):
    t, make = lab
    _, lesson = await make(released=False)
    fake = FakeClassroom()
    assert await post.post_once(NOW, opener=lambda secret: fake) == 0 and not fake.posts
    async with tenant_session(t.id) as s:
        (await s.get(m.Lesson, lesson.id)).released_at = NOW
    assert await post.post_once(NOW, opener=lambda secret: fake) == 1 and fake.posts[0][2] is True


@pytest.mark.parametrize("kwargs", [{"course": None}, {"active": False}, {"status": "failed", "recap": None}])
async def test_nothing_is_posted_without_a_course_an_active_class_or_a_recap(lab, kwargs):
    t, make = lab
    await make(**kwargs)
    fake = FakeClassroom()
    assert await post.post_once(NOW, opener=lambda secret: fake) == 0 and not fake.posts


async def test_a_refusal_is_a_code_and_stops_after_three_tries(lab):
    t, make = lab
    await make()
    fake = FakeClassroom(fail="PERMISSION_DENIED")
    for _ in range(5):
        await post.post_once(NOW, opener=lambda secret: fake)
    lesson = await lesson_of(t)
    assert (lesson.classroom_post_id, lesson.classroom_error, lesson.classroom_attempts) == (None, "PERMISSION_DENIED", post.MAX_TRIES)
