"""WP38: a class is a Drive folder with its own Mezon webhook; the owner makes and edits them, the teaching team sees them."""
import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from support import h, sign_in

from cortex_leads.config import get_settings
from cortex_leads.connectors import egress
from cortex_leads.console import classes
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

HOOK = "https://webhook.mezon.ai/hooks/secret-token-lop-a"


@pytest.fixture(autouse=True)
def public_mezon(monkeypatch):
    async def public(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(egress, "resolve_host", public)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def as_(app_client, world, api_key_factory, role="owner"):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


@pytest.fixture
async def recapper(world, seed):
    return await seed(m.Sandbox(tenant_id=world.t.id, name="lesson_recap", purpose="lesson_recap", profile_ref="lesson_recapper@1", domain_pack={}))


async def account(world, seed, scopes=("drive.file",), label="Cô Lan"):
    secret = json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "r"}).encode()
    return await seed(m.GoogleAccount(tenant_id=world.t.id, label=label, scopes=list(scopes), connected_by="staff:owner",
                                      secret_enc=Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(secret)))


@pytest.fixture
def drive(monkeypatch):
    from dev.local.fake_classroom import FakeClassroom
    from test_lesson_upload import uploader_for
    fake = FakeClassroom()
    monkeypatch.setattr(classes, "open_uploader", uploader_for(fake))
    return fake


