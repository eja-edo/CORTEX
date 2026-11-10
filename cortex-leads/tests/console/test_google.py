"""WP37: connect a Google account from the console, then point Classroom courses and watched folders at it."""
import base64
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from support import h, sign_in

from cortex_leads.config import get_settings
from cortex_leads.connectors import google_accounts as ga
from cortex_leads.connectors.classroom import ClassroomError
from cortex_leads.connectors.drive_store import DriveError
from cortex_leads.console import google
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

SCOPE = "https://www.googleapis.com/auth/"
CLASSROOM = " ".join(SCOPE + x for x in ("classroom.courses.readonly", "classroom.coursework.students", "classroom.rosters.readonly", "drive.readonly"))
GOOGLE_ID_TOKEN = "x." + base64.urlsafe_b64encode(json.dumps({"email": "co.lan@truong.vn"}).encode()).decode().rstrip("=") + ".y"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    for k, v in {"CL_GOOGLE_OAUTH_CLIENT_ID": "cid.apps.googleusercontent.com", "CL_GOOGLE_OAUTH_CLIENT_SECRET": "csecret",
                 "CL_PUBLIC_BASE_URL": "https://cortex.example/app"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FakeGoogle:
    """Stands in for Google's token endpoint: hands out a refresh token carrying `scope`."""

    def __init__(self, scope: str, refresh: str | None = "rt-1") -> None:
        self.scope, self.refresh, self.seen = scope, refresh, []

    def __call__(self) -> httpx.AsyncClient:
        def answer(req: httpx.Request) -> httpx.Response:
            self.seen.append(str(req.url))
            if req.url.path.endswith("/revoke"):
                return httpx.Response(200)
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3600, "scope": self.scope, "id_token": GOOGLE_ID_TOKEN,
                                             **({"refresh_token": self.refresh} if self.refresh else {})})
        return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def owner(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "owner", None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


async def connect(app_client, csrf, monkeypatch, label="Google của cô Lan", kinds=("classroom",), scope=CLASSROOM, refresh="rt-1"):
    monkeypatch.setattr(ga, "new_http", FakeGoogle(scope, refresh))
    r = await app_client.post("/api/v1/google/accounts/connect", json={"label": label, "kinds": list(kinds)}, headers=h(csrf))
    assert r.status_code == 200, r.text
    query = parse_qs(urlsplit(r.json()["url"]).query)
    return query, await app_client.get("/api/v1/google/callback", params={"state": query["state"][0], "code": "the-code"}, follow_redirects=False)


@pytest.fixture
async def grader(world, seed):
    return await seed(m.Sandbox(tenant_id=world.t.id, name="classroom_grader", purpose="classroom_grader", profile_ref="classroom_grader@1", domain_pack={}))


@pytest.fixture
async def recapper(world, seed):
    return await seed(m.Sandbox(tenant_id=world.t.id, name="lesson_recap", purpose="lesson_recap", profile_ref="lesson_recapper@1", domain_pack={}))


async def test_the_server_must_be_set_up_before_anyone_can_connect(app_client, world, api_key_factory, monkeypatch):
    monkeypatch.setenv("CL_GOOGLE_OAUTH_CLIENT_ID", "")  # (a developer's own .env must not leak into the test)
    get_settings.cache_clear()
    csrf = await owner(app_client, world, api_key_factory)
    assert (await app_client.get("/api/v1/google/accounts")).json()["configured"] is False
    r = await app_client.post("/api/v1/google/accounts/connect", json={"label": "Cô Lan", "kinds": ["drive"]}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_CONFIGURED"


async def test_connecting_asks_google_only_for_what_was_ticked_and_stores_one_account(app_client, world, api_key_factory, monkeypatch):
    csrf = await owner(app_client, world, api_key_factory)
    query, back = await connect(app_client, csrf, monkeypatch)
    assert query["client_id"] == ["cid.apps.googleusercontent.com"] and query["redirect_uri"] == ["https://cortex.example/api/v1/google/callback"]
    assert SCOPE + "classroom.courses.readonly" in query["scope"][0] and SCOPE + "drive.file" not in query["scope"][0]
    assert query["code_challenge_method"] == ["S256"] and query["access_type"] == ["offline"]
    assert back.status_code == 303 and "connected=" in back.headers["location"] and back.headers["location"].startswith("/app/settings?")
    items = (await app_client.get("/api/v1/google/accounts")).json()["items"]
    assert [(a["label"], a["email"], a["status"], a["can"]) for a in items] == [("Google của cô Lan", "co.lan@truong.vn", "active", {"classroom": True, "classroom_post": False, "classroom_create": False, "drive": False, "drive_read": True})]
    assert "rt-1" not in json.dumps(items)
    async with tenant_session(world.t.id) as s:
        acct = (await s.execute(select(m.GoogleAccount))).scalar_one()
    assert json.loads(Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(acct.secret_enc))["refresh_token"] == "rt-1" and b"rt-1" not in acct.secret_enc


async def test_a_forged_or_old_state_and_a_refusal_at_google_connect_nothing(app_client, world, api_key_factory, monkeypatch):
    csrf = await owner(app_client, world, api_key_factory)
    assert "error=BAD_STATE" in (await app_client.get("/api/v1/google/callback", params={"state": "forged", "code": "c"}, follow_redirects=False)).headers["location"]
    started = await app_client.post("/api/v1/google/accounts/connect", json={"label": "Một", "kinds": ["drive"]}, headers=h(csrf))
    query = parse_qs(urlsplit(started.json()["url"]).query)
    r = await app_client.get("/api/v1/google/callback", params={"state": query["state"][0], "error": "access_denied"}, follow_redirects=False)
    assert "error=DENIED" in r.headers["location"]
    _, r = await connect(app_client, csrf, monkeypatch, label="Hai", refresh=None)
    assert "error=NO_REFRESH_TOKEN" in r.headers["location"]
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.GoogleAccount))).first() is None


