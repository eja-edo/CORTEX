"""WP46: a teacher runs the classes they were given and nothing else. The first test holds every class endpoint to a decision; the next ones
walk those endpoints against another class, so a new endpoint is covered the day it is written."""
import json
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.routing import APIRoute
from sqlalchemy import delete, select
from support import PASSWORD, h, sign_in

from cortex_leads.auth import perms
from cortex_leads.auth.users import change_role_or_status, create_user
from cortex_leads.config import get_settings
from cortex_leads.connectors import google_accounts as ga
from cortex_leads.connectors.classroom import ClassroomClient
from cortex_leads.console import api as console_api
from cortex_leads.console import lessons as lessons_screen
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.grader import job
from dev.local.fake_classroom import demo

ZERO = "00000000-0000-0000-0000-000000000000"
CRIT = [{"id": "dung_thi", "label": "Dùng đúng thì", "points": 6, "descriptor": ""}, {"id": "du_so_cau", "label": "Đủ 5 câu", "points": 4, "descriptor": ""}]
PROPOSAL = {"criteria": [{"id": "dung_thi", "label": "Dùng đúng thì", "points": 6, "score": 5, "proposed": 5, "quote": "She has finished", "comment": "", "verified": True},
                         {"id": "du_so_cau", "label": "Đủ 5 câu", "points": 4, "score": 4, "proposed": 4, "quote": "We have never", "comment": "", "verified": True}],
            "total": 9, "max_points": 10, "feedback": "Em làm tốt.", "concerns": [], "problems": [], "flags": []}
CLASS_PERMS = perms.CLASS_WORK | {"classes.edit"}
# Lists, and calls told the class in their body: `need()` with the narrowing written in the handler.
NARROWS_ITSELF = {("GET", "/api/v1/classes"), ("GET", "/api/v1/lessons"), ("GET", "/api/v1/grading"), ("GET", "/api/v1/assignments"), ("POST", "/api/v1/assignments"),
                  ("POST", "/api/v1/assignments/ai"), ("POST", "/api/v1/lessons/upload/session"), ("GET", "/api/v1/google/picker"), ("POST", "/api/v1/google/picker/token")}
BUSINESS_WIDE = {("GET", "/api/v1/class-kinds"), ("GET", "/api/v1/class-kinds/{kind_id}/templates")}  # the shared templates: read by anyone who grades, of no one class


class Bearer:
    async def headers(self):
        return {"Authorization": "Bearer t"}


