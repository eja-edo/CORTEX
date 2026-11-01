"""WP33: the Classroom client against a Classroom that lives in memory (it keeps Google's rule about who may change grades)."""
from datetime import UTC, datetime

import httpx
import pytest

from cortex_leads.connectors.classroom import ClassroomClient, ClassroomError
from cortex_leads.grader.extract import extract
from dev.local.fake_classroom import FakeClassroom, demo


def no_speech():
    raise AssertionError("no recording here, so no speech model")


class Bearer:
    async def headers(self):
        return {"Authorization": "Bearer t"}


def client(fc: FakeClassroom) -> ClassroomClient:
    return ClassroomClient(httpx.AsyncClient(transport=fc.transport()), Bearer(), base="https://x/v1", drive_base="https://x/drive/v3")


async def test_it_lists_work_and_what_was_handed_in_with_the_student_work_as_text():
    fc = demo()
    c = client(fc)
    work = {w.title: w for w in await c.coursework("c1")}
    assert work["Viết 5 câu thì hiện tại hoàn thành"].ours and not work["Bài đọc tuần 5"].ours
    subs = await c.submissions("c1", work["Viết 5 câu thì hiện tại hoàn thành"].id)
    assert len(subs) == 3
    texts = {s.user_id: (await extract(c, s, no_speech)).text for s in subs}
    assert texts["u1"].startswith("I have lived in Hanoi") and texts["u3"] == "I have eaten breakfast. My brother has gone to school."
    assert await c.student_name("c1", "u2") == "Trần Bảo Châu"


async def test_only_handed_in_work_is_listed_by_default():
    fc = demo()
    w = fc.add_work("X", ours=True)
    fc.add_submission(w, "u1", answer="a", state="CREATED")
    fc.add_submission(w, "u2", answer="b", state="TURNED_IN")
    assert [s.user_id for s in await client(fc).submissions("c1", w)] == ["u2"]


async def test_a_grade_is_written_only_on_work_we_created():
    fc = demo()
    c = client(fc)
    ours, theirs = sorted(await c.coursework("c1"), key=lambda w: not w.ours)
    (mine, *_) = await c.submissions("c1", ours.id)
    await c.set_grade(ours, mine.id, 8.456, assign=True)
    assert fc.subs[mine.id]["draftGrade"] == 8.46 and fc.subs[mine.id]["assignedGrade"] == 8.46  # two decimals, as Google asks
    await c.return_submission(ours, mine.id)
    assert fc.subs[mine.id]["state"] == "RETURNED"
    (other,) = await c.submissions("c1", theirs.id)
    calls_before = len(fc.calls)
    with pytest.raises(ClassroomError) as e:
        await c.set_grade(theirs, other.id, 3, assign=False)
    assert e.value.code == "NOT_OURS" and len(fc.calls) == calls_before  # refused here: nothing was even sent to Google


async def test_google_refusing_a_grade_comes_back_as_a_code_not_a_crash():
    fc = demo()
    c = client(fc)
    ours = next(w for w in await c.coursework("c1") if w.ours)
    sub = (await c.submissions("c1", ours.id))[0]
    fc.work[ours.id]["associatedWithDeveloper"] = False  # the project that created it is not ours after all
    with pytest.raises(ClassroomError) as e:
        await c.set_grade(ours, sub.id, 5, assign=False)
    assert e.value.code == "PERMISSION_DENIED"


async def test_created_work_is_ours_and_carries_its_due_date_in_utc():
    fc = demo()
    c = client(fc)
    made = await c.create_coursework("c1", title="Bài mới", description="Mô tả", max_points=10, published=False,
                                     due=datetime(2026, 10, 30, 16, 59, tzinfo=UTC))
    assert made.ours and made.state == "DRAFT" and made.due == datetime(2026, 10, 30, 16, 59, tzinfo=UTC)
    assert fc.work[made.id]["dueDate"] == {"year": 2026, "month": 10, "day": 30}


async def test_attachments_go_to_classroom_with_the_course_work():
    fc = demo()
    c = client(fc)
    made = await c.create_coursework("c1", title="Có tệp", description="Mô tả", max_points=10, published=False, due=None, materials=[
        {"kind": "drive", "id": "f1", "title": "Phiếu", "share": "STUDENT_COPY"}, {"kind": "link", "url": "https://example.com/bai", "title": ""}])
    assert fc.work[made.id]["materials"] == [{"driveFile": {"driveFile": {"id": "f1"}, "shareMode": "STUDENT_COPY"}},
                                             {"link": {"url": "https://example.com/bai"}}]
    plain = await c.create_coursework("c1", title="Không tệp", description="Mô tả", max_points=10, published=False, due=None)
    assert "materials" not in fc.work[plain.id]


async def test_a_request_without_credentials_is_refused():
    fc = demo()

    class Nobody:
        async def headers(self):
            return {}

    c = ClassroomClient(httpx.AsyncClient(transport=fc.transport()), Nobody(), base="https://x/v1")
    with pytest.raises(ClassroomError) as e:
        await c.courses()
    assert e.value.code == "UNAUTHENTICATED"


async def test_google_refusing_the_stored_token_is_unauthenticated_and_no_answer_is_upstream():
    """An expired or revoked sign-in (7 days in Testing) came out as a crash and then as a vague message; now it names itself."""
    class Revoked:
        async def headers(self):
            raise httpx.HTTPStatusError("401", request=httpx.Request("POST", "https://x"), response=httpx.Response(401))

    class Down:
        async def headers(self):
            raise httpx.ConnectError("no network")

    for auth, code in ((Revoked(), "UNAUTHENTICATED"), (Down(), "UPSTREAM")):
        c = ClassroomClient(httpx.AsyncClient(transport=demo().transport()), auth, base="https://x/v1")
        with pytest.raises(ClassroomError) as e:
            await c.courses()
        assert e.value.code == code

    def broken(req):
        raise httpx.ReadTimeout("slow", request=req)

    c = ClassroomClient(httpx.AsyncClient(transport=httpx.MockTransport(broken)), Bearer(), base="https://x/v1")
    with pytest.raises(ClassroomError) as e:
        await c.courses()
    assert e.value.code == "UPSTREAM"


def test_a_grading_sign_in_never_asks_for_drive_write_and_a_drive_sign_in_asks_for_nothing_else():
    """Least privilege: the sign-in that reads student work cannot write to Drive, and the one that stores recordings cannot read anything else."""
    from cortex_leads.connectors.classroom import DRIVE_ONLY_SCOPES, SCOPES
    short = lambda scopes: sorted(x.rsplit("/", 1)[-1] for x in scopes)
    assert "drive.file" not in short(SCOPES) and "drive.readonly" in short(SCOPES)
    assert short(DRIVE_ONLY_SCOPES) == ["drive.file"]
