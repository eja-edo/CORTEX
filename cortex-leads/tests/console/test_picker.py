"""The Drive picker (WP44): a short-lived, narrowed access token for the browser, and nothing else of a Google sign-in."""
import json

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from support import h, sign_in

from cortex_leads.config import get_settings
from cortex_leads.connectors import google_accounts as ga
from cortex_leads.console import spa
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

KEY, APP = "AIza-browser-key", "123456789012"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("CL_GOOGLE_PICKER_API_KEY", KEY)
    monkeypatch.setenv("CL_GOOGLE_PROJECT_NUMBER", APP)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def google(monkeypatch):
    """A fake Google token endpoint that records what a refresh asked for."""
    asked: list[dict[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        asked.append(form)
        if form.get("refresh_token") == "revoked":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"access_token": "ya29.short", "expires_in": 3599})

    monkeypatch.setattr(ga, "new_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    return asked


async def as_(app_client, world, api_key_factory, role="owner"):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


async def account(world, seed, scopes=("drive.file", "classroom.courses.readonly"), label="Cô Lan", refresh="rt-1", email="co.lan@truong.vn"):
    secret = json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": refresh}).encode()
    return await seed(m.GoogleAccount(tenant_id=world.t.id, label=label, email=email, scopes=list(scopes), connected_by="staff:owner",
                                      secret_enc=Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(secret)))


async def test_the_browser_gets_a_token_narrowed_to_drive_file_and_never_the_refresh_token(app_client, world, api_key_factory, seed, on, google):
    a = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/google/picker/token", json={"account_id": str(a.id)}, headers=h(csrf))
    assert r.status_code == 200
    body = r.json()
    assert body == {"token": "ya29.short", "expires_in": 3599, "api_key": KEY, "app_id": APP, "email": "co.lan@truong.vn"}
    assert "rt-1" not in r.text and "refresh" not in r.text  # the long-lived secret stays on the server
    assert google[0]["scope"].endswith("drive.file") and "classroom" not in google[0]["scope"]  # Google was asked for the narrow permission only


async def test_each_token_is_in_the_trail_without_the_token(app_client, world, api_key_factory, seed, on, google):
    a = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    await app_client.post("/api/v1/google/picker/token", json={"account_id": str(a.id)}, headers=h(csrf))
    async with tenant_session(world.t.id) as s:
        (e,) = (await s.execute(select(m.AuditEvent).where(m.AuditEvent.action == "google.picker_token"))).scalars().all()
    assert "ya29" not in json.dumps([e.summary, e.metadata_]) and e.metadata_ == {"scope": "drive.file"}


async def test_nothing_is_handed_out_until_the_picker_is_configured(app_client, world, api_key_factory, seed, google):
    a = await account(world, seed)
    csrf = await as_(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/google/picker/token", json={"account_id": str(a.id)}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PICKER_NOT_CONFIGURED" and google == []
    assert (await app_client.get("/api/v1/google/picker")).json()["configured"] is False


async def test_an_account_without_the_drive_permission_or_with_a_revoked_sign_in_is_refused(app_client, world, api_key_factory, seed, on, google):
    no_drive = await account(world, seed, scopes=("classroom.courses.readonly",), label="Chỉ Classroom")
    gone = await account(world, seed, label="Bị thu hồi", refresh="revoked")
    csrf = await as_(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/google/picker/token", json={"account_id": str(no_drive.id)}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MISSING_SCOPE" and google == []
    r = await app_client.post("/api/v1/google/picker/token", json={"account_id": str(gone.id)}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "UNAUTHENTICATED"
    r = await app_client.post("/api/v1/google/picker/token", json={"account_id": "00000000-0000-0000-0000-000000000000"}, headers=h(csrf))
    assert r.status_code == 404


async def test_the_form_is_told_which_accounts_can_open_the_picker_and_which_to_start_with(app_client, world, api_key_factory, seed, on):
    await account(world, seed, scopes=("classroom.courses.readonly",), label="A chỉ Classroom")
    drive = await account(world, seed, label="B có Drive", email="b@truong.vn")
    csrf = await as_(app_client, world, api_key_factory)
    got = (await app_client.get("/api/v1/google/picker")).json()
    assert got["configured"] is True and got["default_account_id"] == str(drive.id)
    assert {x["label"]: x["can_pick"] for x in got["accounts"]} == {"A chỉ Classroom": False, "B có Drive": True}
    assert all(set(x) == {"id", "label", "email", "can_pick"} for x in got["accounts"])  # no secret field exists to leak
    assert csrf


async def test_a_class_starts_with_the_account_that_acts_in_its_classroom_course(app_client, world, api_key_factory, seed, on):
    other = await account(world, seed, label="Cô khác")
    mine = await account(world, seed, label="Cô của lớp")
    sb = await seed(m.Sandbox(tenant_id=world.t.id, name="classroom_grader", purpose="classroom_grader", profile_ref="classroom_grader@1"))
    cls = await seed(m.Class(tenant_id=world.t.id, name="Lớp A", grader_sandbox_id=sb.id, course_id="c1", auth_kind="oauth", classroom_account_id=mine.id))
    await as_(app_client, world, api_key_factory)
    assert (await app_client.get("/api/v1/google/picker")).json()["default_account_id"] == str(other.id)  # no class: the first that can
    assert (await app_client.get(f"/api/v1/google/picker?class_id={cls.id}")).json()["default_account_id"] == str(mine.id)
    assert (await app_client.get("/api/v1/google/picker?class_id=00000000-0000-0000-0000-000000000000")).status_code == 404


def test_the_page_may_load_googles_dialog_only_when_the_picker_is_configured(monkeypatch):
    get_settings.cache_clear()
    assert "apis.google.com" not in spa.csp()
    monkeypatch.setenv("CL_GOOGLE_PICKER_API_KEY", KEY)
    monkeypatch.setenv("CL_GOOGLE_PROJECT_NUMBER", APP)
    get_settings.cache_clear()
    try:
        assert "https://apis.google.com" in spa.csp() and "frame-src https://docs.google.com" in spa.csp() and "frame-ancestors 'none'" in spa.csp()
    finally:
        get_settings.cache_clear()