def _guards(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _guards(d)


def _routes(router):
    for r in router.routes:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            yield from _routes(r.original_router)


def _class_routes():
    """{(method, path): scoped by its address?} for every endpoint that uses a class permission."""
    out = {}
    for r in _routes(console_api.router):
        calls = list(_guards(r.dependant))
        if {getattr(c, "perm", None) for c in calls} & CLASS_PERMS:
            out |= {(x, "/api/v1" + r.path): any(getattr(c, "class_scoped", False) for c in calls) for x in r.methods}
    return out


def test_every_class_endpoint_says_how_it_keeps_to_a_teachers_classes():
    """A new endpoint that uses a class permission fails here until it is `need_class`, or is added above with the narrowing written."""
    routes = _class_routes()
    undecided = {k for k, scoped in routes.items() if not scoped} - NARROWS_ITSELF - BUSINESS_WIDE
    assert undecided == set()
    assert (NARROWS_ITSELF | BUSINESS_WIDE) - set(routes) == set(), "decisions for endpoints that no longer exist"
    assert not {k for k, scoped in routes.items() if scoped} & (NARROWS_ITSELF | BUSINESS_WIDE)


def test_a_teacher_holds_the_work_of_a_class_and_nothing_of_the_business():
    assert perms.TEACHER == perms.CLASS_WORK | {"classes.edit", "audit.own", "account.self"}
    assert "classes.all" in perms.OWNER and "classes.all" not in perms.TEACHER and "classes.all" not in perms.STAFF
    assert not perms.STAFF & (perms.CLASS_WORK | {"classes.all", "classes.edit", "templates.manage"})  # customer care: nothing of the classes
    assert perms.CLASS_WORK <= perms.OWNER


@pytest.fixture
async def school(world, seed, monkeypatch):
    """Two classes, each with a lesson, a piece of work and a submission waiting for a decision."""
    fc = demo()
    work = next(w for w in fc.work.values() if w["associatedWithDeveloper"])["id"]
    other = next(w for w in fc.work.values() if not w["associatedWithDeveloper"])["id"]
    grader = await seed(m.Sandbox(tenant_id=world.t.id, name="classroom_grader", purpose="classroom_grader", profile_ref="classroom_grader@1"))
    recap = await seed(m.Sandbox(tenant_id=world.t.id, name="lesson_recap", purpose="lesson_recap", profile_ref="lesson_recapper@1"))
    secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(b"{}")
    out = {}
    for key, name, cw in (("a", "Lớp A", work), ("b", "Lớp B", other)):
        c = await seed(m.Class(tenant_id=world.t.id, name=name, grader_sandbox_id=grader.id, recap_sandbox_id=recap.id, source_kind="local", source_ref=f"/{key}",
                               course_id="c1" if key == "a" else "c2", auth_kind="delegated", classroom_secret_enc=secret))
        w = await seed(m.Assignment(tenant_id=world.t.id, class_id=c.id, coursework_id=cw, origin="app", state="created", title=f"Bài {name}", max_points=10, criteria=CRIT,
                                    answer_key="have/has + V3"))
        sub = next(k for k, v in fc.subs.items() if v["_work"] == cw)
        i = await seed(m.GradeItem(tenant_id=world.t.id, sandbox_id=grader.id, assignment_id=w.id, submission_id=sub, student_ref="u1", student_name=f"Học sinh {name}",
                                   status="proposed", content="She has finished her homework. We have never been to Paris.", proposal=PROPOSAL))
        lesson = await seed(m.Lesson(tenant_id=world.t.id, sandbox_id=recap.id, class_id=c.id, status="done", file_id=f"f-{key}", name=f"Buổi {name}.mp4",
                                     recap={"summary": "x"}, transcript=f"lời của {name}"))
        out[key] = {"class": c, "work": w, "item": i, "lesson": lesson}
    monkeypatch.setattr(job, "open_source", lambda s: ClassroomClient(httpx.AsyncClient(transport=fc.transport()), Bearer(), base="https://x/v1", drive_base="https://x/drive/v3"))
    return out


async def make_teacher(world, *classes, email="co.mai@tt.vn"):
    async with tenant_session(world.t.id) as s:
        u = await create_user(s, world.t.id, email=email, name="Cô Mai", role="teacher", password=PASSWORD, created_by="test")
        s.add_all(m.ClassTeacher(tenant_id=world.t.id, class_id=c.id, user_id=u.id, assigned_by="test") for c in classes)
    return u


async def login(client, email="co.mai@tt.vn"):
    client.cookies.clear()
    r = await client.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["csrf"]


async def owner(client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "owner", None)
    client.cookies.clear()
    return await sign_in(client, key)


def fill(path, ids):
    return re.sub(r"\{(\w+)\}", lambda x: str(ids[x.group(1)]), path)


def ids_of(room):
    return {"class_id": room["class"].id, "assignment_id": room["work"].id, "draft_id": room["work"].id, "item_id": room["item"].id, "lesson_id": room["lesson"].id}


async def test_what_is_in_another_class_answers_exactly_like_what_does_not_exist(app_client, world, school):
    await make_teacher(world, school["a"]["class"])
    csrf = await login(app_client)
    scoped = sorted(k for k, v in _class_routes().items() if v)
    assert len(scoped) >= 15
    nothing = dict.fromkeys(ids_of(school["b"]), ZERO)
    for method, path in scoped:
        theirs = await app_client.request(method, fill(path, ids_of(school["b"])), json={}, headers=h(csrf))
        missing = await app_client.request(method, fill(path, nothing), json={}, headers=h(csrf))
        assert theirs.status_code == 404, (method, path, theirs.status_code, theirs.text)
        assert (missing.status_code, missing.json()) == (theirs.status_code, theirs.json()), (method, path)
    async with tenant_session(world.t.id) as s:
        b = await s.get(m.Class, school["b"]["class"].id)
        item = await s.get(m.GradeItem, school["b"]["item"].id)
        assert await s.get(m.Lesson, school["b"]["lesson"].id) is not None
    assert b.name == "Lớp B" and item.status == "proposed"


async def test_a_refusal_is_a_line_in_the_log(app_client, world, school):
    await make_teacher(world, school["a"]["class"])
    await login(app_client)
    await app_client.get(f"/api/v1/grading/{school['b']['item'].id}")
    async with tenant_session(world.t.id) as s:
        (e,) = (await s.execute(select(m.AuditEvent).where(m.AuditEvent.action == "permission.refused"))).scalars().all()
    assert e.result == "denied" and e.actor_role == "teacher" and str(school["b"]["item"].id) in e.metadata_["path"]


async def test_the_lists_hold_only_their_own_classes_even_when_asked_for_another(app_client, world, school):
    await make_teacher(world, school["a"]["class"])
    await login(app_client)
    a, b = school["a"], school["b"]
    get = lambda p: app_client.get(f"/api/v1/{p}")
    assert [c["name"] for c in (await get("classes")).json()["items"]] == ["Lớp A"]
    lessons = (await get("lessons")).json()
    assert [x["class_id"] for x in lessons["items"]] == [str(a["class"].id)] and [c["name"] for c in lessons["classes"]] == ["Lớp A"]
    assert (await get(f"lessons?class_id={b['class'].id}")).json()["items"] == []
    grading = (await get("grading")).json()
    assert [x["id"] for x in grading["items"]] == [str(a["item"].id)] and grading["counts"]["proposed"] == 1
    for ask in (f"class_id={b['class'].id}", f"assignment_id={b['work'].id}"):
        other = (await get(f"grading?{ask}")).json()
        assert other["items"] == [] and other["counts"]["proposed"] == 0
    assert [x["label"] for x in (await get("assignments")).json()["sources"]] == ["Lớp A"]


async def test_a_teacher_with_no_class_sees_an_empty_school(app_client, world, school):
    await make_teacher(world)
    await login(app_client)
    assert (await app_client.get("/api/v1/classes")).json()["items"] == []
    assert (await app_client.get("/api/v1/lessons")).json()["items"] == []
    assert (await app_client.get("/api/v1/grading?status=all")).json()["items"] == []


async def test_in_their_own_class_a_teacher_does_the_work(app_client, world, school):
    await make_teacher(world, school["a"]["class"])
    csrf = await login(app_client)
    a = school["a"]
    for path in (f"classes/{a['class'].id}/assignments", f"grading/{a['item'].id}", f"lessons/{a['lesson'].id}", f"classes/{a['class'].id}/classroom-options"):
        assert (await app_client.get(f"/api/v1/{path}")).status_code == 200, path
    r = await app_client.post(f"/api/v1/grading/{a['item'].id}/decision", json={"action": "approve"}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["written"] is True, r.text
    assert (await app_client.post(f"/api/v1/lessons/{a['lesson'].id}/release", headers=h(csrf))).status_code == 200
    body = {"class_id": str(a["class"].id), "title": "Bài mới", "description": "Viết năm câu về gia đình.", "max_points": 10, "criteria": CRIT}
    made = await app_client.post("/api/v1/assignments", json=body, headers=h(csrf))
    assert made.status_code == 201 and made.json()["created_by"] == "staff:co-mai", made.text  # who did it stays theirs, whatever Google account posts it


async def test_a_class_named_in_the_body_is_held_to_the_same_line(app_client, world, school):
    await make_teacher(world, school["a"]["class"])
    csrf = await login(app_client)
    b = str(school["b"]["class"].id)
    body = {"class_id": b, "title": "Bài mới", "description": "Viết năm câu về gia đình.", "max_points": 10, "criteria": CRIT}
    assert (await app_client.post("/api/v1/assignments", json=body, headers=h(csrf))).status_code == 404
    assert (await app_client.post("/api/v1/assignments/ai", json={"class_id": b, "topic": "Gia đình"}, headers=h(csrf))).status_code == 404
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.Assignment).where(m.Assignment.title == "Bài mới"))).first() is None


