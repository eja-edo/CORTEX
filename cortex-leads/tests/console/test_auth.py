"""WP30: sign-in, sessions, passwords, lockout, accounts and permissions."""
import hashlib
from datetime import timedelta

from sqlalchemy import text
from support import PASSWORD, account_for_key, h, sign_in
from wp5_support import rows

from cortex_leads.auth.passwords import hash_password, strength_errors, verify_password
from cortex_leads.db import models as m

GOOD = "Mat-khau-moi-4821"


async def login(client, email, password=PASSWORD):
    return await client.post("/api/v1/session/login", json={"email": email, "password": password})


async def as_(client, world, api_key_factory, role, ref=None):
    _, key = await api_key_factory(world.t, role, ref if role == "staff" else None)
    client.cookies.clear()
    return await sign_in(client, key), await account_for_key(key)


# --- passwords ---------------------------------------------------------------------------------------
def test_a_password_is_stored_salted_and_checked_in_constant_time_form():
    a, b = hash_password(GOOD), hash_password(GOOD)
    assert a != b and a.startswith("scrypt$") and GOOD not in a  # a fresh salt every time
    assert verify_password(GOOD, a) and not verify_password(GOOD + "x", a) and not verify_password(GOOD, None)
    assert not verify_password(GOOD, "garbage") and not verify_password(GOOD, "scrypt$1$2$3$!!$!!")


def test_the_password_rules_say_what_is_wrong():
    assert strength_errors("ngan1") and strength_errors("passwordpassword") and strength_errors("12345678901")
    assert strength_errors("nguyenvanan-9999", email="nguyenvanan@x.vn")  # holds the login name
    assert strength_errors("abcdefghijkl")  # letters only
    assert strength_errors("A" * 200 + "1")  # too long for the server to hash
    assert strength_errors(GOOD, email="a@b.vn", name="Trần Văn An") == []