async def test_a_class_gets_its_own_folder_in_drive_and_its_own_webhook(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp A1", "webhook_url": HOOK}, headers=h(csrf))
    assert r.status_code == 201, r.text
    assert [f["name"] for f in drive.folders.values()] == ["Lớp A1"]  # the folder carries the class's name
    (item,) = (await app_client.get("/api/v1/classes")).json()["items"]
    assert item["name"] == "Lớp A1" and item["account"] == "Cô Lan" and item["can_upload"] is True and item["has_webhook"] is True
    assert item["webhook"] == "webhook.mezon.ai" and "secret-token" not in json.dumps(item)  # the address is a secret: only its host is shown
    async with tenant_session(world.t.id) as s:
        src = (await s.execute(select(m.Class))).scalar_one()
        assert src.owned and src.source_ref == next(iter(drive.folders)) and src.source_secret_enc is None and src.notify_target_id is not None


async def test_two_classes_do_not_share_folders_and_may_share_a_channel(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    for name in ("Lớp A1", "Lớp B2"):
        r = await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": name, "webhook_url": HOOK}, headers=h(csrf))
        assert r.status_code == 201
    assert len(drive.folders) == 2
    async with tenant_session(world.t.id) as s:
        assert len((await s.execute(select(m.NotifyTarget))).scalars().all()) == 1  # one channel, two classes
    again = await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp A1"}, headers=h(csrf))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "NAME_TAKEN"


async def test_a_webhook_that_could_leak_a_recap_is_refused(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    for bad in ("http://webhook.mezon.ai/x", "https://evil.example/x", "https://user:pw@webhook.mezon.ai/x"):
        r = await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp X", "webhook_url": bad}, headers=h(csrf))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_WEBHOOK", bad


async def test_a_class_needs_the_right_permission_on_the_account(app_client, world, api_key_factory, recapper, seed, drive):
    csrf = await as_(app_client, world, api_key_factory)
    no_drive = await account(world, seed, scopes=("classroom.courses.readonly",), label="Chỉ lớp")
    r = await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(no_drive.id), "name": "Lớp A1"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MISSING_SCOPE" and not drive.folders
    read_only = await account(world, seed, scopes=("drive.readonly",), label="Chỉ đọc")
    r = await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(read_only.id), "name": "Lớp Meet", "folder": "F" * 12}, headers=h(csrf))
    assert r.status_code == 201
    (item,) = (await app_client.get("/api/v1/classes")).json()["items"]
    assert item["can_upload"] is False and item["folder"].startswith("Thư mục có sẵn")  # an existing folder can be watched, not written to


async def test_the_owner_renames_a_class_and_changes_or_removes_its_webhook(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    made = (await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp A1"}, headers=h(csrf))).json()
    url = f"/api/v1/classes/{made['id']}"
    out = (await app_client.patch(url, json={"name": "Lớp A1 buổi tối", "webhook_url": HOOK}, headers=h(csrf))).json()
    assert out["name"] == "Lớp A1 buổi tối" and out["has_webhook"] is True
    assert (await app_client.patch(url, json={"webhook_url": "http://nope"}, headers=h(csrf))).status_code == 422
    assert (await app_client.patch(url, json={"webhook_url": None}, headers=h(csrf))).json()["has_webhook"] is False
    assert (await app_client.patch(url, json={"name": "Lớp A1 buổi tối"}, headers=h(csrf))).json()["has_webhook"] is False  # not mentioned: untouched
    assert (await app_client.patch(url, json={"active": False}, headers=h(csrf))).json()["active"] is False
    assert (await app_client.patch("/api/v1/classes/00000000-0000-0000-0000-000000000000", json={"name": "xx"}, headers=h(csrf))).status_code == 404


async def test_staff_see_the_classes_but_cannot_change_them(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)
    owner = await as_(app_client, world, api_key_factory)
    await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp A1"}, headers=h(owner))
    staff = await as_(app_client, world, api_key_factory, "staff")
    assert [c["name"] for c in (await app_client.get("/api/v1/classes")).json()["items"]] == ["Lớp A1"]
    r = await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp C"}, headers=h(staff))
    assert r.status_code == 403


async def test_the_lesson_list_can_be_cut_to_one_class_and_names_each_lessons_class(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    ids = {}
    for name in ("Lớp A1", "Lớp B2"):
        ids[name] = (await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": name}, headers=h(csrf))).json()["id"]
        await seed(m.Lesson(tenant_id=world.t.id, sandbox_id=recapper.id, class_id=ids[name], file_id=f"f-{name}", name=f"buổi của {name}"))
    everything = (await app_client.get("/api/v1/lessons")).json()
    assert {(x["name"], x["class_name"]) for x in everything["items"]} == {("buổi của Lớp A1", "Lớp A1"), ("buổi của Lớp B2", "Lớp B2")}
    assert [c["name"] for c in everything["classes"]] == ["Lớp A1", "Lớp B2"]
    only = (await app_client.get("/api/v1/lessons", params={"class_id": ids["Lớp B2"]})).json()
    assert [x["name"] for x in only["items"]] == ["buổi của Lớp B2"]


async def test_the_owner_deletes_a_class_with_its_lessons_and_the_drive_folder_stays(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    made = await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp A1"}, headers=h(csrf))
    cid = made.json()["id"]
    async with tenant_session(world.t.id) as s:
        s.add(m.Lesson(tenant_id=world.t.id, sandbox_id=recapper.id, class_id=cid, file_id="f1", name="buổi 1.mp4"))
    r = await app_client.delete(f"/api/v1/classes/{cid}", headers=h(csrf))
    assert r.status_code == 200 and r.json()["lessons"] == 1
    assert (await app_client.get("/api/v1/classes")).json()["items"] == []
    assert len(drive.folders) == 1 and not any(f["trashed"] for f in drive.folders.values())  # the teacher's folder is untouched
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.Lesson))).first() is None
    assert (await app_client.delete(f"/api/v1/classes/{cid}", headers=h(csrf))).status_code == 404


async def test_a_class_posts_its_recaps_to_a_classroom_course_when_the_account_may(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)  # owns the Drive folder, may not post
    poster = await account(world, seed, scopes=("classroom.courses.readonly", "classroom.announcements"), label="Cô Lan đăng bài")
    csrf = await as_(app_client, world, api_key_factory)
    made = (await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp B1"}, headers=h(csrf))).json()
    r = await app_client.patch(f"/api/v1/classes/{made['id']}", json={"classroom_course_id": "123456", "classroom_course_name": "IELTS B1", "classroom_account_id": str(poster.id)}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["classroom"] == {"course_id": "123456", "course": "IELTS B1", "account_id": str(poster.id)}
    r = await app_client.patch(f"/api/v1/classes/{made['id']}", json={"recap_mode": "auto"}, headers=h(csrf))
    assert r.json()["classroom"]["course_id"] == "123456" and r.json()["policy"]["recap_mode"] == "auto"  # changing only the setting keeps the course
    r = await app_client.patch(f"/api/v1/classes/{made['id']}", json={"classroom_course_id": ""}, headers=h(csrf))
    assert r.json()["classroom"] is None  # taken off


async def test_an_account_not_signed_in_for_posting_is_refused(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)  # Drive only
    csrf = await as_(app_client, world, api_key_factory)
    made = (await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp C1"}, headers=h(csrf))).json()
    r = await app_client.patch(f"/api/v1/classes/{made['id']}", json={"classroom_course_id": "123456"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MISSING_SCOPE"
    r = await app_client.patch(f"/api/v1/classes/{made['id']}", json={"classroom_course_id": "12/../3"}, headers=h(csrf))
    assert r.status_code == 422


async def grader_class(world, seed, **kw):
    sb = await seed(m.Sandbox(tenant_id=world.t.id, name="classroom_grader", purpose="classroom_grader", profile_ref="classroom_grader@1"))
    return await seed(m.Class(tenant_id=world.t.id, name="Lớp chấm", grader_sandbox_id=sb.id, course_id="c1", auth_kind="oauth", **kw)), sb


async def test_a_new_class_waits_for_a_person_both_for_recaps_and_for_grades(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    made = (await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp P1"}, headers=h(csrf))).json()
    (item,) = (await app_client.get("/api/v1/classes")).json()["items"]
    assert item["id"] == made["id"] and item["policy"] == {"recap_mode": "review", "grading_mode": "review", "assignment_post_mode": "manual"}


async def test_only_a_class_connected_to_a_course_can_leave_review_for_grading_and_each_change_is_in_the_trail(app_client, world, api_key_factory, seed):
    cls, _ = await grader_class(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    r = await app_client.patch(f"/api/v1/classes/{cls.id}", json={"grading_mode": "auto_write"}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["policy"]["grading_mode"] == "auto_write"
    async with tenant_session(world.t.id) as s:
        trail = [e.action for e in (await s.execute(select(m.AuditEvent).where(m.AuditEvent.action.like("class.%")))).scalars()]
    assert "class.grading_mode" in trail  # who let the machine write grades by itself, and when


async def test_a_class_with_no_course_to_grade_cannot_change_how_it_grades(app_client, world, api_key_factory, recapper, seed, drive):
    acct = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    made = (await app_client.post("/api/v1/classes", json={"sandbox_id": str(recapper.id), "account_id": str(acct.id), "name": "Lớp Q1"}, headers=h(csrf))).json()
    r = await app_client.patch(f"/api/v1/classes/{made['id']}", json={"grading_mode": "manual"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_GRADER"


async def test_the_teaching_team_cannot_loosen_a_class(app_client, world, api_key_factory, seed):
    cls, _ = await grader_class(world, seed, listed=True)
    csrf = await as_(app_client, world, api_key_factory, "staff")
    r = await app_client.patch(f"/api/v1/classes/{cls.id}", json={"grading_mode": "auto_write"}, headers=h(csrf))
    assert r.status_code == 403


async def test_leaving_manual_sets_waiting_submissions_going(app_client, world, api_key_factory, seed):
    cls, sb = await grader_class(world, seed, listed=True, grading_mode="manual")
    work = await seed(m.Assignment(tenant_id=world.t.id, class_id=cls.id, coursework_id="w1", title="Bài", max_points=10, criteria=[], state="created"))
    item = await seed(m.GradeItem(tenant_id=world.t.id, sandbox_id=sb.id, assignment_id=work.id, submission_id="s1", student_ref="u1", status="pending"))
    csrf = await as_(app_client, world, api_key_factory)
    r = await app_client.patch(f"/api/v1/classes/{cls.id}", json={"grading_mode": "review"}, headers=h(csrf))
    assert r.status_code == 200
    async with tenant_session(world.t.id) as s:
        assert (await s.get(m.GradeItem, item.id)).status == "queued"