async def test_an_upload_goes_only_to_their_own_class(app_client, world, school, seed, monkeypatch):
    """Even when another class is the only one that can take uploads: "the only class" must mean only among theirs."""
    a = await seed(m.GoogleAccount(tenant_id=world.t.id, label="Chung", email="chung@tt.vn", scopes=["drive.file"], connected_by="staff:owner", secret_enc=b"x"))
    async with tenant_session(world.t.id) as s:
        b = await s.get(m.Class, school["b"]["class"].id)
        b.source_kind, b.owned, b.drive_account_id = "drive", True, a.id
    await make_teacher(world, school["a"]["class"])
    csrf = await login(app_client)

    async def live(*_):
        return ["a skill"]
    monkeypatch.setattr(lessons_screen, "live_skills_for", live)
    r = await app_client.post("/api/v1/lessons/upload/session", json={"name": "buoi.mp4", "size": 10, "class_id": str(school["b"]["class"].id)}, headers=h(csrf))
    none_said = await app_client.post("/api/v1/lessons/upload/session", json={"name": "buoi.mp4", "size": 10}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_CLASS"
    assert none_said.status_code == 409 and none_said.json()["detail"]["code"] == "NO_CLASS"


async def test_a_teacher_changes_their_class_but_does_not_rewire_it(app_client, world, school):
    await make_teacher(world, school["a"]["class"])
    csrf = await login(app_client)
    url = f"/api/v1/classes/{school['a']['class'].id}"
    ok = await app_client.patch(url, json={"name": "Lớp A nâng cao", "recap_mode": "auto", "grading_mode": "manual"}, headers=h(csrf))
    assert ok.status_code == 200 and ok.json()["name"] == "Lớp A nâng cao" and ok.json()["policy"]["grading_mode"] == "manual", ok.text
    for said in ({"webhook_url": "https://webhook.mezon.ai/x"}, {"webhook_url": None}, {"active": False}, {"classroom_course_id": ""}, {"classroom_course_id": "9", "classroom_account_id": ZERO},
                 {"grading_mode": "auto_write"}, {"name": "Lén", "grading_mode": "auto_write"}):
        r = await app_client.patch(url, json=said, headers=h(csrf))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "FORBIDDEN", said
    async with tenant_session(world.t.id) as s:
        c = await s.get(m.Class, school["a"]["class"].id)
    assert c.name == "Lớp A nâng cao" and c.active and c.course_id == "c1" and c.grading_mode == "manual"  # a refused change leaves nothing behind


async def test_a_teacher_can_take_a_class_back_from_writing_grades_by_itself(app_client, world, school):
    async with tenant_session(world.t.id) as s:
        (await s.get(m.Class, school["a"]["class"].id)).grading_mode = "auto_write"
    await make_teacher(world, school["a"]["class"])
    csrf = await login(app_client)
    r = await app_client.patch(f"/api/v1/classes/{school['a']['class'].id}", json={"grading_mode": "review"}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["policy"]["grading_mode"] == "review"


async def test_what_is_not_a_class_stays_out_of_reach(app_client, world, school):
    await make_teacher(world, school["a"]["class"])
    csrf = await login(app_client)
    a = school["a"]["class"].id
    for method, path in (("GET", "conversations"), ("GET", "skills"), ("GET", "sandboxes"), ("GET", "catalog"), ("GET", "team"), ("GET", "google/accounts"), ("GET", "settings/business"),
                         ("POST", "classes"), ("DELETE", f"classes/{a}"), ("POST", f"classes/{a}/relink"), ("POST", "class-kinds"), ("POST", "kill-switch")):
        r = await app_client.request(method, f"/api/v1/{path}", json={}, headers=h(csrf))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "FORBIDDEN", (method, path, r.status_code)
    me = (await app_client.get("/api/v1/session")).json()
    assert me["role"] == "teacher" and "inbox.use" not in me["permissions"] and "lessons.read" in me["permissions"] and me["needs_person"] == 0


async def test_the_shared_templates_are_read_not_changed(app_client, world, seed):
    kind = await seed(m.ClassKind(tenant_id=world.t.id, name="IELTS"))
    await make_teacher(world)
    csrf = await login(app_client)
    assert [k["name"] for k in (await app_client.get("/api/v1/class-kinds")).json()["items"]] == ["IELTS"]
    assert (await app_client.get(f"/api/v1/class-kinds/{kind.id}/templates")).status_code == 200
    assert (await app_client.delete(f"/api/v1/class-kinds/{kind.id}", headers=h(csrf))).status_code == 403


# --- the owner gives the classes --------------------------------------------------------------------
async def test_the_owner_gives_classes_and_it_holds_at_the_teachers_next_request(app_client, world, api_key_factory, school):
    u = await make_teacher(world)
    a, b = str(school["a"]["class"].id), str(school["b"]["class"].id)
    csrf = await owner(app_client, world, api_key_factory)
    r = await app_client.put(f"/api/v1/team/{u.id}/classes", json={"class_ids": [a, b]}, headers=h(csrf))
    assert r.status_code == 200 and [c["name"] for c in r.json()["classes"]] == ["Lớp A", "Lớp B"], r.text
    listed = next(x for x in (await app_client.get("/api/v1/team")).json()["items"] if x["id"] == str(u.id))
    assert [c["id"] for c in listed["classes"]] == [a, b]
    teacher = await login(app_client)
    assert len((await app_client.get("/api/v1/classes")).json()["items"]) == 2
    async with tenant_session(world.t.id) as s:  # taken away while they are signed in
        await s.execute(delete(m.ClassTeacher).where(m.ClassTeacher.class_id == school["b"]["class"].id))
    assert [c["name"] for c in (await app_client.get("/api/v1/classes")).json()["items"]] == ["Lớp A"]
    assert (await app_client.get(f"/api/v1/grading/{school['b']['item'].id}")).status_code == 404
    assert teacher


async def test_giving_classes_is_in_the_trail_and_saying_the_same_again_is_not(app_client, world, api_key_factory, school):
    u = await make_teacher(world, school["a"]["class"])
    csrf = await owner(app_client, world, api_key_factory)
    url = f"/api/v1/team/{u.id}/classes"
    await app_client.put(url, json={"class_ids": [str(school["b"]["class"].id)]}, headers=h(csrf))
    await app_client.put(url, json={"class_ids": [str(school["b"]["class"].id)]}, headers=h(csrf))
    async with tenant_session(world.t.id) as s:
        (e,) = (await s.execute(select(m.AuditEvent).where(m.AuditEvent.action == "user.classes_changed"))).scalars().all()
    assert e.metadata_ == {"added": ["Lớp B"], "removed": ["Lớp A"]}


async def test_classes_go_only_to_a_teacher_and_only_real_ones(app_client, world, api_key_factory, school, seed, tenant_factory):
    u = await make_teacher(world)
    csrf = await owner(app_client, world, api_key_factory)
    me = (await app_client.get("/api/v1/session")).json()
    staff = next(x for x in (await app_client.get("/api/v1/team")).json()["items"] if x["email"] == me["email"])
    a = str(school["a"]["class"].id)
    r = await app_client.put(f"/api/v1/team/{staff['id']}/classes", json={"class_ids": [a]}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_TEACHER"
    other = await tenant_factory()
    sb = await seed(m.Sandbox(tenant_id=other.id, name="classroom_grader", purpose="classroom_grader", profile_ref="classroom_grader@1"))
    foreign = await seed(m.Class(tenant_id=other.id, name="Lớp ngoài", grader_sandbox_id=sb.id, course_id="c9", auth_kind="oauth"))
    hidden = await seed(m.Class(tenant_id=world.t.id, name="/x", listed=False, grader_sandbox_id=school["a"]["class"].grader_sandbox_id, course_id="c8", auth_kind="oauth"))
    for bad in (str(foreign.id), str(hidden.id), ZERO):
        r = await app_client.put(f"/api/v1/team/{u.id}/classes", json={"class_ids": [a, bad]}, headers=h(csrf))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_CLASS", bad
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.ClassTeacher))).first() is None  # all or nothing