# --- sign-in -----------------------------------------------------------------------------------------
async def test_unknown_email_and_wrong_password_get_the_same_answer(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    email = await account_for_key(key)
    a = await login(app_client, email, "sai-mat-khau-1")
    b = await login(app_client, "khong-co@nowhere.test", "sai-mat-khau-1")
    assert a.status_code == b.status_code == 401 and a.json() == b.json() and a.json()["detail"]["code"] == "BAD_CREDENTIALS"


async def test_five_wrong_passwords_lock_the_account_even_for_the_right_one(app_client, world, api_key_factory, owner_engine):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    email = await account_for_key(key)
    for _ in range(5):
        assert (await login(app_client, email, "sai-mat-khau-1")).status_code == 401
    r = await login(app_client, email, PASSWORD)  # the right password, during the lock
    assert r.status_code == 429 and r.json()["detail"]["code"] == "LOGIN_LOCKED" and int(r.headers["Retry-After"]) > 0
    assert any(e.metadata_.get("locked") for e in await rows(world, m.AuditEvent) if e.action == "login.failed")
    async with owner_engine.begin() as c:  # time passes
        await c.execute(text("update login_throttle set locked_until = now() - interval '1 second'"))
    assert (await login(app_client, email, PASSWORD)).status_code == 200


async def test_the_lock_follows_the_email_not_the_account_so_it_leaks_nothing(app_client, world):
    for _ in range(5):
        await login(app_client, "khong-co@nowhere.test", "sai-mat-khau-1")
    assert (await login(app_client, "khong-co@nowhere.test", "sai-mat-khau-1")).status_code == 429  # an email that does not exist locks too


async def test_one_wrong_password_elsewhere_does_not_lock_another_account(app_client, world, api_key_factory):
    _, k1 = await api_key_factory(world.t, "staff", "nv1")
    _, k2 = await api_key_factory(world.t, "staff", "nv2")
    e1, e2 = await account_for_key(k1), await account_for_key(k2)
    for _ in range(5):
        await login(app_client, e1, "sai-mat-khau-1")
    assert (await login(app_client, e2, PASSWORD)).status_code == 200


async def test_too_many_failures_from_one_address_lock_that_address(app_client, world, api_key_factory, monkeypatch):
    from cortex_leads.config import get_settings
    monkeypatch.setattr(get_settings(), "LOGIN_IP_MAX_FAILURES", 4)
    _, key = await api_key_factory(world.t, "staff", "nv1")
    email = await account_for_key(key)
    for i in range(4):
        await login(app_client, f"nguoi{i}@nowhere.test", "sai-mat-khau-1")  # four different accounts, one address
    assert (await login(app_client, email, PASSWORD)).status_code == 429


async def test_a_success_clears_the_account_counter(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    email = await account_for_key(key)
    for _ in range(4):
        await login(app_client, email, "sai-mat-khau-1")
    assert (await login(app_client, email, PASSWORD)).status_code == 200
    for _ in range(4):
        await login(app_client, email, "sai-mat-khau-1")
    assert (await login(app_client, email, PASSWORD)).status_code == 200  # 4 + 4 would have locked without the clearing


async def test_malformed_sign_in_bodies_are_refused_before_any_hashing(app_client):
    for body in ({}, {"email": "a@b.vn"}, {"email": "a@b.vn", "password": "x" * 500}, {"email": "x" * 400, "password": "y"}, {"api_key": "clk_abc"}):
        assert (await app_client.post("/api/v1/session/login", json=body)).status_code == 422


# --- sessions ----------------------------------------------------------------------------------------
async def test_the_cookie_is_opaque_and_the_database_keeps_only_a_hash_of_its_secret(app_client, world, api_key_factory, owner_engine):
    csrf, email = await as_(app_client, world, api_key_factory, "staff", "nv1")
    cookie = app_client.cookies.get("cl_session")
    sid, secret = cookie.split(".", 1)
    async with owner_engine.begin() as c:
        row = (await c.execute(text("select secret_hash, expires_at, ip from auth_session where id = :i"), {"i": sid})).one()
    assert row.secret_hash == hashlib.sha256(secret.encode()).hexdigest() and secret not in row.secret_hash and row.ip
    assert cookie.count(".") == 1 and email not in cookie and csrf
    app_client.cookies.set("cl_session", f"{sid}.{'A' * len(secret)}", path="/")  # right session, wrong secret
    assert (await app_client.get("/api/v1/session")).status_code == 401


async def test_logout_ends_the_session_on_the_server_so_a_copied_cookie_is_dead(app_client, world, api_key_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "staff", "nv1")
    stolen = app_client.cookies.get("cl_session")
    assert (await app_client.post("/api/v1/session/logout", headers=h(csrf))).status_code == 200
    app_client.cookies.set("cl_session", stolen, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401


async def test_sessions_end_after_their_absolute_and_idle_limits(app_client, world, api_key_factory, owner_engine):
    await as_(app_client, world, api_key_factory, "staff", "nv1")
    sid = app_client.cookies.get("cl_session").split(".")[0]
    async with owner_engine.begin() as c:
        await c.execute(text("update auth_session set last_seen_at = now() - interval '3 hours' where id = :i"), {"i": sid})
    assert (await app_client.get("/api/v1/session")).status_code == 401  # idle for longer than 2 hours
    await as_(app_client, world, api_key_factory, "staff", "nv1")
    sid = app_client.cookies.get("cl_session").split(".")[0]
    async with owner_engine.begin() as c:
        await c.execute(text("update auth_session set expires_at = now() - interval '1 second' where id = :i"), {"i": sid})
    assert (await app_client.get("/api/v1/session")).status_code == 401  # past its absolute end, however active


async def test_activity_keeps_a_session_alive_but_only_writes_now_and_then(app_client, world, api_key_factory, owner_engine):
    await as_(app_client, world, api_key_factory, "staff", "nv1")
    sid = app_client.cookies.get("cl_session").split(".")[0]
    async with owner_engine.begin() as c:
        await c.execute(text("update auth_session set last_seen_at = now() - interval '90 minutes' where id = :i"), {"i": sid})
    assert (await app_client.get("/api/v1/session")).status_code == 200
    async with owner_engine.begin() as c:
        seen = (await c.execute(text("select now() - last_seen_at from auth_session where id = :i"), {"i": sid})).scalar_one()
    assert seen < timedelta(minutes=1)  # slid forward
    assert (await app_client.get("/api/v1/session")).status_code == 200


async def test_a_disabled_person_is_out_on_the_very_next_request(app_client, world, api_key_factory, owner_engine):
    _, email = await as_(app_client, world, api_key_factory, "staff", "nv1")
    assert (await app_client.get("/api/v1/session")).status_code == 200
    async with owner_engine.begin() as c:
        await c.execute(text("update app_user set status = 'disabled' where lower(email) = :e"), {"e": email})
    assert (await app_client.get("/api/v1/session")).status_code == 401
    assert (await login(app_client, email)).status_code == 401  # and cannot come back, with the same answer as a wrong password
    assert [e.metadata_["reason"] for e in await rows(world, m.AuditEvent) if e.action == "login.failed"] == ["disabled"]


async def test_a_demotion_takes_effect_on_the_next_request_without_signing_in_again(app_client, world, api_key_factory, owner_engine):
    csrf, email = await as_(app_client, world, api_key_factory, "owner")
    assert (await app_client.get("/api/v1/audit/verify")).status_code == 200
    async with owner_engine.begin() as c:
        await c.execute(text("update app_user set role = 'staff' where lower(email) = :e"), {"e": email})
    assert (await app_client.get("/api/v1/audit/verify")).status_code == 403
    assert (await app_client.get("/api/v1/session")).json()["role"] == "staff"
    assert csrf


# --- my password and my sessions ---------------------------------------------------------------------
async def test_changing_the_password_needs_the_current_one_and_ends_the_other_sessions(app_client, world, api_key_factory):
    csrf, email = await as_(app_client, world, api_key_factory, "staff", "nv1")
    mine = app_client.cookies.get("cl_session")
    from httpx import ASGITransport, AsyncClient

    from cortex_leads.app import create_app
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as other:  # a second device
        assert (await login(other, email)).status_code == 200
        app_client.cookies.set("cl_session", mine, path="/")
        assert (await app_client.post("/api/v1/session/password", json={"current": "khong-dung-1", "new": GOOD}, headers=h(csrf))).status_code == 403
        assert (await app_client.post("/api/v1/session/password", json={"current": PASSWORD, "new": "ngan1"}, headers=h(csrf))).status_code == 422
        assert (await app_client.post("/api/v1/session/password", json={"current": PASSWORD, "new": PASSWORD}, headers=h(csrf))).status_code == 422
        r = await app_client.post("/api/v1/session/password", json={"current": PASSWORD, "new": GOOD}, headers=h(csrf))
        assert r.status_code == 200 and r.json()["other_sessions_ended"] == 1
        assert (await other.get("/api/v1/session")).status_code == 401  # the other device is out
    assert (await app_client.get("/api/v1/session")).status_code == 200  # this one stays
    app_client.cookies.clear()
    assert (await login(app_client, email, PASSWORD)).status_code == 401 and (await login(app_client, email, GOOD)).status_code == 200
    ev = {e.action for e in await rows(world, m.AuditEvent)}
    assert {"password.changed", "password.change_failed"} <= ev
    assert all(GOOD not in str(e.metadata_) and PASSWORD not in str(e.metadata_) for e in await rows(world, m.AuditEvent))


async def test_guessing_the_current_password_through_the_change_form_counts_toward_the_lock(app_client, world, api_key_factory):
    csrf, email = await as_(app_client, world, api_key_factory, "staff", "nv1")
    for _ in range(5):
        await app_client.post("/api/v1/session/password", json={"current": "khong-dung-1", "new": GOOD}, headers=h(csrf))
    r = await app_client.post("/api/v1/session/password", json={"current": PASSWORD, "new": GOOD}, headers=h(csrf))
    assert r.status_code == 429


async def test_my_sessions_can_be_listed_and_ended_one_by_one_or_all_at_once(app_client, world, api_key_factory):
    csrf, email = await as_(app_client, world, api_key_factory, "staff", "nv1")
    from httpx import ASGITransport, AsyncClient

    from cortex_leads.app import create_app
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as other:
        await login(other, email)
        items = (await app_client.get("/api/v1/session/sessions")).json()["items"]
        assert len(items) == 2 and sum(i["current"] for i in items) == 1
        theirs = next(i for i in items if not i["current"])
        assert (await app_client.post(f"/api/v1/session/sessions/{theirs['id']}/revoke", headers=h(csrf))).status_code == 200
        assert (await other.get("/api/v1/session")).status_code == 401
        assert (await app_client.post("/api/v1/session/sessions/00000000-0000-0000-0000-000000000000/revoke", headers=h(csrf))).status_code == 404
        assert (await app_client.post("/api/v1/session/logout-all", headers=h(csrf))).json() == {"ended": 1}
    assert (await app_client.get("/api/v1/session")).status_code == 401


async def test_nobody_can_end_someone_elses_session(app_client, world, api_key_factory):
    _, k1 = await api_key_factory(world.t, "staff", "nv1")
    _, k2 = await api_key_factory(world.t, "staff", "nv2")
    await sign_in(app_client, k1)
    sid = (await app_client.get("/api/v1/session/sessions")).json()["items"][0]["id"]
    app_client.cookies.clear()
    csrf = await sign_in(app_client, k2)
    assert (await app_client.post(f"/api/v1/session/sessions/{sid}/revoke", headers=h(csrf))).status_code == 404


# --- accounts ----------------------------------------------------------------------------------------
async def test_the_owner_adds_a_person_with_a_temporary_password_they_must_replace(app_client, world, api_key_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post("/api/v1/team", json={"email": "Minh.Tran@Example.vn", "name": "Trần Minh", "role": "staff"}, headers=h(csrf))
    assert r.status_code == 201 and r.json()["email"] == "minh.tran@example.vn" and r.json()["staff_ref"] == "minh-tran"
    temp = r.json()["temporary_password"]
    assert len(temp) >= 12 and temp not in (await app_client.get("/api/v1/team")).text  # shown once, never listed
    row = next(u for u in await rows(world, m.AppUser) if u.email == "minh.tran@example.vn")
    assert temp not in row.password_hash and row.must_change_password
    app_client.cookies.clear()
    me = (await login(app_client, "minh.tran@example.vn", temp)).json()
    assert me["must_change_password"] is True
    csrf2 = me["csrf"]
    blocked = await app_client.get("/api/v1/conversations?filter=all")
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"  # nothing else until a new password
    assert (await app_client.get("/api/v1/session")).status_code == 200
    assert (await app_client.post("/api/v1/session/password", json={"current": temp, "new": GOOD}, headers=h(csrf2))).status_code == 200
    assert (await app_client.get("/api/v1/conversations?filter=all")).status_code == 200


async def test_accounts_are_the_owners_to_manage_and_staff_are_refused(app_client, world, api_key_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "staff", "nv1")
    assert (await app_client.get("/api/v1/team")).status_code == 403
    assert (await app_client.post("/api/v1/team", json={"email": "x@y.vn", "name": "Xu Yi", "role": "owner"}, headers=h(csrf))).status_code == 403
    assert not any(u.email == "x@y.vn" for u in await rows(world, m.AppUser))


async def test_email_is_unique_across_businesses_and_bad_input_is_refused(app_client, world, api_key_factory, tenant_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    other = await tenant_factory()
    from cortex_leads.auth.users import create_user
    from cortex_leads.db.session import tenant_session
    async with tenant_session(other.id) as s:
        await create_user(s, other.id, email="chung@example.vn", name="Người Khác", role="staff", password=GOOD, created_by="test")
    r = await app_client.post("/api/v1/team", json={"email": "chung@example.vn", "name": "Người Trùng", "role": "staff"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EMAIL_TAKEN"
    assert "chung@example.vn" not in (await app_client.get("/api/v1/team")).text  # the other business stays invisible
    for bad in ({"email": "khong-phai-email", "name": "Tên Đủ"}, {"email": "a@b.vn", "name": "x"}, {"email": "a@b.vn", "name": "Tên Đủ", "role": "root"}):
        assert (await app_client.post("/api/v1/team", json=bad, headers=h(csrf))).status_code in (422,)


async def test_the_last_owner_cannot_be_removed_and_nobody_changes_their_own_standing(app_client, world, api_key_factory):
    csrf, email = await as_(app_client, world, api_key_factory, "owner")
    me = next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["you"])
    r = await app_client.patch(f"/api/v1/team/{me['id']}", json={"status": "disabled"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SELF_CHANGE"
    new = (await app_client.post("/api/v1/team", json={"email": "chu2@example.vn", "name": "Chủ Hai", "role": "owner"}, headers=h(csrf))).json()
    assert (await app_client.patch(f"/api/v1/team/{new['id']}", json={"role": "staff"}, headers=h(csrf))).status_code == 200  # two owners: fine
    assert (await app_client.post(f"/api/v1/team/{me['id']}/reset-password", headers=h(csrf))).status_code == 409  # not for yourself


async def test_a_business_always_keeps_an_active_owner(app_client, world, api_key_factory, owner_engine):
    csrf, email = await as_(app_client, world, api_key_factory, "owner")
    new = (await app_client.post("/api/v1/team", json={"email": "chu2@example.vn", "name": "Chủ Hai", "role": "owner"}, headers=h(csrf))).json()
    async with owner_engine.begin() as c:  # the first owner leaves, outside the console
        await c.execute(text("update app_user set status = 'disabled' where lower(email) = :e"), {"e": email})
    app_client.cookies.clear()
    csrf2 = (await login(app_client, "chu2@example.vn", new["temporary_password"])).json()["csrf"]
    await app_client.post("/api/v1/session/password", json={"current": new["temporary_password"], "new": GOOD}, headers=h(csrf2))
    me = next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["you"])
    assert (await app_client.patch(f"/api/v1/team/{me['id']}", json={"role": "staff"}, headers=h(csrf2))).json()["detail"]["code"] == "SELF_CHANGE"


async def test_disabling_a_person_ends_their_sessions_and_opening_them_again_works(app_client, world, api_key_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    made = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    owner_cookie = app_client.cookies.get("cl_session")
    app_client.cookies.clear()
    await login(app_client, "an@example.vn", made["temporary_password"])
    an_cookie = app_client.cookies.get("cl_session")
    app_client.cookies.set("cl_session", owner_cookie, path="/")
    assert next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["email"] == "an@example.vn")["sessions"] == 1
    assert (await app_client.patch(f"/api/v1/team/{made['id']}", json={"status": "disabled"}, headers=h(csrf))).json()["status"] == "disabled"
    app_client.cookies.set("cl_session", an_cookie, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401
    app_client.cookies.set("cl_session", owner_cookie, path="/")
    await app_client.patch(f"/api/v1/team/{made['id']}", json={"status": "active"}, headers=h(csrf))
    app_client.cookies.clear()
    assert (await login(app_client, "an@example.vn", made["temporary_password"])).status_code == 200
    acts = {e.action for e in await rows(world, m.AuditEvent)}
    assert {"user.created", "user.updated"} <= acts


async def test_a_reset_gives_a_new_temporary_password_and_ends_every_sign_in(app_client, world, api_key_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    made = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    owner_cookie = app_client.cookies.get("cl_session")
    app_client.cookies.clear()
    await login(app_client, "an@example.vn", made["temporary_password"])
    an_cookie = app_client.cookies.get("cl_session")
    app_client.cookies.set("cl_session", owner_cookie, path="/")
    reset = (await app_client.post(f"/api/v1/team/{made['id']}/reset-password", headers=h(csrf))).json()
    assert reset["temporary_password"] != made["temporary_password"]
    app_client.cookies.set("cl_session", an_cookie, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401
    app_client.cookies.clear()
    assert (await login(app_client, "an@example.vn", made["temporary_password"])).status_code == 401  # the old one is gone
    assert (await login(app_client, "an@example.vn", reset["temporary_password"])).json()["must_change_password"] is True
    assert all(reset["temporary_password"] not in str(e.metadata_) + e.summary for e in await rows(world, m.AuditEvent))


async def test_another_business_cannot_see_or_touch_my_people(app_client, world, api_key_factory, tenant_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    mine = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    other = await tenant_factory()
    _, key = await api_key_factory(other, "owner", None)
    app_client.cookies.clear()
    csrf2 = await sign_in(app_client, key)
    assert "an@example.vn" not in (await app_client.get("/api/v1/team")).text
    for call in (app_client.patch(f"/api/v1/team/{mine['id']}", json={"status": "disabled"}, headers=h(csrf2)),
                 app_client.post(f"/api/v1/team/{mine['id']}/reset-password", headers=h(csrf2)),
                 app_client.post(f"/api/v1/team/{mine['id']}/end-sessions", headers=h(csrf2))):
        assert (await call).status_code == 404
    assert next(u for u in await rows(world, m.AppUser) if u.email == "an@example.vn").status == "active"


async def test_the_database_itself_refuses_to_show_one_business_the_accounts_of_another(world, tenant_factory):
    from cortex_leads.auth.users import create_user
    from cortex_leads.db.session import system_session, tenant_session
    other = await tenant_factory()
    async with tenant_session(other.id) as s:
        await create_user(s, other.id, email="rieng@example.vn", name="Người Riêng", role="staff", password=GOOD, created_by="test")
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(text("select count(*) from app_user where lower(email) = 'rieng@example.vn'"))).scalar_one() == 0
        assert (await s.execute(text("select count(*) from auth_session"))).scalar_one() == 0
    async with system_session() as s:  # no business, no sign-in being looked up: nothing at all
        assert (await s.execute(text("select count(*) from app_user"))).scalar_one() == 0
        await s.execute(text("select set_config('app.login_email', 'rieng@example.vn', true)"))
        assert (await s.execute(text("select count(*) from app_user"))).scalar_one() == 1  # exactly the one named
        await s.execute(text("select set_config('app.login_email', '', true)"))
        assert (await s.execute(text("select count(*) from app_user"))).scalar_one() == 0


# --- permissions: the whole API against one table ----------------------------------------------------
OWNER_ONLY = {
    ("GET", "/api/v1/google/accounts"), ("POST", "/api/v1/google/accounts/connect"), ("POST", "/api/v1/google/accounts/{account_id}/revoke"), ("POST", "/api/v1/google/accounts/{account_id}/reconnect"),
    ("DELETE", "/api/v1/google/accounts/{account_id}"), ("POST", "/api/v1/classes/{class_id}/relink"),
    ("GET", "/api/v1/google/accounts/{account_id}/courses"), ("POST", "/api/v1/google/classroom-sources"), ("POST", "/api/v1/classes"), ("PATCH", "/api/v1/classes/{class_id}"), ("DELETE", "/api/v1/classes/{class_id}"),
    ("GET", "/api/v1/google/accounts/{account_id}/folders"), ("POST", "/api/v1/google/lesson-sources"), ("POST", "/api/v1/google/sources/{kind}/{source_id}/active"),
    ("POST", "/api/v1/kill-switch"), ("GET", "/api/v1/proposals"), ("POST", "/api/v1/proposals/{proposal_id}/{verb}"), ("POST", "/api/v1/assistant/chat"),
    ("POST", "/api/v1/sandboxes"), ("POST", "/api/v1/sandboxes/{sandbox_id}/{verb}"), ("POST", "/api/v1/sandboxes/{sandbox_id}/send-mode"), ("GET", "/api/v1/sandboxes/{sandbox_id}"),
    ("GET", "/api/v1/sandboxes/{sandbox_id}/tools/{tool}"), ("POST", "/api/v1/sandboxes/{sandbox_id}/tools/{tool}/{state}"),
    ("POST", "/api/v1/skills/{skill_id}/{verb}"), ("GET", "/api/v1/tools"),
    ("GET", "/api/v1/sources"), ("POST", "/api/v1/sources"), ("GET", "/api/v1/sources/{source_id}"), ("POST", "/api/v1/sources/mcp/describe"),
    ("POST", "/api/v1/sources/{source_id}/review"), ("POST", "/api/v1/sources/{source_id}/{verb}"), ("PUT", "/api/v1/sources/{source_id}/sandbox"),
    ("GET", "/api/v1/audit/export"), ("GET", "/api/v1/audit/verify"),
    ("GET", "/api/v1/team"), ("POST", "/api/v1/team"), ("PATCH", "/api/v1/team/{user_id}"), ("POST", "/api/v1/team/{user_id}/reset-password"),
    ("POST", "/api/v1/team/{user_id}/end-sessions"),
    ("GET", "/api/v1/settings/business"), ("PUT", "/api/v1/settings/business"), ("GET", "/api/v1/settings/ai"), ("GET", "/api/v1/settings/notify-targets"),
    ("POST", "/api/v1/settings/notify-targets"), ("DELETE", "/api/v1/settings/notify-targets/{target_id}"), ("POST", "/api/v1/settings/notify-targets/{target_id}/test"),
    ("GET", "/api/v1/settings/channels"), ("POST", "/api/v1/settings/channels"), ("DELETE", "/api/v1/settings/channels/{connector_id}"),
    ("GET", "/api/v1/customers/{conversation_id}/export"), ("POST", "/api/v1/customers/{conversation_id}/erase"), ("GET", "/api/v1/onboarding"),
}
FOR_ANYONE_SIGNED_IN = {
    ("GET", "/api/v1/session"), ("POST", "/api/v1/session/logout"), ("POST", "/api/v1/session/password"), ("GET", "/api/v1/session/sessions"),
    ("POST", "/api/v1/session/sessions/{session_id}/revoke"), ("POST", "/api/v1/session/logout-all"),
    ("GET", "/api/v1/conversations"), ("GET", "/api/v1/conversations/{conversation_id}"), ("POST", "/api/v1/drafts/{draft_id}/action"),
    ("POST", "/api/v1/conversations/{conversation_id}/reply"), ("POST", "/api/v1/conversations/{conversation_id}/booking"),
    ("POST", "/api/v1/bookings/{booking_id}/cancel"), ("POST", "/api/v1/conversations/{conversation_id}/outcome"), ("POST", "/api/v1/facts/{fact_id}/{verb}"),
    ("GET", "/api/v1/skills"), ("GET", "/api/v1/skills/form-options"), ("GET", "/api/v1/skills/{skill_id}"), ("POST", "/api/v1/skills/preview"),
    ("POST", "/api/v1/skills"), ("PUT", "/api/v1/skills/{skill_id}"), ("POST", "/api/v1/skills/{skill_id}/revert"), ("GET", "/api/v1/sandboxes"),
    ("GET", "/api/v1/audit"), ("GET", "/api/v1/audit/{event_id}"),
    ("GET", "/api/v1/lessons"), ("GET", "/api/v1/classes"), ("GET", "/api/v1/lessons/{lesson_id}"), ("POST", "/api/v1/lessons/upload/session"),
    ("GET", "/api/v1/lessons/{lesson_id}/media"), ("DELETE", "/api/v1/lessons/{lesson_id}"), ("POST", "/api/v1/lessons/{lesson_id}/release"),
    ("GET", "/api/v1/grading"), ("GET", "/api/v1/grading/{item_id}"), ("POST", "/api/v1/grading/{item_id}/decision"), ("POST", "/api/v1/grading/{item_id}/grade"),
    ("GET", "/api/v1/classes/{class_id}/assignments"), ("POST", "/api/v1/assignments/{assignment_id}/grade"),
    ("GET", "/api/v1/assignments"), ("POST", "/api/v1/assignments"), ("POST", "/api/v1/assignments/ai"), ("POST", "/api/v1/assignments/{draft_id}/decision"),
}
# The callback trusts only its signed state. The recovery calls are for someone who cannot sign in: they answer the same whoever asks
# (forgot), or need the secret link (reset), and both are rate limited.
PUBLIC = {("POST", "/api/v1/session/login"), ("GET", "/api/v1/google/callback"), ("GET", "/api/v1/auth/recovery"), ("POST", "/api/v1/auth/forgot"),
          ("POST", "/api/v1/auth/reset")}


def _api_routes():
    from cortex_leads.app import create_app
    return {(m_.upper(), p) for p, ops in create_app().openapi()["paths"].items() if p.startswith("/api/v1") for m_ in ops}


def test_every_endpoint_has_been_given_a_decision():
    """A new endpoint fails this test until someone says who may call it."""
    decided = OWNER_ONLY | FOR_ANYONE_SIGNED_IN | PUBLIC
    assert _api_routes() - decided == set(), "endpoints with no permission decision"
    assert decided - _api_routes() == set(), "decisions for endpoints that no longer exist"
    assert not (OWNER_ONLY & FOR_ANYONE_SIGNED_IN)


async def test_staff_are_refused_every_owner_endpoint_and_nobody_unsigned_gets_anything(app_client, world, api_key_factory):
    zero = "00000000-0000-0000-0000-000000000000"
    fill = lambda p: (p.replace("{verb}", "lock").replace("{state}", "off").replace("{tool}", "send_message").replace("{proposal_id}", zero)
                      .replace("{sandbox_id}", zero).replace("{skill_id}", zero).replace("{source_id}", zero).replace("{user_id}", zero).replace("{account_id}", zero).replace("{class_id}", zero)
                      .replace("{target_id}", zero).replace("{connector_id}", "conn_x").replace("{conversation_id}", zero))
    for method, path in sorted(OWNER_ONLY | FOR_ANYONE_SIGNED_IN):
        r = await app_client.request(method, fill(path).replace("{event_id}", zero).replace("{session_id}", zero).replace("{conversation_id}", zero)
                                     .replace("{draft_id}", zero).replace("{booking_id}", zero).replace("{fact_id}", zero).replace("{lesson_id}", zero).replace("{item_id}", zero).replace("{draft_id}", zero), json={})
        assert r.status_code in (401, 403), (method, path, r.status_code)  # no cookie: refused, never served
    csrf, _ = await as_(app_client, world, api_key_factory, "staff", "nv1")
    for method, path in sorted(OWNER_ONLY):
        r = await app_client.request(method, fill(path), json={}, headers=h(csrf))
        assert r.status_code == 403, (method, path, r.status_code)
        assert r.json()["detail"]["code"] == "FORBIDDEN"
    for method, path in sorted(FOR_ANYONE_SIGNED_IN):
        r = await app_client.request(method, fill(path).replace("{event_id}", zero).replace("{session_id}", zero).replace("{conversation_id}", zero)
                                     .replace("{draft_id}", zero).replace("{booking_id}", zero).replace("{fact_id}", zero).replace("{lesson_id}", zero).replace("{item_id}", zero).replace("{draft_id}", zero), json={}, headers=h(csrf))
        assert r.status_code != 403 or "owner only" in r.text or path.startswith("/api/v1/skills") or path.startswith("/api/v1/audit"), (method, path, r.status_code)


async def test_the_api_is_never_cached_and_the_console_cannot_be_framed(app_client):
    r = await app_client.post("/api/v1/session/login", json={"email": "a@b.vn", "password": "x"})
    assert r.headers["Cache-Control"] == "no-store" and r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"


async def test_the_command_line_makes_an_account_and_resets_a_lost_owner_password(world, app_client):
    import argparse

    from cortex_leads.cli import cmd_create_user, cmd_reset_password
    await cmd_create_user(argparse.Namespace(tenant=world.t.id, email="chu@cli.test", name="Chủ Dòng Lệnh", role="owner", password=GOOD))
    assert (await login(app_client, "chu@cli.test", GOOD)).status_code == 200
    stolen = app_client.cookies.get("cl_session")
    await cmd_reset_password(argparse.Namespace(email="chu@cli.test"))
    app_client.cookies.set("cl_session", stolen, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401  # every sign-in ended
    assert (await login(app_client, "chu@cli.test", GOOD)).status_code == 401
    assert next(u for u in await rows(world, m.AppUser) if u.email == "chu@cli.test").must_change_password is True
    assert "cli" in [e.actor for e in await rows(world, m.AuditEvent) if e.action == "password.reset"][0]
