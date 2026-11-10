"""The platform admin page (WP47, DESIGN §5.16): its own sign-in, always two steps, kept apart from the console, and what it may do to a business."""
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select, text
from support import PASSWORD, h, sign_in, sql

from cortex_leads.auth import mfa, passwords
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session

ADMIN_EMAIL = "ops@cortex.example.vn"
ADMIN_PASSWORD = "Admin-pass-98765"


def code(secret: str, ahead: int = 0) -> str:
    """The code the admin's phone shows now (`ahead` = the next step, for a second code inside the same 30 seconds)."""
    return mfa.code_at(secret, mfa.step_of(datetime.now(UTC)) + ahead)


@pytest.fixture
async def admin(owner_engine):
    secret = mfa.new_secret()
    _, hashes = mfa.new_recovery_codes()
    async with system_session() as s:
        row = m.PlatformAdmin(id=uuid7(), email=ADMIN_EMAIL, display_name="Vận hành", password_hash=passwords.hash_password(ADMIN_PASSWORD),
                              mfa_secret_enc=mfa.seal(secret), mfa_enabled_at=datetime.now(UTC), mfa_recovery=hashes)
        s.add(row)
    return row.id, secret


async def admin_in(client, secret: str) -> str:
    r = await client.post("/api/admin/session/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200 and r.json() == {"mfa_required": True}, r.text
    r = await client.post("/api/admin/session/mfa", json={"code": code(secret)})
    assert r.status_code == 200, r.text
    return r.json()["csrf"]


def _admin_routes():
    from cortex_leads.app import create_app
    return {(meth.upper(), p.removeprefix("/api/admin")) for p, ops in create_app().openapi()["paths"].items() if p.startswith("/api/admin/") for meth in ops}


async def test_every_admin_route_but_the_sign_in_steps_needs_a_signed_in_admin(app_client):
    from cortex_leads.admin.api import PUBLIC

    zero = "00000000-0000-0000-0000-000000000000"
    routes = _admin_routes()
    assert PUBLIC <= routes
    for method, path in sorted(routes - PUBLIC):
        r = await app_client.request(method, "/api/admin" + path.replace("{tenant_id}", zero).replace("{user_id}", zero), json={})
        assert r.status_code == 401, (method, path, r.status_code)


async def test_signing_in_takes_the_password_then_a_code_and_a_password_alone_gives_nothing(app_client, admin, owner_engine):
    _, secret = admin
    r = await app_client.post("/api/admin/session/login", json={"email": ADMIN_EMAIL, "password": "wrong-password-1"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "BAD_CREDENTIALS"
    r = await app_client.post("/api/admin/session/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200 and "cl_admin" not in r.cookies
    assert (await app_client.get("/api/admin/session")).status_code == 401  # the password step made no session
    assert (await app_client.post("/api/admin/session/mfa", json={"code": code(secret, -5)})).status_code == 401  # an old code
    r = await app_client.post("/api/admin/session/mfa", json={"code": code(secret)})
    assert r.status_code == 200 and r.json()["email"] == ADMIN_EMAIL
    assert (await app_client.get("/api/admin/session")).status_code == 200
    async with owner_engine.connect() as c:  # platform rows: no business can read them, the owner of the database can
        rows = (await c.execute(text("select action, actor from audit_event where tenant_id is null"))).all()
    assert {(a, f"admin:{ADMIN_EMAIL}") for a in ("admin.login.failed", "admin.login.mfa_failed", "admin.login.ok")} <= set(rows)
    assert all("Admin-pass" not in str(r) for r in rows)


async def test_an_admin_without_two_step_sign_in_cannot_sign_in_at_all(app_client, admin, owner_engine):
    await sql(owner_engine, "update platform_admin set mfa_enabled_at = null")
    r = await app_client.post("/api/admin/session/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "BAD_CREDENTIALS"  # the same answer as a wrong password


async def test_the_console_and_the_admin_page_do_not_accept_each_others_sign_in(app_client, admin, world, api_key_factory):
    _, key = await api_key_factory(world.t, "owner", None)
    await sign_in(app_client, key)  # a business owner, signed in to the console
    assert (await app_client.get("/api/admin/tenants")).status_code == 401
    app_client.cookies.clear()
    await admin_in(app_client, admin[1])
    assert (await app_client.get("/api/v1/session")).status_code == 401  # and an admin is nobody in the console


async def test_a_state_changing_call_needs_the_csrf_token(app_client, admin, world):
    csrf = await admin_in(app_client, admin[1])
    r = await app_client.post(f"/api/admin/tenants/{world.t.id}/ai", json={"paused": True})
    assert r.status_code == 403
    r = await app_client.post(f"/api/admin/tenants/{world.t.id}/ai", json={"paused": True}, headers=h(csrf))
    assert r.status_code == 200 and r.json()["changed"] == 1


async def test_signing_out_and_disabling_end_the_admin_session_at_once(app_client, admin, owner_engine):
    csrf = await admin_in(app_client, admin[1])
    token = app_client.cookies.get("cl_admin")
    assert (await app_client.post("/api/admin/session/logout", headers=h(csrf))).status_code == 200
    app_client.cookies.set("cl_admin", token, path="/api/admin")  # the old token, kept by someone
    assert (await app_client.get("/api/admin/session")).status_code == 401
    app_client.cookies.clear()
    # sign in again (next 30-second step: the code just used is spent) and then be disabled
    await app_client.post("/api/admin/session/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert (await app_client.post("/api/admin/session/mfa", json={"code": code(admin[1], 1)})).status_code == 200
    assert (await app_client.get("/api/admin/session")).status_code == 200
    await sql(owner_engine, "update platform_admin set status = 'disabled'")
    assert (await app_client.get("/api/admin/session")).status_code == 401


async def test_a_new_business_comes_with_every_sandbox_and_its_first_owner_invited(app_client, admin, mail):
    csrf = await admin_in(app_client, admin[1])
    r = await app_client.post("/api/admin/tenants", json={"name": "Trung tâm Mới", "timezone": "Asia/Ho_Chi_Minh",
                                                          "owner_email": "chu@moi.vn", "owner_name": "Chủ Mới"}, headers=h(csrf))
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["owner"] == {"email": "chu@moi.vn", "mail_sent": True}
    assert mail.sent[-1]["to"] == "chu@moi.vn" and "#token=" in mail.sent[-1]["body"] and "kind=invite" in mail.sent[-1]["body"]
    d = (await app_client.get(f"/api/admin/tenants/{tid}")).json()
    assert d["name"] == "Trung tâm Mới" and d["sandboxes"] >= 2 and d["sandboxes_missing"] == [] and d["ai"] == "running"
    assert [(a["email"], a["role"], a["invited"]) for a in d["account_list"]] == [("chu@moi.vn", "owner", True)]
    assert d["owners_waiting"] == 1
    async with tenant_session(UUID(tid)) as s:
        actors = (await s.execute(select(m.AuditEvent.actor, m.AuditEvent.actor_role, m.AuditEvent.action))).all()
    assert (f"admin:{ADMIN_EMAIL}", "platform", "tenant.created") in actors and (f"admin:{ADMIN_EMAIL}", "platform", "user.created") in actors
    listed = (await app_client.get("/api/admin/tenants")).json()["items"]
    assert [t["name"] for t in listed] == ["Trung tâm Mới"]


async def test_no_mail_means_no_new_business_rather_than_one_nobody_can_open(app_client, admin):
    csrf = await admin_in(app_client, admin[1])
    r = await app_client.post("/api/admin/tenants", json={"name": "Không thư", "owner_email": "a@b.vn", "owner_name": "Ai Đó"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MAIL_OFF"
    assert (await app_client.get("/api/admin/tenants")).json()["items"] == []


async def test_bad_input_is_refused_before_anything_is_made(app_client, admin, mail):
    csrf = await admin_in(app_client, admin[1])
    for body, want in (({"name": "X Y", "timezone": "Mars/Base", "owner_email": "a@b.vn", "owner_name": "Ai Đó"}, "BAD_TIMEZONE"),
                       ({"name": "X Y", "owner_email": "không-phải-email", "owner_name": "Ai Đó"}, "BAD_EMAIL")):
        r = await app_client.post("/api/admin/tenants", json=body, headers=h(csrf))
        assert r.status_code == 422 and r.json()["detail"]["code"] == want, r.text
    assert (await app_client.get("/api/admin/tenants")).json()["items"] == []


async def test_the_admin_sees_accounts_but_nothing_personal_and_no_customer(app_client, admin, world, api_key_factory, owner_engine):
    _, key = await api_key_factory(world.t, "owner", None)
    from support import account_for_key
    email = await account_for_key(key)
    await sql(owner_engine, "update app_user set phone = '0901234567', national_id_enc = 'x' where email = :e", e=email)
    await admin_in(app_client, admin[1])
    r = await app_client.get(f"/api/admin/tenants/{world.t.id}")
    assert r.status_code == 200
    text_ = r.text
    assert email in text_ and "0901234567" not in text_ and "national" not in text_ and "Nguyễn Văn An" not in text_  # the customer of `world`
    assert r.json()["conversations_7d"] >= 0
    assert (await app_client.get(f"/api/admin/tenants/{uuid7()}")).status_code == 404


async def test_an_owner_who_lost_their_phone_is_rescued_with_the_admins_own_code(app_client, admin, world, api_key_factory, owner_engine, mail):
    _, key = await api_key_factory(world.t, "owner", None)
    from support import account_for_key
    email = await account_for_key(key)
    await sql(owner_engine, "update app_user set mfa_enabled_at = now(), mfa_secret_enc = 'x' where email = :e", e=email)
    async with tenant_session(world.t.id) as s:
        uid = (await s.execute(select(m.AppUser.id).where(m.AppUser.email == email))).scalar_one()
    csrf = await admin_in(app_client, admin[1])
    url = f"/api/admin/tenants/{world.t.id}/users/{uid}/mfa/reset"
    r = await app_client.post(url, json={"code": "000000"}, headers=h(csrf))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "BAD_MFA_CODE"
    r = await app_client.post(url, json={"code": code(admin[1], 1)}, headers=h(csrf))
    assert r.status_code == 200, r.text
    async with tenant_session(world.t.id) as s:
        u = await s.get(m.AppUser, uid)
        assert u.mfa_enabled_at is None and u.mfa_secret_enc is None
        assert (await s.execute(select(m.AuditEvent.action).where(m.AuditEvent.actor == f"admin:{ADMIN_EMAIL}"))).scalars().all() == ["mfa.reset"]
    assert mail.sent[-1]["to"] == email
    # a link to choose a new password goes to the owner, never a password to the admin
    r = await app_client.post(f"/api/admin/tenants/{world.t.id}/users/{uid}/send-link", headers=h(csrf))
    assert r.status_code == 200 and r.json()["kind"] == "reset" and mail.sent[-1]["to"] == email and "password" not in r.text
    # and the person can still sign in with their password: nothing was changed but the second step
    app_client.cookies.clear()
    assert (await app_client.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})).status_code == 200


async def test_another_owner_can_be_invited_when_the_only_one_left(app_client, admin, world, mail):
    csrf = await admin_in(app_client, admin[1])
    r = await app_client.post(f"/api/admin/tenants/{world.t.id}/owners", json={"email": "chu2@acme.vn", "name": "Chủ Hai"}, headers=h(csrf))
    assert r.status_code == 201 and r.json()["mail_sent"] is True
    r = await app_client.post(f"/api/admin/tenants/{world.t.id}/owners", json={"email": "chu2@acme.vn", "name": "Chủ Hai"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EMAIL_TAKEN"


async def test_a_typo_in_an_invited_owners_email_is_fixed_and_the_invitation_goes_again(app_client, admin, world, mail):
    csrf = await admin_in(app_client, admin[1])
    r = await app_client.post(f"/api/admin/tenants/{world.t.id}/owners", json={"email": "chu@acme.vncom", "name": "chu"}, headers=h(csrf))
    assert r.status_code == 201, r.text
    async with tenant_session(world.t.id) as s:
        uid = (await s.execute(select(m.AppUser.id).where(m.AppUser.email == "chu@acme.vncom"))).scalar_one()
    r = await app_client.patch(f"/api/admin/tenants/{world.t.id}/users/{uid}", json={"email": "chu@acme.vn", "name": "Chủ Acme"}, headers=h(csrf))
    assert r.status_code == 200, r.text
    assert r.json() == {"email": "chu@acme.vn", "name": "Chủ Acme", "email_moved": True, "sessions_ended": 0, "mail_sent": True}
    assert mail.sent[-1]["to"] == "chu@acme.vn"  # no code needed: nobody was using this account yet
    async with tenant_session(world.t.id) as s:
        resets = (await s.execute(select(m.PasswordReset).where(m.PasswordReset.user_id == uid))).scalars().all()
        assert sum(x.used_at is None for x in resets) == 1  # the link sent to the wrong address no longer works
        ev = (await s.execute(select(m.AuditEvent).where(m.AuditEvent.action == "user.updated"))).scalar_one()
        assert ev.actor == f"admin:{ADMIN_EMAIL}" and {c["field"] for c in ev.metadata_["changes"]} == {"name", "email"}


async def test_moving_the_email_of_an_account_in_use_needs_the_admins_code_and_tells_the_old_address(app_client, admin, world, api_key_factory, mail):
    _, key = await api_key_factory(world.t, "owner", None)
    from support import account_for_key
    email = await account_for_key(key)
    async with tenant_session(world.t.id) as s:
        uid = (await s.execute(select(m.AppUser.id).where(m.AppUser.email == email))).scalar_one()
    assert (await app_client.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})).status_code == 200
    console = dict(app_client.cookies)
    app_client.cookies.clear()
    csrf = await admin_in(app_client, admin[1])
    url = f"/api/admin/tenants/{world.t.id}/users/{uid}"
    r = await app_client.patch(url, json={"email": "moi@acme.vn"}, headers=h(csrf))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CODE_REQUIRED"
    r = await app_client.patch(url, json={"name": "Tên mới"}, headers=h(csrf))  # a name needs no code
    assert r.status_code == 200 and r.json()["email_moved"] is False and r.json()["mail_sent"] is None
    r = await app_client.patch(url, json={"email": "moi@acme.vn", "code": code(admin[1], 1)}, headers=h(csrf))
    assert r.status_code == 200, r.text
    assert r.json()["sessions_ended"] >= 1 and r.json()["mail_sent"] is True
    assert mail.sent[-1]["to"] == email and "moi@acme.vn" in mail.sent[-1]["body"]
    app_client.cookies.clear()
    app_client.cookies.update(console)
    assert (await app_client.get("/api/v1/session")).status_code == 401  # signed out everywhere
    app_client.cookies.clear()
    assert (await app_client.post("/api/v1/session/login", json={"email": "moi@acme.vn", "password": PASSWORD})).status_code == 200


async def test_stopping_every_business_needs_the_admins_code(app_client, admin, world, tenant_factory, sandbox_factory):
    other = await tenant_factory("Khác")
    await sandbox_factory(other)
    csrf = await admin_in(app_client, admin[1])
    assert (await app_client.post("/api/admin/ai", json={"paused": True, "code": "123456"}, headers=h(csrf))).status_code == 401
    r = await app_client.post("/api/admin/ai", json={"paused": True, "code": code(admin[1], 1)}, headers=h(csrf))
    assert r.status_code == 200 and r.json() == {"tenants": 2, "sandboxes_changed": 2}
    items = (await app_client.get("/api/admin/tenants")).json()["items"]
    assert {t["ai"] for t in items} == {"paused"}
    r = await app_client.post(f"/api/admin/tenants/{world.t.id}/ai", json={"paused": False}, headers=h(csrf))
    assert r.json()["changed"] == 1


async def test_missing_sandboxes_are_added_once(app_client, admin, world):
    csrf = await admin_in(app_client, admin[1])
    before = (await app_client.get(f"/api/admin/tenants/{world.t.id}")).json()
    assert before["sandboxes_missing"]  # `world` has only customer care
    r = await app_client.post(f"/api/admin/tenants/{world.t.id}/sandboxes/ensure", headers=h(csrf))
    assert sorted(r.json()["added"]) == sorted(before["sandboxes_missing"])
    assert (await app_client.post(f"/api/admin/tenants/{world.t.id}/sandboxes/ensure", headers=h(csrf))).json()["added"] == []


async def test_the_command_line_makes_an_admin_with_two_step_sign_in_already_on(app_client, monkeypatch, capsys):
    import argparse
    import getpass
    import re

    from cortex_leads import cli

    monkeypatch.setattr(getpass, "getpass", lambda prompt="": ADMIN_PASSWORD)
    seen: dict[str, str] = {}

    def type_code(prompt: str = "") -> str:  # what the operator reads off their phone, from the key the command just printed
        seen["key"] = re.search(r"Khoá:\s+([A-Z2-7 ]+)", capsys.readouterr().out).group(1).replace(" ", "")
        return mfa.code_at(seen["key"], mfa.step_of(datetime.now(UTC)))

    monkeypatch.setattr("builtins.input", type_code)
    await cli.cmd_create_admin(argparse.Namespace(email=ADMIN_EMAIL, name="Vận hành"))
    out = capsys.readouterr().out
    assert len(re.findall(r"^  [a-z2-9]{5}-[a-z2-9]{5}$", out, re.MULTILINE)) == 10 and ADMIN_PASSWORD not in out
    r = await app_client.post("/api/admin/session/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    r = await app_client.post("/api/admin/session/mfa", json={"code": mfa.code_at(seen["key"], mfa.step_of(datetime.now(UTC)) + 1)})
    assert r.status_code == 200, r.text
    with pytest.raises(SystemExit):
        await cli.cmd_create_admin(argparse.Namespace(email=ADMIN_EMAIL, name="Vận hành"))  # one admin per email