async def test_a_teacher_made_from_the_team_page_gets_a_name_of_their_own(app_client, world, api_key_factory, mail):
    csrf = await owner(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/team", json={"email": "thay.nam@tt.vn", "name": "Thầy Nam", "role": "teacher"}, headers=h(csrf))
    assert r.status_code == 201 and r.json()["staff_ref"] == "thay-nam"


async def test_leaving_the_role_leaves_the_classes(world, school):
    u = await make_teacher(world, school["a"]["class"])
    async with tenant_session(world.t.id) as s:
        await change_role_or_status(s, await s.get(m.AppUser, u.id), role="staff", status=None, now=datetime.now(UTC))
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.ClassTeacher))).first() is None
        await change_role_or_status(s, await s.get(m.AppUser, u.id), role="teacher", status=None, now=datetime.now(UTC) + timedelta(seconds=1))


async def test_a_deleted_class_leaves_no_row_behind(app_client, world, api_key_factory, seed):
    sb = await seed(m.Sandbox(tenant_id=world.t.id, name="lesson_recap", purpose="lesson_recap", profile_ref="lesson_recapper@1"))
    c = await seed(m.Class(tenant_id=world.t.id, name="Lớp tạm", recap_sandbox_id=sb.id, source_kind="local", source_ref="/t"))
    await make_teacher(world, c)
    csrf = await owner(app_client, world, api_key_factory)
    assert (await app_client.delete(f"/api/v1/classes/{c.id}", headers=h(csrf))).status_code == 200
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.ClassTeacher))).first() is None


