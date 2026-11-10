"""WP33: the console's grading and assignment screens. Decisions are a person's; the work of a student is served one item at a time."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from cryptography.fernet import Fernet
from support import h, sign_in

from cortex_leads.config import get_settings
from cortex_leads.connectors.classroom import ClassroomClient
from cortex_leads.console.assistant import get_gateway
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.grader import job
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.llm.providers import FakeProvider
from cortex_leads.llm.types import LLMResult
from cortex_leads.skills.loader import sync_dir
from cortex_leads.skills.profile import SANDBOXES_DIR
from cortex_leads.skills.registry import promote
from dev.local.fake_classroom import demo

CRIT = [{"id": "dung_thi", "label": "Dùng đúng thì", "points": 6, "descriptor": ""}, {"id": "du_so_cau", "label": "Đủ 5 câu", "points": 4, "descriptor": ""}]
PROPOSAL = {"criteria": [{"id": "dung_thi", "label": "Dùng đúng thì", "points": 6, "score": 5, "proposed": 5, "quote": "She has finished", "comment": "", "verified": True},
                         {"id": "du_so_cau", "label": "Đủ 5 câu", "points": 4, "score": 4, "proposed": 4, "quote": "We have never", "comment": "", "verified": True}],
            "total": 9, "max_points": 10, "feedback": "Em làm tốt.", "concerns": [], "problems": ["Một lưu ý"], "flags": []}


class Bearer:
    async def headers(self):
        return {"Authorization": "Bearer t"}


async def as_(app_client, world, api_key_factory, role):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


@pytest.fixture
async def gradebook(world, seed, monkeypatch):
    fc = demo()
    ours = next(w for w in fc.work.values() if w["associatedWithDeveloper"])["id"]
    manual = next(w for w in fc.work.values() if not w["associatedWithDeveloper"])["id"]
    sb = await seed(m.Sandbox(tenant_id=world.t.id, name="classroom_grader", purpose="classroom_grader", profile_ref="classroom_grader@1"))
    src = await seed(m.Class(tenant_id=world.t.id, name="Tiếng Anh A1", grader_sandbox_id=sb.id, course_id="c1", auth_kind="delegated",
                             classroom_secret_enc=Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(b"{}")))
    works = {}
    for cw, origin, title in ((ours, "app", "Viết 5 câu"), (manual, "classroom", "Bài đọc")):
        works[cw] = await seed(m.Assignment(tenant_id=world.t.id, class_id=src.id, coursework_id=cw, origin=origin, state="created", title=title, max_points=10,
                                            criteria=CRIT, answer_key="have/has + V3"))
    sub = next(k for k, v in fc.subs.items() if v["_work"] == ours)
    mine = await seed(m.GradeItem(tenant_id=world.t.id, sandbox_id=sb.id, assignment_id=works[ours].id, submission_id=sub, student_ref="u1",
                                  student_name="Nguyễn Minh An", status="proposed",
                                  content="She has finished her homework. We have never been to Paris.", proposal=PROPOSAL))
    sub2 = next(k for k, v in fc.subs.items() if v["_work"] == manual)
    theirs = await seed(m.GradeItem(tenant_id=world.t.id, sandbox_id=sb.id, assignment_id=works[manual].id, submission_id=sub2, student_ref="u1",
                                    student_name="Nguyễn Minh An", status="proposed",
                                    content="A boy has a dog.", proposal=PROPOSAL))
    monkeypatch.setattr(job, "open_source", lambda s: ClassroomClient(httpx.AsyncClient(transport=fc.transport()), Bearer(), base="https://x/v1",
                                                                       drive_base="https://x/drive/v3"))
    return fc, sb, src, mine, theirs


async def test_the_list_counts_by_status_and_never_carries_the_work(app_client, world, api_key_factory, gradebook):
    await as_(app_client, world, api_key_factory, "owner")  # a teacher, not only the owner
    r = (await app_client.get("/api/v1/grading")).json()
    assert r["counts"]["proposed"] == 2 and len(r["items"]) == 2
    first = next(x for x in r["items"] if x["work_title"] == "Viết 5 câu")
    assert first["student"] == "Nguyễn Minh An" and first["total"] == 9 and first["ours"] is True and first["problems"] == 1
    assert "She has finished" not in json.dumps(r)


async def test_one_item_shows_the_work_the_guide_and_the_suggestion(app_client, world, api_key_factory, gradebook):
    _, _, _, mine, _ = gradebook
    await as_(app_client, world, api_key_factory, "owner")
    d = (await app_client.get(f"/api/v1/grading/{mine.id}")).json()
    assert d["content"].startswith("She has finished") and d["guide"]["answer_key"] == "have/has + V3" and d["proposal"]["total"] == 9


async def test_approving_with_the_teachers_own_marks_writes_a_draft_grade(app_client, world, api_key_factory, gradebook):
    fc, _, _, mine, _ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post(f"/api/v1/grading/{mine.id}/decision", headers=h(csrf), json={
        "action": "approve", "scores": {"dung_thi": 4, "du_so_cau": 4}, "write": "draft"})
    assert r.status_code == 200 and r.json()["total"] == 8 and r.json()["written"] is True
    assert fc.subs[mine.submission_id]["draftGrade"] == 8
    again = await app_client.post(f"/api/v1/grading/{mine.id}/decision", headers=h(csrf), json={"action": "reject"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "ALREADY_DECIDED"


async def test_marks_outside_the_guide_and_writes_to_work_we_did_not_make_are_refused_in_plain_words(app_client, world, api_key_factory, gradebook):
    fc, _, _, mine, theirs = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    bad = await app_client.post(f"/api/v1/grading/{mine.id}/decision", headers=h(csrf), json={"action": "approve", "scores": {"dung_thi": 9, "du_so_cau": 1}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "BAD_SCORES" and "từ 0 đến điểm tối đa" in bad.json()["detail"]["message"]
    no = await app_client.post(f"/api/v1/grading/{theirs.id}/decision", headers=h(csrf), json={"action": "approve", "write": "draft"})
    assert no.status_code == 409 and no.json()["detail"]["code"] == "NOT_OURS" and "nhập tay" in no.json()["detail"]["message"]
    assert "draftGrade" not in fc.subs[theirs.submission_id]
    ok = await app_client.post(f"/api/v1/grading/{theirs.id}/decision", headers=h(csrf), json={"action": "approve", "write": "none"})
    assert ok.status_code == 200 and ok.json()["written"] is False


async def test_a_decision_is_in_the_activity_log(app_client, world, api_key_factory, gradebook):
    _, _, _, mine, _ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    await app_client.post(f"/api/v1/grading/{mine.id}/decision", headers=h(csrf), json={"action": "reject"})
    log = (await app_client.get("/api/v1/audit")).json()
    assert any("đề xuất điểm" in str(e) for e in log["items"])


async def test_another_business_sees_nothing_of_this_one(app_client, world, api_key_factory, gradebook, tenant_factory):
    _, _, _, mine, _ = gradebook
    other = await tenant_factory("Khác")
    _, key = await api_key_factory(other, "owner", None)
    app_client.cookies.clear()
    await sign_in(app_client, key)
    assert (await app_client.get("/api/v1/grading")).json()["items"] == []
    assert (await app_client.get(f"/api/v1/grading/{mine.id}")).status_code == 404


DRAFT = {"title": "Viết 5 câu về em", "description": "Viết 5 câu về bản thân, dùng thì hiện tại hoàn thành, nộp trên Classroom.", "max_points": 10,
         "criteria": CRIT, "answer_key": None}


async def test_a_teacher_drafts_an_assignment_and_approving_creates_it_with_its_guide(app_client, world, api_key_factory, gradebook):
    fc, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    before = len(fc.work)
    r = await app_client.post("/api/v1/assignments", headers=h(csrf), json={**DRAFT, "class_id": str(src.id)})
    assert r.status_code == 201 and r.json()["status"] == "draft" and len(fc.work) == before  # nothing in Classroom yet
    listing = (await app_client.get("/api/v1/assignments")).json()
    assert listing["sources"] == [{"id": str(src.id), "label": "Tiếng Anh A1"}] and listing["items"][0]["origin"] == "teacher"
    due = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    ok = await app_client.post(f"/api/v1/assignments/{r.json()['id']}/decision", headers=h(csrf), json={"action": "approve", "publish": True, "due": due})
    assert ok.status_code == 200 and ok.json()["status"] == "created" and len(fc.work) == before + 1
    assert fc.work[ok.json()["coursework_id"]]["state"] == "PUBLISHED"


async def test_files_attached_to_a_draft_reach_classroom_when_it_is_approved(app_client, world, api_key_factory, gradebook):
    fc, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post("/api/v1/assignments", headers=h(csrf), json={**DRAFT, "class_id": str(src.id), "materials": [
        {"url": "https://drive.google.com/file/d/f77/view", "share": "STUDENT_COPY"}, {"url": "https://example.com/doc", "title": "Tài liệu"}]})
    assert r.status_code == 201 and [x["kind"] for x in r.json()["materials"]] == ["drive", "link"]
    ok = await app_client.post(f"/api/v1/assignments/{r.json()['id']}/decision", headers=h(csrf), json={"action": "approve", "publish": True})
    assert fc.work[ok.json()["coursework_id"]]["materials"][0] == {"driveFile": {"driveFile": {"id": "f77"}, "shareMode": "STUDENT_COPY"}}


async def test_an_attachment_that_is_not_a_web_address_is_refused_before_a_draft_exists(app_client, world, api_key_factory, gradebook):
    _, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post("/api/v1/assignments", headers=h(csrf), json={**DRAFT, "class_id": str(src.id), "materials": [{"url": "javascript:alert(1)"}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_MATERIAL"
    assert (await app_client.get("/api/v1/assignments")).json()["items"] == []


async def test_points_that_do_not_add_up_are_refused_before_a_draft_exists(app_client, world, api_key_factory, gradebook):
    _, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post("/api/v1/assignments", headers=h(csrf), json={**DRAFT, "max_points": 20, "class_id": str(src.id)})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_GUIDE"


async def test_the_ai_drafts_for_a_teacher_through_the_skill(app_client, world, api_key_factory, gradebook):
    _, sb, src, *_ = gradebook
    async with tenant_session(world.t.id) as s:
        for row in await sync_dir(s, world.t.id, sb.id, SANDBOXES_DIR / "classroom_grader" / "skills"):
            await promote(s, sb.id, row.name, row.version, "shadow")
            await promote(s, sb.id, row.name, row.version, "live")
    gateway = LLMGateway(FakeProvider([LLMResult(content=json.dumps(DRAFT, ensure_ascii=False), tokens_in=10, tokens_out=10, model="f")]))
    app_client._transport.app.dependency_overrides[get_gateway] = lambda: gateway
    try:
        csrf = await as_(app_client, world, api_key_factory, "owner")
        r = await app_client.post("/api/v1/assignments/ai", headers=h(csrf), json={"class_id": str(src.id), "topic": "thì hiện tại hoàn thành", "minutes": 20})
    finally:
        app_client._transport.app.dependency_overrides.clear()
    assert r.status_code == 201 and r.json()["origin"] == "ai" and r.json()["status"] == "draft"


async def test_the_sandbox_pages_show_the_course_and_how_many_submissions_are_waiting(app_client, world, api_key_factory, gradebook, seed):
    _, sb, src, mine, _ = gradebook
    await seed(m.NotifyTarget(tenant_id=world.t.id, kind="mezon", address="https://webhook.mezon.ai/webhooks/1/SECRET-TOKEN", label="Mezon của đội"))
    await as_(app_client, world, api_key_factory, "owner")
    d = (await app_client.get(f"/api/v1/sandboxes/{sb.id}")).json()
    assert d["facing"] == {"customer": False, "tools": False}
    (feed,) = d["feeds"]
    assert (feed["kind"], feed["label"], feed["where"], feed["unit"]) == ("classroom", "Khoá học Google Classroom", "Tiếng Anh A1", "bài nộp")
    assert feed["lessons"] == {"done": 0, "failed": 0, "waiting": 2}  # both submissions wait for a teacher
    assert "SECRET-TOKEN" not in str(d)
    mine_row = next(x for x in (await app_client.get("/api/v1/sandboxes")).json()["items"] if x["id"] == str(sb.id))
    assert mine_row["flow"] == "1 khoá học Classroom → 1 kênh Mezon"


async def test_a_sandbox_shows_the_channel_bound_to_it_and_not_the_general_one(app_client, world, api_key_factory, gradebook, seed):
    _, sb, *_ = gradebook
    await seed(m.NotifyTarget(tenant_id=world.t.id, kind="mezon", address="https://webhook.mezon.ai/webhooks/1/GENERAL-TOKEN", label="Kênh chung"))
    await seed(m.NotifyTarget(tenant_id=world.t.id, kind="mezon", address="https://webhook.mezon.ai/webhooks/2/GRADING-TOKEN", label="Kênh chấm bài",
                              sandbox_id=sb.id))
    await as_(app_client, world, api_key_factory, "owner")
    d = (await app_client.get(f"/api/v1/sandboxes/{sb.id}")).json()
    assert [p["label"] for p in d["pushes"]] == ["Kênh chấm bài"] and "TOKEN" not in str(d)


async def test_an_expired_google_sign_in_is_said_in_words_and_the_draft_stays_a_draft(app_client, world, api_key_factory, gradebook, monkeypatch):
    _, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    made = await app_client.post("/api/v1/assignments", headers=h(csrf), json={**DRAFT, "class_id": str(src.id)})

    class Revoked:
        async def headers(self):
            raise httpx.HTTPStatusError("401", request=httpx.Request("POST", "https://x"), response=httpx.Response(401))

    monkeypatch.setattr(job, "open_source", lambda s: ClassroomClient(httpx.AsyncClient(), Revoked(), base="https://x/v1"))
    r = await app_client.post(f"/api/v1/assignments/{made.json()['id']}/decision", headers=h(csrf), json={"action": "approve", "publish": True})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "UNAUTHENTICATED" and "Kết nối Google" in r.json()["detail"]["message"]
    listing = (await app_client.get("/api/v1/assignments")).json()["items"]
    assert listing[0]["status"] == "draft" and listing[0]["error"] == "UNAUTHENTICATED" and listing[0]["course"] == "Tiếng Anh A1"


async def test_drafts_of_a_course_that_was_switched_off_are_not_offered(app_client, world, api_key_factory, gradebook, seed, sandbox_factory):
    _, sb, src, *_ = gradebook
    from sqlalchemy import update
    await seed(m.Assignment(tenant_id=world.t.id, class_id=src.id, origin="app", authored_by="teacher", title="Cũ", description="Bài của lớp đã tắt rồi.",
                            max_points=10, criteria=CRIT))
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Class).values(active=False))
    await as_(app_client, world, api_key_factory, "owner")
    assert (await app_client.get("/api/v1/assignments")).json()["items"] == []


async def test_approving_without_saying_where_to_write_returns_the_grade_only_for_work_we_made(app_client, world, api_key_factory, gradebook):
    fc, _, _, mine, theirs = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    ok = await app_client.post(f"/api/v1/grading/{mine.id}/decision", headers=h(csrf), json={"action": "approve"})
    assert ok.status_code == 200 and ok.json()["written"] is True and ok.json()["returned"] is True
    assert fc.subs[mine.submission_id]["state"] == "RETURNED"
    typed = await app_client.post(f"/api/v1/grading/{theirs.id}/decision", headers=h(csrf), json={"action": "approve"})
    assert typed.status_code == 200 and typed.json()["written"] is False  # not ours: Google would refuse, so it is kept here for the teacher to type in


async def test_a_class_in_manual_mode_lists_its_waiting_submissions_and_a_click_sends_them_to_the_ai(app_client, world, api_key_factory, gradebook, seed):
    _, sb, src, mine, _ = gradebook
    work = await seed(m.Assignment(tenant_id=world.t.id, class_id=src.id, coursework_id="w9", origin="app", state="created", title="Bài chờ", max_points=10, criteria=CRIT))
    waiting = [await seed(m.GradeItem(tenant_id=world.t.id, sandbox_id=sb.id, assignment_id=work.id, submission_id=f"s{i}", student_ref=f"u{i}", status="pending")) for i in range(2)]
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = (await app_client.get(f"/api/v1/grading?status=pending&assignment_id={work.id}")).json()
    assert len(r["items"]) == 2 and r["counts"]["pending"] == 2 and r["counts"]["proposed"] == 0  # counts are of this work only
    one = await app_client.post(f"/api/v1/grading/{waiting[0].id}/grade", headers=h(csrf))
    assert one.status_code == 200 and one.json() == {"queued": 1}
    again = await app_client.post(f"/api/v1/grading/{waiting[0].id}/grade", headers=h(csrf))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "NOT_PENDING"
    rest = await app_client.post(f"/api/v1/assignments/{work.id}/grade", headers=h(csrf))
    assert rest.json() == {"queued": 1}
    async with tenant_session(world.t.id) as s:
        assert {(await s.get(m.GradeItem, w.id)).status for w in waiting} == {"queued"}


async def test_a_class_page_lists_every_piece_of_work_with_where_its_submissions_stand(app_client, world, api_key_factory, gradebook):
    _, _, src, *_ = gradebook
    await as_(app_client, world, api_key_factory, "owner")
    r = (await app_client.get(f"/api/v1/classes/{src.id}/assignments")).json()
    assert r["class"]["name"] == "Tiếng Anh A1" and r["class"]["grading_mode"] == "review"
    by = {x["title"]: x for x in r["items"]}
    assert by["Viết 5 câu"]["ours"] is True and by["Viết 5 câu"]["gradable"] is True and by["Viết 5 câu"]["counts"]["proposed"] == 1
    assert by["Bài đọc"]["ours"] is False and by["Bài đọc"]["submissions"] == 1
    assert (await app_client.get("/api/v1/classes/00000000-0000-0000-0000-000000000000/assignments")).status_code == 404


# --- posting the way Classroom does ---------------------------------------------------------------------------------------------
async def post_draft(app_client, csrf, src, **extra):
    r = await app_client.post("/api/v1/assignments", headers=h(csrf), json={**DRAFT, "class_id": str(src.id), **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_the_form_can_set_due_date_schedule_topic_and_students_before_approving(app_client, world, api_key_factory, gradebook):
    fc, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    due, when = datetime.now(UTC) + timedelta(days=5), datetime.now(UTC) + timedelta(days=1)
    d = await post_draft(app_client, csrf, src, due=due.isoformat(), scheduled=when.isoformat(), topic_name="Tuần 6", assignees=[{"id": "u1", "name": "An"}])
    assert (d["posting"], d["topic"]["name"], d["assignees"]) == ("draft", "Tuần 6", [{"id": "u1", "name": "An"}]) and d["scheduled"] and d["due"]
    ok = await app_client.post(f"/api/v1/assignments/{d['id']}/decision", headers=h(csrf), json={"action": "approve", "publish": True})
    assert ok.status_code == 200 and ok.json()["scheduled"] is True and ok.json()["published"] is False
    w = fc.work[ok.json()["coursework_id"]]
    assert w["state"] == "DRAFT" and "scheduledTime" in w and w["individualStudentsOptions"] == {"studentIds": ["u1"]} and w["topicId"] in fc.topics
    listing = {x["id"]: x for x in (await app_client.get("/api/v1/assignments")).json()["items"]}
    assert listing[d["id"]]["posting"] == "scheduled"


async def test_a_schedule_in_the_past_is_refused_when_the_draft_is_written(app_client, world, api_key_factory, gradebook):
    _, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post("/api/v1/assignments", headers=h(csrf), json={**DRAFT, "class_id": str(src.id),
                                                                           "scheduled": (datetime.now(UTC) - timedelta(hours=1)).isoformat()})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_SCHEDULE"
    assert (await app_client.get("/api/v1/assignments")).json()["items"] == []


async def test_a_posted_assignment_can_be_edited_published_and_deleted_from_the_console(app_client, world, api_key_factory, gradebook):
    fc, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    d = await post_draft(app_client, csrf, src)
    wid = (await app_client.post(f"/api/v1/assignments/{d['id']}/decision", headers=h(csrf), json={"action": "approve", "publish": False})).json()["coursework_id"]
    assert fc.work[wid]["state"] == "DRAFT"
    e = await app_client.patch(f"/api/v1/assignments/{d['id']}", headers=h(csrf), json={"title": "Tên mới", "topic_name": "Ôn thi", "due": (datetime.now(UTC) + timedelta(days=9)).isoformat()})
    assert e.status_code == 200 and e.json()["title"] == "Tên mới" and e.json()["topic"]["name"] == "Ôn thi" and fc.work[wid]["title"] == "Tên mới"
    assert e.json()["posting"] == "classroom_draft"
    p = await app_client.post(f"/api/v1/assignments/{d['id']}/publish", headers=h(csrf))
    assert p.status_code == 200 and fc.work[wid]["state"] == "PUBLISHED"
    assert (await app_client.post(f"/api/v1/assignments/{d['id']}/publish", headers=h(csrf))).json()["detail"]["code"] == "ALREADY_PUBLISHED"
    x = await app_client.delete(f"/api/v1/assignments/{d['id']}", headers=h(csrf))
    assert x.status_code == 200 and wid not in fc.work
    assert d["id"] not in [i["id"] for i in (await app_client.get("/api/v1/assignments")).json()["items"]]
    assert (await app_client.patch(f"/api/v1/assignments/{d['id']}", headers=h(csrf), json={"title": "Lại"})).status_code == 409


async def test_an_edit_with_nothing_in_it_or_an_empty_title_is_refused(app_client, world, api_key_factory, gradebook):
    _, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    d = await post_draft(app_client, csrf, src)
    assert (await app_client.patch(f"/api/v1/assignments/{d['id']}", headers=h(csrf), json={})).status_code == 422
    assert (await app_client.patch(f"/api/v1/assignments/{d['id']}", headers=h(csrf), json={"title": None})).status_code == 422
    assert (await app_client.patch(f"/api/v1/assignments/{d['id']}", headers=h(csrf), json={"due": (datetime.now(UTC) - timedelta(days=1)).isoformat()})).status_code == 422


async def test_work_the_teacher_made_by_hand_cannot_be_edited_published_or_deleted(app_client, world, api_key_factory, gradebook):
    fc, _, src, *_ = gradebook
    csrf = await as_(app_client, world, api_key_factory, "owner")
    async with tenant_session(world.t.id) as s:
        theirs = (await s.execute(select(m.Assignment).where(m.Assignment.origin == "classroom"))).scalars().first().id
    for call in (app_client.patch(f"/api/v1/assignments/{theirs}", headers=h(csrf), json={"title": "x"}),
                 app_client.post(f"/api/v1/assignments/{theirs}/publish", headers=h(csrf)),
                 app_client.delete(f"/api/v1/assignments/{theirs}", headers=h(csrf))):
        assert (await call).status_code == 404


async def test_the_form_can_list_the_courses_topics_and_students(app_client, world, api_key_factory, gradebook):
    fc, _, src, *_ = gradebook
    fc.topics["t0"] = {"topicId": "t0", "name": "Tuần 1", "_course": "c1"}
    await as_(app_client, world, api_key_factory, "owner")
    r = (await app_client.get(f"/api/v1/classes/{src.id}/classroom-options")).json()
    assert r["topics"] == [{"id": "t0", "name": "Tuần 1"}] and {s["name"] for s in r["students"]} >= {"Nguyễn Minh An", "Trần Bảo Châu"} and r["problems"] == {}


async def test_a_missing_topics_permission_does_not_hide_the_students(app_client, world, api_key_factory, gradebook, monkeypatch):
    fc, _, src, *_ = gradebook
    csrf_ = await as_(app_client, world, api_key_factory, "owner")
    orig = fc.handle

    def handle(req):
        return httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}}) if req.url.path.endswith("/topics") else orig(req)

    fc.handle = handle
    r = (await app_client.get(f"/api/v1/classes/{src.id}/classroom-options")).json()
    assert r["problems"] == {"topics": "PERMISSION_DENIED"} and r["students"] and csrf_