async def test_a_course_needs_an_account_that_was_given_classroom_and_then_follows_the_account(app_client, world, api_key_factory, grader, recapper, monkeypatch):
    csrf = await owner(app_client, world, api_key_factory)
    await connect(app_client, csrf, monkeypatch, label="Chỉ Drive", kinds=("drive",), scope=SCOPE + "drive.file")
    await connect(app_client, csrf, monkeypatch, label="Cô Lan")
    ids = {a["label"]: a["id"] for a in (await app_client.get("/api/v1/google/accounts")).json()["items"]}
    body = {"sandbox_id": str(grader.id), "account_id": ids["Chỉ Drive"], "course_id": "111", "label": "Lớp 6A"}
    r = await app_client.post("/api/v1/google/classroom-sources", json=body, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MISSING_SCOPE"
    assert (await app_client.post("/api/v1/google/classroom-sources", json={**body, "sandbox_id": str(recapper.id), "account_id": ids["Cô Lan"]}, headers=h(csrf))).status_code == 422
    assert (await app_client.post("/api/v1/google/classroom-sources", json={**body, "account_id": ids["Cô Lan"]}, headers=h(csrf))).status_code == 201
    assert (await app_client.post("/api/v1/google/classroom-sources", json={**body, "account_id": ids["Cô Lan"]}, headers=h(csrf))).status_code == 201  # again: no duplicate
    async with tenant_session(world.t.id) as s:
        src = (await s.execute(select(m.Class))).scalar_one()
        assert src.classroom_secret_enc is None and src.classroom_account.label == "Cô Lan" and src.auth_kind == "oauth" and src.grader_sandbox_id is not None
        assert json.loads(ga.secret_of_account(src.classroom_account, ClassroomError("UNAUTHENTICATED")))["refresh_token"] == "rt-1"
    used = (await app_client.get("/api/v1/google/accounts")).json()["items"]
    lan = next(u for u in used if u["label"] == "Cô Lan")
    assert [(x["kind"], x["name"]) for x in lan["used_by"]] == [("classroom", "Lớp 6A")]
    assert next(u for u in used if u["label"] == "Chỉ Drive")["used_by"] == []


async def test_two_accounts_can_serve_two_courses_of_the_same_sandbox(app_client, world, api_key_factory, grader, monkeypatch):
    csrf = await owner(app_client, world, api_key_factory)
    await connect(app_client, csrf, monkeypatch, label="Cô Lan", refresh="rt-lan")
    await connect(app_client, csrf, monkeypatch, label="Thầy Minh", refresh="rt-minh")
    ids = {a["label"]: a["id"] for a in (await app_client.get("/api/v1/google/accounts")).json()["items"]}
    for who, course in (("Cô Lan", "111"), ("Thầy Minh", "222")):
        r = await app_client.post("/api/v1/google/classroom-sources", json={"sandbox_id": str(grader.id), "account_id": ids[who], "course_id": course}, headers=h(csrf))
        assert r.status_code == 201
    async with tenant_session(world.t.id) as s:
        got = {x.course_id: json.loads(ga.secret_of_account(x.classroom_account, ClassroomError("X")))["refresh_token"] for x in (await s.execute(select(m.Class))).scalars()}
    assert got == {"111": "rt-lan", "222": "rt-minh"}


async def test_revoking_ends_every_source_that_used_the_account_and_keeps_their_history(app_client, world, api_key_factory, grader, recapper, monkeypatch):
    csrf = await owner(app_client, world, api_key_factory)
    fake = FakeGoogle(CLASSROOM + " " + SCOPE + "drive.file")
    monkeypatch.setattr(ga, "new_http", fake)
    await connect(app_client, csrf, monkeypatch, label="Cô Lan", kinds=("classroom", "drive"), scope=CLASSROOM + " " + SCOPE + "drive.file")
    acct = (await app_client.get("/api/v1/google/accounts")).json()["items"][0]
    assert acct["can"] == {"classroom": True, "classroom_post": False, "classroom_create": False, "drive": True, "drive_read": True}
    await app_client.post("/api/v1/google/classroom-sources", json={"sandbox_id": str(grader.id), "account_id": acct["id"], "course_id": "111"}, headers=h(csrf))
    r = await app_client.post("/api/v1/google/lesson-sources", json={"sandbox_id": str(recapper.id), "account_id": acct["id"], "folder_id": "F" * 12}, headers=h(csrf))
    assert r.status_code == 201
    monkeypatch.setattr(ga, "new_http", fake)
    out = (await app_client.post(f"/api/v1/google/accounts/{acct['id']}/revoke", headers=h(csrf))).json()
    assert out["status"] == "revoked" and not any(out["can"].values())
    assert any(u.endswith("/revoke") for u in fake.seen)
    async with tenant_session(world.t.id) as s:
        src = (await s.execute(select(m.Class).where(m.Class.grader_sandbox_id.is_not(None)))).scalar_one()
        target = (await s.execute(select(m.Class).where(m.Class.recap_sandbox_id.is_not(None)))).scalar_one()
        for account, err in ((src.classroom_account, ClassroomError("UNAUTHENTICATED")), (target.drive_account, DriveError("UNAUTHENTICATED"))):
            with pytest.raises(type(err)):
                ga.secret_of_account(account, err)
    r = await app_client.post("/api/v1/google/classroom-sources", json={"sandbox_id": str(grader.id), "account_id": acct["id"], "course_id": "333"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ACCOUNT_REVOKED"


async def test_the_courses_of_an_account_come_from_classroom(app_client, world, api_key_factory, grader, monkeypatch):
    csrf = await owner(app_client, world, api_key_factory)
    await connect(app_client, csrf, monkeypatch)
    acct = (await app_client.get("/api/v1/google/accounts")).json()["items"][0]

    class Fake:
        async def courses(self):
            return [{"id": "111", "name": "Tiếng Anh 6A", "section": "Sáng"}, {"id": "222", "name": "Tiếng Anh 7B"}]

    monkeypatch.setattr(google, "_classroom", lambda secret: Fake())
    await app_client.post("/api/v1/google/classroom-sources", json={"sandbox_id": str(grader.id), "account_id": acct["id"], "course_id": "111"}, headers=h(csrf))
    items = (await app_client.get(f"/api/v1/google/accounts/{acct['id']}/courses")).json()["items"]
    assert [(c["id"], c["connected"]) for c in items] == [("111", True), ("222", False)]

    class Expired:
        async def courses(self):
            raise ClassroomError("UNAUTHENTICATED")

    monkeypatch.setattr(google, "_classroom", lambda secret: Expired())
    r = await app_client.get(f"/api/v1/google/accounts/{acct['id']}/courses")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "UNAUTHENTICATED"


async def test_a_recordings_folder_is_watched_with_the_account_and_read_as_that_teacher(app_client, world, api_key_factory, recapper, monkeypatch):
    from cortex_leads.lessons import job
    from cortex_leads.connectors.lesson_sources import DriveFolder

    csrf = await owner(app_client, world, api_key_factory)
    await connect(app_client, csrf, monkeypatch, label="Cô Lan", kinds=("drive_read",), scope=SCOPE + "drive.readonly", refresh="rt-lan")
    acct = (await app_client.get("/api/v1/google/accounts")).json()["items"][0]
    assert acct["can"] == {"classroom": False, "classroom_post": False, "classroom_create": False, "drive": False, "drive_read": True}

    class Fake:
        async def folders(self):
            return [{"id": "F" * 12, "name": "Meet Recordings"}]

    monkeypatch.setattr(google, "_classroom", lambda secret: Fake())
    got = (await app_client.get(f"/api/v1/google/accounts/{acct['id']}/folders")).json()
    assert got["items"] == [{"id": "F" * 12, "name": "Meet Recordings", "connected": False}]
    body = {"sandbox_id": str(recapper.id), "account_id": acct["id"], "folder_id": "F" * 12, "label": "Meet Recordings"}
    assert (await app_client.post("/api/v1/google/lesson-sources", json={**body, "folder_id": "../x"}, headers=h(csrf))).status_code == 422
    assert (await app_client.post("/api/v1/google/lesson-sources", json=body, headers=h(csrf))).status_code == 201
    assert (await app_client.post("/api/v1/google/lesson-sources", json=body, headers=h(csrf))).status_code == 201  # again: one row
    async with tenant_session(world.t.id) as s:
        src = (await s.execute(select(m.Class))).scalar_one()
        assert src.source_secret_enc is None and src.drive_account.label == "Cô Lan" and src.active
        opened = job.open_source(src, httpx.AsyncClient())
    assert isinstance(opened, DriveFolder)
    sources = (await app_client.get("/api/v1/google/accounts")).json()["sources"]
    assert [(x["kind"], x["name"], x["account"], x["legacy"]) for x in sources] == [("folder", "Meet Recordings", "Cô Lan", False)]


async def test_an_old_command_line_source_is_listed_as_old_and_can_never_be_switched_on(app_client, world, api_key_factory, grader, seed, monkeypatch):
    csrf = await owner(app_client, world, api_key_factory)
    old = await seed(m.Class(tenant_id=world.t.id, grader_sandbox_id=grader.id, course_id="999", auth_kind="oauth", name="lớp cũ", classroom_secret_enc=b"x"))
    sources = (await app_client.get("/api/v1/google/accounts")).json()["sources"]
    assert [(x["name"], x["account"], x["legacy"], x["active"]) for x in sources] == [("lớp cũ", None, True, True)]
    r = await app_client.post(f"/api/v1/google/sources/classroom/{old.id}/active", json={"active": False}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["active"] is False
    async with tenant_session(world.t.id) as s:
        assert (await s.get(m.Class, old.id)).active is False
    r = await app_client.post(f"/api/v1/google/sources/classroom/{old.id}/active", json={"active": True}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LEGACY_SOURCE"  # nothing reads a key-only source any more
    zero = "00000000-0000-0000-0000-000000000000"
    assert (await app_client.post(f"/api/v1/google/sources/folder/{zero}/active", json={"active": False}, headers=h(csrf))).status_code == 404


async def test_a_source_with_no_account_is_never_opened_and_says_a_sign_in_is_needed(world, grader, recapper, seed):
    """Nothing reads a command-line key any more: the jobs treat such a source as an expired sign-in."""
    from cortex_leads.grader import job as grader_job
    from cortex_leads.lessons import job as lessons_job

    src = await seed(m.Class(tenant_id=world.t.id, name="1", grader_sandbox_id=grader.id, course_id="1", auth_kind="oauth", classroom_secret_enc=b"x"))
    folder = await seed(m.Class(tenant_id=world.t.id, recap_sandbox_id=recapper.id, source_kind="drive", source_ref="F" * 12, source_secret_enc=b"x", name="F" * 12, listed=False, recap_mode="auto"))
    async with tenant_session(world.t.id) as s:
        with pytest.raises(ClassroomError):
            grader_job.open_source(await s.get(m.Class, src.id))
        with pytest.raises(DriveError):
            lessons_job.open_source(await s.get(m.Class, folder.id), httpx.AsyncClient())


async def accounts_of(world):
    async with tenant_session(world.t.id) as s:
        return list((await s.execute(select(m.GoogleAccount).order_by(m.GoogleAccount.created_at))).scalars())


async def test_signing_the_same_account_in_again_keeps_everything_that_uses_it(app_client, world, api_key_factory, monkeypatch, grader, seed):
    csrf = await owner(app_client, world, api_key_factory)
    await connect(app_client, csrf, monkeypatch)
    (acct,) = await accounts_of(world)
    src = await seed(m.Class(tenant_id=world.t.id, name="123", grader_sandbox_id=grader.id, course_id="123", auth_kind="oauth", classroom_account_id=acct.id))
    monkeypatch.setattr(ga, "new_http", FakeGoogle(CLASSROOM + " " + SCOPE + "classroom.announcements", "rt-2"))
    r = await app_client.post(f"/api/v1/google/accounts/{acct.id}/reconnect", json={"kinds": ["classroom", "classroom_post"]}, headers=h(csrf))
    assert r.status_code == 200, r.text
    query = parse_qs(urlsplit(r.json()["url"]).query)
    assert SCOPE + "classroom.announcements" in query["scope"][0]
    back = await app_client.get("/api/v1/google/callback", params={"state": query["state"][0], "code": "c"}, follow_redirects=False)
    assert back.status_code == 303 and "error" not in back.headers["location"]
    (again,) = await accounts_of(world)  # the same row, not a second account
    assert again.id == acct.id and "classroom.announcements" in again.scopes
    assert json.loads(Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(again.secret_enc))["refresh_token"] == "rt-2"
    async with tenant_session(world.t.id) as s:
        assert (await s.get(m.Class, src.id)).classroom_account_id == acct.id


async def test_a_different_google_user_cannot_take_over_an_account(app_client, world, api_key_factory, monkeypatch):
    csrf = await owner(app_client, world, api_key_factory)
    await connect(app_client, csrf, monkeypatch)
    (acct,) = await accounts_of(world)
    other = "x." + base64.urlsafe_b64encode(json.dumps({"email": "nguoi.la@gmail.com"}).encode()).decode().rstrip("=") + ".y"
    monkeypatch.setattr(ga, "new_http", FakeGoogle(CLASSROOM, "rt-9"))
    monkeypatch.setattr(ga, "_email_of", lambda t: "nguoi.la@gmail.com")
    r = await app_client.post(f"/api/v1/google/accounts/{acct.id}/reconnect", json={"kinds": ["classroom"]}, headers=h(csrf))
    query = parse_qs(urlsplit(r.json()["url"]).query)
    back = await app_client.get("/api/v1/google/callback", params={"state": query["state"][0], "code": "c"}, follow_redirects=False)
    assert "error=OTHER_ACCOUNT" in back.headers["location"] and other
    assert json.loads(Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt((await accounts_of(world))[0].secret_enc))["refresh_token"] == "rt-1"


async def test_deleting_an_account_keeps_what_used_it_and_leaves_it_waiting_for_a_new_sign_in(app_client, world, api_key_factory, monkeypatch, grader, recapper, seed):
    csrf = await owner(app_client, world, api_key_factory)
    await connect(app_client, csrf, monkeypatch)
    await connect(app_client, csrf, monkeypatch, label="Tài khoản dự phòng")
    old, new = await accounts_of(world)
    course = await seed(m.Class(tenant_id=world.t.id, name="Lớp chấm", grader_sandbox_id=grader.id, course_id="123", auth_kind="oauth", classroom_account_id=old.id))
    made = await seed(m.Class(tenant_id=world.t.id, recap_sandbox_id=recapper.id, source_kind="drive", source_ref="f1", name="Lớp có thư mục", drive_account_id=old.id, owned=True, recap_mode="auto"))
    lesson = await seed(m.Lesson(tenant_id=world.t.id, sandbox_id=recapper.id, class_id=made.id, file_id="x", name="buổi 1.mp4", status="done"))
    r = await app_client.delete(f"/api/v1/google/accounts/{old.id}", headers=h(csrf))
    assert r.status_code == 200 and r.json()["sources"] == 2
    assert [a.label for a in await accounts_of(world)] == ["Tài khoản dự phòng"]
    async with tenant_session(world.t.id) as s:  # nothing was deleted with it: the class, its lessons and the graded course are still there
        assert (await s.get(m.Class, course.id)).classroom_account_id is None
        assert (await s.get(m.Class, made.id)).drive_account_id is None and await s.get(m.Lesson, lesson.id) is not None
    (row,) = [c for c in (await app_client.get("/api/v1/classes")).json()["items"] if c["id"] == str(made.id)]  # still listed, saying it is cut off
    assert row["account"] is None and row["linked"] is False and row["can_upload"] is False
    refused = await app_client.post(f"/api/v1/classes/{made.id}/relink", json={"account_id": str(new.id), "folder": "new"}, headers=h(csrf))
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "MISSING_SCOPE"  # a new folder needs the Drive permission, which the stand-in account lacks
    linked = await app_client.post(f"/api/v1/classes/{made.id}/relink", json={"account_id": str(new.id), "folder": "folder2"}, headers=h(csrf))
    assert linked.status_code == 200 and (linked.json()["account"], linked.json()["linked"], linked.json()["owned"]) == ("Tài khoản dự phòng", True, False)
    async with tenant_session(world.t.id) as s:
        assert (await s.get(m.Class, made.id)).source_ref == "folder2" and await s.get(m.Lesson, lesson.id) is not None  # its lessons stayed