async def test_staff_have_no_part_in_the_classes(app_client, world, api_key_factory, school):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    app_client.cookies.clear()
    await sign_in(app_client, key)
    for path in ("/api/v1/classes", f"/api/v1/grading/{school['b']['item'].id}", "/api/v1/lessons", "/api/v1/assignments", "/api/v1/class-kinds", "/api/v1/google/picker"):
        r = await app_client.get(path)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "FORBIDDEN", path


async def test_the_owner_still_reaches_every_class(app_client, world, api_key_factory, school):
    _, key = await api_key_factory(world.t, "owner", None)
    app_client.cookies.clear()
    await sign_in(app_client, key)
    assert len((await app_client.get("/api/v1/classes")).json()["items"]) == 2
    assert (await app_client.get(f"/api/v1/grading/{school['b']['item'].id}")).status_code == 200


# --- the Drive picker on an account every class shares -----------------------------------------------
@pytest.fixture
def picker(monkeypatch):
    monkeypatch.setenv("CL_GOOGLE_PICKER_API_KEY", "AIza-x")
    monkeypatch.setenv("CL_GOOGLE_PROJECT_NUMBER", "123")
    get_settings.cache_clear()
    monkeypatch.setattr(ga, "new_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"access_token": "ya29.short", "expires_in": 3599}))))
    yield
    get_settings.cache_clear()


async def google_account(world, seed, label):
    secret = json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "rt"}).encode()
    return await seed(m.GoogleAccount(tenant_id=world.t.id, label=label, email=f"{label}@tt.vn", scopes=["drive.file"], connected_by="staff:owner",
                                      secret_enc=Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(secret)))


