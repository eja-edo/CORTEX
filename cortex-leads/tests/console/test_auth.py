"""WP30: sign-in, sessions, passwords, lockout, accounts and permissions."""
import hashlib
from datetime import timedelta

from sqlalchemy import text
from support import PASSWORD, account_for_key, activate, h, sign_in
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
async def test_the_cookie_is_a_signed_token_that_cannot_be_altered_or_forged(app_client, world, api_key_factory, owner_engine):
    import base64
    import json

    import jwt as pyjwt
    csrf, email = await as_(app_client, world, api_key_factory, "staff", "nv1")
    cookie = app_client.cookies.get("cl_session")
    head, body, sig = cookie.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert claims["r"] == "staff" and claims["em"] == email and "password" not in cookie.lower() and csrf
    async with owner_engine.begin() as c:
        row = (await c.execute(text("select expires_at, ip from auth_session where id = :i"), {"i": claims["sid"]})).one()
    assert row.ip  # the list of devices still knows where it was
    owner_claims = {**claims, "r": "owner"}
    for bad in (
        f"{head}.{base64.urlsafe_b64encode(json.dumps(owner_claims).encode()).decode().rstrip('=')}.{sig}",  # edited: the signature no longer fits
        pyjwt.encode(owner_claims, "some-other-key", algorithm="HS256"),  # signed by someone else
        pyjwt.encode(owner_claims, key=None, algorithm="none"),  # no signature at all
        f"{head}.{body}.", f"{head}.{body}", cookie[:-3] + "AAA", "",
    ):
        app_client.cookies.set("cl_session", bad, path="/")
        assert (await app_client.get("/api/v1/session")).status_code == 401, bad[:40]
    app_client.cookies.set("cl_session", cookie, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 200


async def test_logout_ends_the_session_on_the_server_so_a_copied_cookie_is_dead(app_client, world, api_key_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "staff", "nv1")
    stolen = app_client.cookies.get("cl_session")
    assert (await app_client.post("/api/v1/session/logout", headers=h(csrf))).status_code == 200
    app_client.cookies.set("cl_session", stolen, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401


async def _token_made_at(world, email, *, now, auth_time=None):
    """What the server would have handed out at `now`: the clock is the token's own, so no test has to wait."""
    from sqlalchemy import select

    from cortex_leads.auth import tokens
    from cortex_leads.db.session import tenant_session
    async with tenant_session(world.t.id) as s:
        user = (await s.execute(select(m.AppUser).where(m.AppUser.email == email))).scalar_one()
        sid = (await s.execute(select(m.AuthSession.id).where(m.AuthSession.user_id == user.id, m.AuthSession.revoked_at.is_(None)))).scalars().first()
        return tokens.issue(user, await s.get(m.Tenant, user.tenant_id), sid, auth_time or now, now), sid


async def test_an_access_token_ends_at_its_own_time_and_never_past_the_end_of_the_sign_in(app_client, world, api_key_factory):
    from datetime import UTC, datetime
    _, email = await as_(app_client, world, api_key_factory, "staff", "nv1")
    now = datetime.now(UTC)
    short, _ = await _token_made_at(world, email, now=now - timedelta(minutes=20))
    app_client.cookies.set("cl_session", short, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401  # an access token lives minutes, not hours
    long_ago, _ = await _token_made_at(world, email, now=now, auth_time=now - timedelta(days=31))
    app_client.cookies.set("cl_session", long_ago, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401  # past the end of the sign-in, however it was renewed
    fresh, _ = await _token_made_at(world, email, now=now)
    app_client.cookies.set("cl_session", fresh, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 200


async def _change(world, email, **kw):
    """What the console does when an owner changes a person: through the account rules, which raise the person's version."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from cortex_leads.auth.users import change_role_or_status
    from cortex_leads.db.session import tenant_session
    async with tenant_session(world.t.id) as s:
        user = (await s.execute(select(m.AppUser).where(m.AppUser.email == email))).scalar_one()
        await change_role_or_status(s, user, role=kw.get("role"), status=kw.get("status"), now=datetime.now(UTC))


async def test_a_disabled_person_is_out_on_the_very_next_request(app_client, world, api_key_factory):
    _, email = await as_(app_client, world, api_key_factory, "staff", "nv1")
    assert (await app_client.get("/api/v1/session")).status_code == 200
    await _change(world, email, status="disabled")
    assert (await app_client.get("/api/v1/session")).status_code == 401
    assert (await login(app_client, email)).status_code == 401  # and cannot come back, with the same answer as a wrong password
    assert [e.metadata_["reason"] for e in await rows(world, m.AuditEvent) if e.action == "login.failed"] == ["disabled"]


async def test_a_demotion_ends_the_old_token_and_the_next_sign_in_has_the_new_role(app_client, world, api_key_factory):
    csrf, email = await as_(app_client, world, api_key_factory, "owner")
    assert (await app_client.get("/api/v1/audit/verify")).status_code == 200
    from cortex_leads.auth.users import create_user
    from cortex_leads.db.session import tenant_session
    async with tenant_session(world.t.id) as s:  # the business keeps an owner, so this one can step down
        await create_user(s, world.t.id, email="chu-khac@example.vn", name="Chủ Khác", role="owner", password=GOOD, created_by="test")
    await _change(world, email, role="staff")  # the token carries the role, so a change of role ends it: no stale owner token survives
    assert (await app_client.get("/api/v1/audit/verify")).status_code == 401
    app_client.cookies.clear()
    assert (await login(app_client, email)).json()["role"] == "staff"
    assert (await app_client.get("/api/v1/audit/verify")).status_code == 403
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
    app_client.cookies.clear()  # a browser takes the new cookie the password change handed back; this test jar would keep both
    app_client.cookies.set("cl_session", r.cookies.get("cl_session"), path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 200  # this one stays, on the version it was given
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
async def test_the_owner_invites_a_person_who_chooses_their_own_password_from_a_mailed_link(app_client, world, api_key_factory, mail):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post("/api/v1/team", json={"email": "Minh.Tran@Example.vn", "name": "Trần Minh", "role": "staff"}, headers=h(csrf))
    assert r.status_code == 201 and r.json()["email"] == "minh.tran@example.vn" and r.json()["staff_ref"] == "minh-tran"
    assert r.json()["mail_sent"] is True and "password" not in r.text.lower()  # no password exists to hand over
    assert [x["to"] for x in mail.sent] == ["minh.tran@example.vn"] and "https://cortex.example.vn/app/reset#token=" in mail.sent[0]["body"]
    listed = next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["email"] == "minh.tran@example.vn")
    assert listed["invited"] is True
    row = next(u for u in await rows(world, m.AppUser) if u.email == "minh.tran@example.vn")
    assert row.password_hash == "!"  # not a hash of anything: no input can match it
    app_client.cookies.clear()
    for guess in ("", "!", PASSWORD, GOOD, "Trần Minh"):  # nobody can walk in before the link is used
        assert (await login(app_client, "minh.tran@example.vn", guess)).status_code in (401, 422)
    assert (await activate(app_client, mail, GOOD)).status_code == 200
    assert (await login(app_client, "minh.tran@example.vn", GOOD)).status_code == 200
    assert (await app_client.get("/api/v1/conversations?filter=all")).status_code == 200
    assert (await activate(app_client, mail, "Another-pass-7391")).status_code == 400  # the link works once
    csrf_owner, _ = await as_(app_client, world, api_key_factory, "owner")
    assert next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["email"] == "minh.tran@example.vn")["invited"] is False
    blob = " ".join(str(e.metadata_) + e.summary for e in await rows(world, m.AuditEvent))
    assert GOOD not in blob and mail.sent[0]["body"].split("token=")[1].split()[0] not in blob


async def test_nobody_is_invited_when_the_server_cannot_send_mail(app_client, world, api_key_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MAIL_OFF"
    assert not any(u.email == "an@example.vn" for u in await rows(world, m.AppUser))  # and no account was left behind with a way in


async def test_a_failed_mail_leaves_a_waiting_account_the_owner_can_send_again(app_client, world, api_key_factory, mail):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    mail.fail = True
    made = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    assert made["mail_sent"] is False and mail.sent == []
    mail.fail = False
    again = (await app_client.post(f"/api/v1/team/{made['id']}/send-link", headers=h(csrf))).json()
    assert again["mail_sent"] is True and again["kind"] == "invite" and len(mail.sent) == 1
    app_client.cookies.clear()
    assert (await activate(app_client, mail, GOOD)).status_code == 200


async def test_sending_again_cancels_the_earlier_link(app_client, world, api_key_factory, mail):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    made = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    await app_client.post(f"/api/v1/team/{made['id']}/send-link", headers=h(csrf))
    app_client.cookies.clear()
    assert (await activate(app_client, mail, GOOD, 0)).status_code == 400
    assert (await activate(app_client, mail, GOOD, 1)).status_code == 200


async def test_the_invitation_link_expires(app_client, world, api_key_factory, mail, owner_engine):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))
    async with owner_engine.begin() as c:
        await c.execute(text("update password_reset set expires_at = now() - interval '1 minute'"))
    app_client.cookies.clear()
    assert (await activate(app_client, mail, GOOD)).status_code == 400


async def test_accounts_are_the_owners_to_manage_and_staff_are_refused(app_client, world, api_key_factory):
    csrf, _ = await as_(app_client, world, api_key_factory, "staff", "nv1")
    assert (await app_client.get("/api/v1/team")).status_code == 403
    assert (await app_client.post("/api/v1/team", json={"email": "x@y.vn", "name": "Xu Yi", "role": "owner"}, headers=h(csrf))).status_code == 403
    assert not any(u.email == "x@y.vn" for u in await rows(world, m.AppUser))


async def test_email_is_unique_across_businesses_and_bad_input_is_refused(app_client, world, api_key_factory, tenant_factory, mail):
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


async def test_the_last_owner_cannot_be_removed_and_nobody_changes_their_own_standing(app_client, world, api_key_factory, mail):
    csrf, email = await as_(app_client, world, api_key_factory, "owner")
    me = next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["you"])
    r = await app_client.patch(f"/api/v1/team/{me['id']}", json={"status": "disabled"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SELF_CHANGE"
    new = (await app_client.post("/api/v1/team", json={"email": "chu2@example.vn", "name": "Chủ Hai", "role": "owner"}, headers=h(csrf))).json()
    assert (await app_client.patch(f"/api/v1/team/{new['id']}", json={"role": "staff"}, headers=h(csrf))).status_code == 200  # two owners: fine
    assert (await app_client.post(f"/api/v1/team/{me['id']}/send-link", headers=h(csrf))).status_code == 409  # not for yourself


async def test_a_business_always_keeps_an_active_owner(app_client, world, api_key_factory, owner_engine, mail):
    csrf, email = await as_(app_client, world, api_key_factory, "owner")
    new = (await app_client.post("/api/v1/team", json={"email": "chu2@example.vn", "name": "Chủ Hai", "role": "owner"}, headers=h(csrf))).json()
    async with owner_engine.begin() as c:  # the first owner leaves, outside the console
        await c.execute(text("update app_user set status = 'disabled' where lower(email) = :e"), {"e": email})
    app_client.cookies.clear()
    await activate(app_client, mail, GOOD)
    csrf2 = (await login(app_client, "chu2@example.vn", GOOD)).json()["csrf"]
    me = next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["you"])
    assert (await app_client.patch(f"/api/v1/team/{me['id']}", json={"role": "staff"}, headers=h(csrf2))).json()["detail"]["code"] == "SELF_CHANGE"


async def test_disabling_a_person_ends_their_sessions_and_opening_them_again_works(app_client, world, api_key_factory, mail):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    made = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    owner_cookie = app_client.cookies.get("cl_session")
    app_client.cookies.clear()
    await activate(app_client, mail, GOOD)
    await login(app_client, "an@example.vn", GOOD)
    an_cookie = app_client.cookies.get("cl_session")
    app_client.cookies.set("cl_session", owner_cookie, path="/")
    assert next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["email"] == "an@example.vn")["sessions"] == 1
    assert (await app_client.patch(f"/api/v1/team/{made['id']}", json={"status": "disabled"}, headers=h(csrf))).json()["status"] == "disabled"
    assert (await app_client.post(f"/api/v1/team/{made['id']}/send-link", headers=h(csrf))).status_code == 409  # a locked account gets no link
    app_client.cookies.set("cl_session", an_cookie, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401
    app_client.cookies.set("cl_session", owner_cookie, path="/")
    await app_client.patch(f"/api/v1/team/{made['id']}", json={"status": "active"}, headers=h(csrf))
    app_client.cookies.clear()
    assert (await login(app_client, "an@example.vn", GOOD)).status_code == 200
    acts = {e.action for e in await rows(world, m.AuditEvent)}
    assert {"user.created", "user.updated"} <= acts


async def test_a_typo_in_an_invited_email_is_fixed_and_the_invitation_goes_to_the_right_address(app_client, world, api_key_factory, mail):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    made = (await app_client.post("/api/v1/team", json={"email": "an@gmail.comd", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    r = await app_client.patch(f"/api/v1/team/{made['id']}", json={"email": "An@Gmail.com", "name": "Văn An B"}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["email"] == "an@gmail.com" and r.json()["name"] == "Văn An B" and r.json()["mail_sent"] is True
    assert [x["to"] for x in mail.sent] == ["an@gmail.comd", "an@gmail.com"]
    app_client.cookies.clear()
    assert (await activate(app_client, mail, GOOD, 0)).status_code == 400  # the link that went to the wrong address is dead
    assert (await activate(app_client, mail, GOOD, 1)).status_code == 200
    assert (await login(app_client, "an@gmail.com", GOOD)).status_code == 200


async def test_moving_the_email_of_an_account_in_use_signs_them_out_voids_links_and_tells_the_old_address(app_client, world, api_key_factory, mail):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    owner_cookie = app_client.cookies.get("cl_session")
    made = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    app_client.cookies.clear()
    await activate(app_client, mail, GOOD)
    await login(app_client, "an@example.vn", GOOD)
    an_cookie = app_client.cookies.get("cl_session")
    app_client.cookies.set("cl_session", owner_cookie, path="/")
    await app_client.post(f"/api/v1/team/{made['id']}/send-link", headers=h(csrf))  # a reset link to the old address, still unused
    r = await app_client.patch(f"/api/v1/team/{made['id']}", json={"email": "An.Moi@Example.vn"}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["email"] == "an.moi@example.vn"
    app_client.cookies.set("cl_session", an_cookie, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401  # signed out everywhere
    app_client.cookies.clear()
    assert (await activate(app_client, mail, "Another-pass-7391", 1)).status_code == 400  # the reset link that went to the old address is dead
    assert (await login(app_client, "an@example.vn", GOOD)).status_code == 401
    assert (await login(app_client, "an.moi@example.vn", GOOD)).status_code == 200  # same password, new name
    told = mail.sent[-1]
    assert told["to"] == "an@example.vn" and "an.moi@example.vn" in told["body"]
    ev = [e for e in await rows(world, m.AuditEvent) if e.action == "user.updated"][-1]
    assert ev.metadata_.get("email_moved") is True


async def test_the_owner_edits_their_own_details_but_not_their_own_role_or_standing(app_client, world, api_key_factory, mail):
    csrf, email = await as_(app_client, world, api_key_factory, "owner")
    me = next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["you"])
    r = await app_client.patch(f"/api/v1/team/{me['id']}", json={"name": "Chủ Mới Tên", "phone": "0912 345 678"}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["name"] == "Chủ Mới Tên" and r.json()["phone"] == "0912 345 678"
    assert (await app_client.patch(f"/api/v1/team/{me['id']}", json={"role": "staff"}, headers=h(csrf))).json()["detail"]["code"] == "SELF_CHANGE"
    moved = await app_client.patch(f"/api/v1/team/{me['id']}", json={"email": "chu.moi@example.vn"}, headers=h(csrf))
    assert moved.status_code == 200
    assert (await app_client.get("/api/v1/session")).status_code == 200  # the session they are using stays


async def test_phone_birth_date_and_id_number_are_kept_checked_and_never_logged(app_client, world, api_key_factory, mail, owner_engine):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    made = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    url = f"/api/v1/team/{made['id']}"
    r = await app_client.patch(url, json={"phone": "+84 912 345 678", "birth_date": "1990-04-04", "national_id": "079 000 000 003"}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["birth_date"] == "1990-04-04" and r.json()["national_id"] == "079000000003"
    listed = next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["id"] == made["id"])
    assert listed["phone"] == "+84 912 345 678" and listed["national_id"] == "079000000003"
    async with owner_engine.begin() as c:  # on disk the number is not readable
        stored = (await c.execute(text("select national_id_enc from app_user where email = 'an@example.vn'"))).scalar_one()
    assert stored and "079000000003" not in stored
    blob = " ".join(str(e.metadata_) + e.summary + str(getattr(e, "changes", "")) for e in await rows(world, m.AuditEvent))
    assert "079000000003" not in blob and "912 345" not in blob and "1990-04-04" not in blob
    assert any(e.action == "user.updated" for e in await rows(world, m.AuditEvent))
    for bad in ({"phone": "abc"}, {"national_id": "12345"}, {"birth_date": "2999-01-01"}, {"birth_date": "1800-01-01"}):
        assert (await app_client.patch(url, json=bad, headers=h(csrf))).status_code == 422, bad
    cleared = await app_client.patch(url, json={"phone": "", "national_id": None, "birth_date": None}, headers=h(csrf))
    assert cleared.json()["phone"] is None and cleared.json()["national_id"] is None and cleared.json()["birth_date"] is None
    untouched = await app_client.patch(url, json={"name": "Văn An Hai"}, headers=h(csrf))  # a request that does not mention them leaves them alone
    assert untouched.status_code == 200


async def test_an_invited_email_cannot_take_another_accounts_address(app_client, world, api_key_factory, mail):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    await app_client.post("/api/v1/team", json={"email": "a@example.vn", "name": "Văn A", "role": "staff"}, headers=h(csrf))
    b = (await app_client.post("/api/v1/team", json={"email": "b@example.vn", "name": "Văn B", "role": "staff"}, headers=h(csrf))).json()
    r = await app_client.patch(f"/api/v1/team/{b['id']}", json={"email": "a@example.vn"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EMAIL_TAKEN"
    assert (await app_client.patch(f"/api/v1/team/{b['id']}", json={"email": "khong-phai-email"}, headers=h(csrf))).status_code == 422


async def test_a_reset_link_leaves_the_old_password_until_used_then_ends_every_sign_in(app_client, world, api_key_factory, mail):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    made = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    owner_cookie = app_client.cookies.get("cl_session")
    app_client.cookies.clear()
    await activate(app_client, mail, GOOD)
    await login(app_client, "an@example.vn", GOOD)
    an_cookie = app_client.cookies.get("cl_session")
    app_client.cookies.set("cl_session", owner_cookie, path="/")
    sent = (await app_client.post(f"/api/v1/team/{made['id']}/send-link", headers=h(csrf))).json()
    assert sent["kind"] == "reset" and sent["mail_sent"] is True and "password" not in str(sent).lower().replace("password.", "")
    app_client.cookies.set("cl_session", an_cookie, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 200  # nothing changes until they use the link
    app_client.cookies.clear()
    assert (await activate(app_client, mail, "Another-pass-7391")).status_code == 200
    app_client.cookies.set("cl_session", an_cookie, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401
    app_client.cookies.clear()
    assert (await login(app_client, "an@example.vn", GOOD)).status_code == 401  # the old one is gone
    assert (await login(app_client, "an@example.vn", "Another-pass-7391")).status_code == 200
    assert "password.link_sent" in {e.action for e in await rows(world, m.AuditEvent)}


async def test_another_business_cannot_see_or_touch_my_people(app_client, world, api_key_factory, tenant_factory, mail):
    csrf, _ = await as_(app_client, world, api_key_factory, "owner")
    mine = (await app_client.post("/api/v1/team", json={"email": "an@example.vn", "name": "Văn An", "role": "staff"}, headers=h(csrf))).json()
    other = await tenant_factory()
    _, key = await api_key_factory(other, "owner", None)
    app_client.cookies.clear()
    csrf2 = await sign_in(app_client, key)
    assert "an@example.vn" not in (await app_client.get("/api/v1/team")).text
    for call in (app_client.patch(f"/api/v1/team/{mine['id']}", json={"status": "disabled"}, headers=h(csrf2)),
                 app_client.post(f"/api/v1/team/{mine['id']}/send-link", headers=h(csrf2)),
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
    ("GET", "/api/v1/team"), ("POST", "/api/v1/team"), ("PATCH", "/api/v1/team/{user_id}"), ("POST", "/api/v1/team/{user_id}/send-link"),
    ("POST", "/api/v1/team/{user_id}/end-sessions"), ("PUT", "/api/v1/team/{user_id}/classes"),
    ("POST", "/api/v1/team/{user_id}/mfa/disable"),  # staff and teachers only; the owner confirms with their own password
    ("GET", "/api/v1/settings/business"), ("PUT", "/api/v1/settings/business"), ("GET", "/api/v1/settings/ai"), ("GET", "/api/v1/settings/notify-targets"),
    ("POST", "/api/v1/settings/notify-targets"), ("DELETE", "/api/v1/settings/notify-targets/{target_id}"), ("POST", "/api/v1/settings/notify-targets/{target_id}/test"),
    ("GET", "/api/v1/settings/channels"), ("POST", "/api/v1/settings/channels"), ("DELETE", "/api/v1/settings/channels/{connector_id}"),
    ("GET", "/api/v1/customers/{conversation_id}/export"), ("POST", "/api/v1/customers/{conversation_id}/erase"),
    ("POST", "/api/v1/catalog/import"),
}
FOR_ANYONE_SIGNED_IN = {
    ("GET", "/api/v1/catalog"), ("GET", "/api/v1/catalog/template"),
    ("GET", "/api/v1/session"), ("POST", "/api/v1/session/logout"), ("POST", "/api/v1/session/password"), ("GET", "/api/v1/session/sessions"),
    ("GET", "/api/v1/account/mfa"), ("POST", "/api/v1/account/mfa/setup"), ("POST", "/api/v1/account/mfa/enable"), ("POST", "/api/v1/account/mfa/disable"),
    ("POST", "/api/v1/account/mfa/recovery-codes"),
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
    ("PATCH", "/api/v1/assignments/{assignment_id}"), ("POST", "/api/v1/assignments/{assignment_id}/publish"), ("DELETE", "/api/v1/assignments/{assignment_id}"),
    ("GET", "/api/v1/class-kinds"), ("POST", "/api/v1/class-kinds"), ("PATCH", "/api/v1/class-kinds/{kind_id}"), ("DELETE", "/api/v1/class-kinds/{kind_id}"),
    ("GET", "/api/v1/class-kinds/{kind_id}/templates"), ("POST", "/api/v1/class-kinds/{kind_id}/templates"), ("PUT", "/api/v1/assignment-templates/{template_id}"),
    ("DELETE", "/api/v1/assignment-templates/{template_id}"),
    ("GET", "/api/v1/google/picker"), ("POST", "/api/v1/google/picker/token"),
    ("GET", "/api/v1/classes/{class_id}/classroom-options"),
}
# The callback trusts only its signed state. The recovery calls are for someone who cannot sign in: they answer the same whoever asks
# (forgot), or need the secret link (reset), and both are rate limited.
PUBLIC = {("POST", "/api/v1/session/login"), ("POST", "/api/v1/session/mfa"), ("POST", "/api/v1/session/refresh"), ("GET", "/api/v1/google/callback"), ("GET", "/api/v1/auth/recovery"), ("POST", "/api/v1/auth/forgot"),
          ("POST", "/api/v1/auth/reset")}


CLASS_PATHS = tuple("/api/v1/" + x for x in ("lessons", "grading", "classes", "assignments", "assignment-templates", "class-kinds", "google/picker"))


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
                      .replace("{sandbox_id}", zero).replace("{skill_id}", zero).replace("{source_id}", zero).replace("{user_id}", zero).replace("{account_id}", zero).replace("{class_id}", zero).replace("{kind_id}", zero).replace("{template_id}", zero)
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
    plain = lambda p: (fill(p).replace("{event_id}", zero).replace("{session_id}", zero).replace("{conversation_id}", zero)
                       .replace("{draft_id}", zero).replace("{booking_id}", zero).replace("{fact_id}", zero).replace("{lesson_id}", zero).replace("{item_id}", zero))
    for method, path in sorted(x for x in FOR_ANYONE_SIGNED_IN if x[1].startswith(CLASS_PATHS)):  # first: a sign-out below would make the rest answer 401
        r = await app_client.request(method, plain(path), json={}, headers=h(csrf))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "FORBIDDEN", (method, path, r.status_code)  # customer care has no part in the classes (2026-11-06)
    for method, path in sorted(x for x in FOR_ANYONE_SIGNED_IN if not x[1].startswith(CLASS_PATHS)):
        r = await app_client.request(method, plain(path), json={}, headers=h(csrf))
        assert r.status_code != 403 or "owner only" in r.text or path.startswith("/api/v1/skills") or path.startswith("/api/v1/audit"), (method, path, r.status_code)


async def test_the_api_is_never_cached_and_the_console_cannot_be_framed(app_client):
    r = await app_client.post("/api/v1/session/login", json={"email": "a@b.vn", "password": "x"})
    assert r.headers["Cache-Control"] == "no-store" and r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"


async def test_the_command_line_makes_an_account_and_resets_a_lost_owner_password(world, app_client, monkeypatch, mail):
    import argparse
    import getpass

    from cortex_leads.cli import cmd_create_user, cmd_reset_password
    await cmd_create_user(argparse.Namespace(tenant=world.t.id, email="chu@cli.test", name="Chủ Dòng Lệnh", role="owner", password=GOOD))
    assert (await login(app_client, "chu@cli.test", GOOD)).status_code == 200
    stolen = app_client.cookies.get("cl_session")
    answers = iter(["Mat-khau-cli-8842", "Mat-khau-cli-8842"])
    monkeypatch.setattr(getpass, "getpass", lambda *_: next(answers))  # typed at the terminal, never an argument or an output
    await cmd_reset_password(argparse.Namespace(email="chu@cli.test"))
    app_client.cookies.set("cl_session", stolen, path="/")
    assert (await app_client.get("/api/v1/session")).status_code == 401  # every sign-in ended
    assert (await login(app_client, "chu@cli.test", GOOD)).status_code == 401
    assert (await login(app_client, "chu@cli.test", "Mat-khau-cli-8842")).status_code == 200
    assert "cli" in [e.actor for e in await rows(world, m.AuditEvent) if e.action == "password.reset"][0]


async def test_the_command_line_invites_by_mail_and_prints_no_password(world, app_client, mail, capsys):
    import argparse

    from cortex_leads.cli import cmd_create_user
    await cmd_create_user(argparse.Namespace(tenant=world.t.id, email="moi@cli.test", name="Người Mời", role="staff", password=None))
    out = capsys.readouterr().out
    assert "invite=sent" in out and "password" not in out.lower() and len(mail.sent) == 1
    assert (await activate(app_client, mail, GOOD)).status_code == 200


async def test_the_command_line_refuses_to_invite_when_mail_is_off(world):
    import argparse

    import pytest

    from cortex_leads.cli import cmd_create_user
    with pytest.raises(SystemExit):
        await cmd_create_user(argparse.Namespace(tenant=world.t.id, email="moi@cli.test", name="Người Mời", role="staff", password=None))
    assert not any(u.email == "moi@cli.test" for u in await rows(world, m.AppUser))