async def test_a_teacher_sees_only_the_account_of_their_class_and_may_not_browse_it(app_client, world, school, seed, picker):
    shared, other = await google_account(world, seed, "chung"), await google_account(world, seed, "rieng")
    async with tenant_session(world.t.id) as s:
        (await s.get(m.Class, school["a"]["class"].id)).classroom_account_id = shared.id
    await make_teacher(world, school["a"]["class"])
    await login(app_client)
    got = (await app_client.get(f"/api/v1/google/picker?class_id={school['a']['class'].id}")).json()
    assert [x["id"] for x in got["accounts"]] == [str(shared.id)] and got["default_account_id"] == str(shared.id) and got["browse"] is False
    assert (await app_client.get("/api/v1/google/picker")).json()["accounts"] == []  # no class: no address of any account
    assert (await app_client.get(f"/api/v1/google/picker?class_id={school['b']['class'].id}")).status_code == 404
    assert other


async def test_a_token_is_only_for_the_account_of_their_own_class(app_client, world, school, seed, picker):
    shared, other = await google_account(world, seed, "chung"), await google_account(world, seed, "rieng")
    async with tenant_session(world.t.id) as s:
        (await s.get(m.Class, school["a"]["class"].id)).classroom_account_id = shared.id
        (await s.get(m.Class, school["b"]["class"].id)).classroom_account_id = other.id
    await make_teacher(world, school["a"]["class"])
    csrf = await login(app_client)
    a, b = str(school["a"]["class"].id), str(school["b"]["class"].id)
    post = lambda body: app_client.post("/api/v1/google/picker/token", json=body, headers=h(csrf))
    assert (await post({"account_id": str(shared.id)})).status_code == 404  # no class said
    assert (await post({"account_id": str(other.id), "class_id": a})).status_code == 404  # not this class's account
    assert (await post({"account_id": str(other.id), "class_id": b})).status_code == 404  # not this teacher's class
    ok = await post({"account_id": str(shared.id), "class_id": a})
    assert ok.status_code == 200 and ok.json()["token"] == "ya29.short"
    async with tenant_session(world.t.id) as s:
        (e,) = (await s.execute(select(m.AuditEvent).where(m.AuditEvent.action == "google.picker_token"))).scalars().all()
    assert e.metadata_ == {"scope": "drive.file", "class_id": a} and e.actor == "staff:co-mai"


async def test_the_owner_keeps_the_whole_picker(app_client, world, api_key_factory, seed, picker):
    await google_account(world, seed, "chung")
    _, key = await api_key_factory(world.t, "owner", None)
    app_client.cookies.clear()
    await sign_in(app_client, key)
    got = (await app_client.get("/api/v1/google/picker")).json()
    assert got["browse"] is True and len(got["accounts"]) == 1
