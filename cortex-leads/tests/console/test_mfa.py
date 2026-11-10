"""Two-step sign-in (TOTP + recovery codes), turned on by each person, turned off by them, by the owner for staff, or by the operator."""
import argparse
import base64
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from support import PASSWORD, account_for_key, h, sign_in
from wp5_support import rows

from cortex_leads import cli
from cortex_leads.auth import mfa
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session


async def login(client, email, password=PASSWORD):
    return await client.post("/api/v1/session/login", json={"email": email, "password": password})


async def staff(app_client, world, api_key_factory, ref="nv1"):
    _, key = await api_key_factory(world.t, "staff", ref)
    app_client.cookies.clear()
    return await sign_in(app_client, key), await account_for_key(key)


async def turn_on(client, csrf) -> tuple[str, list[str]]:
    """Through the account page, as a person does it. Returns the secret (what the phone holds) and the recovery codes."""
    r = await client.post("/api/v1/account/mfa/setup", json={"password": PASSWORD}, headers=h(csrf))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["uri"].startswith("otpauth://totp/Cortex") and f"secret={secret}" in r.json()["uri"]
    r = await client.post("/api/v1/account/mfa/enable", json={"code": mfa.code_at(secret, mfa.step_of(datetime.now(UTC)))}, headers=h(csrf))
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def a_later_code(secret: str) -> str:
    """The code of the next time step: the one just used at enable is spent (a code works once)."""
    return mfa.code_at(secret, mfa.step_of(datetime.now(UTC)) + 1)


# --- the algorithm -----------------------------------------------------------------------------------
def test_totp_matches_the_rfc_6238_reference_values():
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    for t, full in ((59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"), (2000000000, "69279037")):
        assert mfa.code_at(secret, t // 30) == full[-6:]


def test_a_code_is_good_once_and_only_near_its_own_time():
    secret = mfa.new_secret()
    now = datetime.now(UTC)
    code = mfa.code_at(secret, mfa.step_of(now))
    step = mfa.match(secret, code, now, None)
    assert step is not None and mfa.match(secret, code, now, step) is None  # replayed: refused
    assert mfa.match(secret, mfa.code_at(secret, mfa.step_of(now) - 5), now, None) is None  # two and a half minutes old
    assert mfa.match(secret, "12345", now, None) is None and mfa.match(secret, "abcdef", now, None) is None


def test_recovery_codes_are_kept_only_as_hashes_and_read_forgivingly():
    codes, hashes = mfa.new_recovery_codes()
    assert len(codes) == 10 == len(set(codes)) and not set(codes) & set(hashes)
    assert mfa.recovery_hash(codes[0].upper().replace("-", " ")) == hashes[0]


def test_the_secret_is_sealed_at_rest_and_the_challenge_cannot_be_forged():
    sealed = mfa.seal("JBSWY3DPEHPK3PXP")
    assert "JBSWY3DP" not in sealed and mfa.unseal(sealed) == "JBSWY3DPEHPK3PXP" and mfa.unseal("garbage") is None
    now = datetime.now(UTC)
    tok = mfa.challenge(uuid4(), uuid4(), 0, now)
    assert mfa.read_challenge(tok, now) is not None
    assert mfa.read_challenge(tok[:-2] + ("A" if tok[-2] != "A" else "B") + tok[-1], now) is None


# --- sign-in -----------------------------------------------------------------------------------------
async def test_nothing_changes_for_someone_who_has_not_turned_it_on(app_client, world, api_key_factory):
    _, email = await staff(app_client, world, api_key_factory)
    app_client.cookies.clear()
    r = await login(app_client, email)
    assert r.status_code == 200 and "mfa_required" not in r.json() and r.json()["email"] == email


async def test_with_it_on_the_password_alone_makes_no_session_and_the_code_does(app_client, world, api_key_factory):
    csrf, email = await staff(app_client, world, api_key_factory)
    secret, _ = await turn_on(app_client, csrf)
    app_client.cookies.clear()
    r = await login(app_client, email)
    assert r.status_code == 200 and r.json() == {"mfa_required": True}
    assert (await app_client.get("/api/v1/session")).status_code == 401  # the password alone signed nobody in
    r = await app_client.post("/api/v1/session/mfa", json={"code": a_later_code(secret)})
    assert r.status_code == 200 and r.json()["email"] == email
    assert (await app_client.get("/api/v1/session")).status_code == 200
    ok = [e for e in await rows(world, m.AuditEvent) if e.action == "login.ok" and (e.metadata_ or {}).get("mfa")]
    assert [e.metadata_["mfa"] for e in ok] == ["totp"] and secret not in str(ok[0].metadata_)


async def test_the_code_step_needs_the_password_step_first(app_client, world, api_key_factory):
    csrf, _ = await staff(app_client, world, api_key_factory)
    secret, _ = await turn_on(app_client, csrf)
    app_client.cookies.clear()
    r = await app_client.post("/api/v1/session/mfa", json={"code": a_later_code(secret)})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "MFA_EXPIRED"


async def test_a_used_code_does_not_work_twice(app_client, world, api_key_factory):
    csrf, email = await staff(app_client, world, api_key_factory)
    secret, _ = await turn_on(app_client, csrf)
    code = a_later_code(secret)
    for expect in (200, 401):
        app_client.cookies.clear()
        await login(app_client, email)
        assert (await app_client.post("/api/v1/session/mfa", json={"code": code})).status_code == expect


async def test_a_recovery_code_signs_in_once_and_says_how_many_are_left(app_client, world, api_key_factory):
    csrf, email = await staff(app_client, world, api_key_factory)
    _, codes = await turn_on(app_client, csrf)
    app_client.cookies.clear()
    await login(app_client, email)
    r = await app_client.post("/api/v1/session/mfa", json={"code": codes[3].upper()})
    assert r.status_code == 200 and r.json()["recovery_left"] == 9
    app_client.cookies.clear()
    await login(app_client, email)
    assert (await app_client.post("/api/v1/session/mfa", json={"code": codes[3]})).status_code == 401


async def test_guessing_codes_locks_the_code_step(app_client, world, api_key_factory):
    csrf, email = await staff(app_client, world, api_key_factory)
    secret, _ = await turn_on(app_client, csrf)
    app_client.cookies.clear()
    await login(app_client, email)
    for _ in range(5):
        assert (await app_client.post("/api/v1/session/mfa", json={"code": "000000"})).status_code == 401
    r = await app_client.post("/api/v1/session/mfa", json={"code": a_later_code(secret)})  # the right code, during the lock
    assert r.status_code == 429 and r.json()["detail"]["code"] == "LOGIN_LOCKED"
    assert any(e.action == "login.mfa_failed" for e in await rows(world, m.AuditEvent))


async def test_a_reset_password_still_asks_for_the_code(app_client, world, api_key_factory):
    """Mail that reaches the wrong hands resets the password, but the phone is still needed."""
    csrf, email = await staff(app_client, world, api_key_factory)
    await turn_on(app_client, csrf)
    r = await app_client.post("/api/v1/session/password", json={"current": PASSWORD, "new": "Mat-khau-moi-4821"}, headers=h(csrf))
    assert r.status_code == 200
    app_client.cookies.clear()
    assert (await login(app_client, email, "Mat-khau-moi-4821")).json() == {"mfa_required": True}


# --- the account page --------------------------------------------------------------------------------
async def test_setting_up_needs_the_password_and_a_code_from_the_new_secret(app_client, world, api_key_factory):
    csrf, _ = await staff(app_client, world, api_key_factory)
    assert (await app_client.post("/api/v1/account/mfa/setup", json={"password": "sai-mat-khau-1"}, headers=h(csrf))).status_code == 403
    r = await app_client.post("/api/v1/account/mfa/setup", json={"password": PASSWORD}, headers=h(csrf))
    secret = r.json()["secret"]
    assert (await app_client.post("/api/v1/account/mfa/enable", json={"code": "123456"}, headers=h(csrf))).status_code == 422
    assert (await app_client.get("/api/v1/account/mfa")).json()["enabled"] is False  # a wrong scan locks nobody out
    r = await app_client.post("/api/v1/account/mfa/enable", json={"code": mfa.code_at(secret, mfa.step_of(datetime.now(UTC)))}, headers=h(csrf))
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
    st = (await app_client.get("/api/v1/account/mfa")).json()
    assert st["enabled"] is True and st["recovery_left"] == 10 and "secret" not in st  # the secret is never shown again
    async with tenant_session(world.t.id) as s:
        u = [x for x in (await s.execute(select(m.AppUser))).scalars() if x.mfa_enabled_at]
    assert u and secret not in (u[0].mfa_secret_enc or "") and all(c not in str(u[0].mfa_recovery) for c in r.json()["recovery_codes"])


async def test_turning_it_off_needs_the_password_and_a_current_code(app_client, world, api_key_factory):
    csrf, email = await staff(app_client, world, api_key_factory)
    secret, _ = await turn_on(app_client, csrf)
    bad = await app_client.post("/api/v1/account/mfa/disable", json={"password": PASSWORD, "code": "000000"}, headers=h(csrf))
    assert bad.status_code == 422
    ok = await app_client.post("/api/v1/account/mfa/disable", json={"password": PASSWORD, "code": a_later_code(secret)}, headers=h(csrf))
    assert ok.status_code == 200 and ok.json()["enabled"] is False
    app_client.cookies.clear()
    assert "mfa_required" not in (await login(app_client, email)).json()
    assert {"mfa.enabled", "mfa.disabled"} <= {e.action for e in await rows(world, m.AuditEvent)}


async def test_new_recovery_codes_retire_the_old_ones(app_client, world, api_key_factory):
    csrf, email = await staff(app_client, world, api_key_factory)
    secret, old = await turn_on(app_client, csrf)
    r = await app_client.post("/api/v1/account/mfa/recovery-codes", json={"password": PASSWORD, "code": a_later_code(secret)}, headers=h(csrf))
    new = r.json()["recovery_codes"]
    assert r.status_code == 200 and not set(new) & set(old)
    app_client.cookies.clear()
    await login(app_client, email)
    assert (await app_client.post("/api/v1/session/mfa", json={"code": old[0]})).status_code == 401
    assert (await app_client.post("/api/v1/session/mfa", json={"code": new[0]})).status_code == 200


# --- the owner, for staff; the operator, for an owner ------------------------------------------------
async def test_the_owner_turns_it_off_for_staff_who_lost_their_phone(app_client, world, api_key_factory, mail):
    csrf, email = await staff(app_client, world, api_key_factory)
    await turn_on(app_client, csrf)
    _, okey = await api_key_factory(world.t, "owner", None)
    app_client.cookies.clear()
    ocsrf = await sign_in(app_client, okey)
    team = (await app_client.get("/api/v1/team")).json()["items"]
    target = next(u for u in team if u["email"] == email)
    assert target["mfa"] is True
    assert (await app_client.post(f"/api/v1/team/{target['id']}/mfa/disable", json={"password": "sai-mat-khau-1"}, headers=h(ocsrf))).status_code == 403
    r = await app_client.post(f"/api/v1/team/{target['id']}/mfa/disable", json={"password": PASSWORD}, headers=h(ocsrf))
    assert r.status_code == 200 and r.json()["mfa"] is False and r.json()["sessions_ended"] >= 1  # the lost phone may hold a sign-in
    assert "secret" not in r.text and "recovery" not in r.text  # nothing to hand over: the owner sees no code
    assert any(x["to"] == email and "tắt" in x["subject"] for x in mail.sent)
    app_client.cookies.clear()
    assert "mfa_required" not in (await login(app_client, email)).json()
    assert any(e.action == "mfa.disabled_by_owner" for e in await rows(world, m.AuditEvent))


async def test_staff_cannot_turn_off_anyone_elses_and_an_owner_cannot_turn_off_another_owners(app_client, world, api_key_factory):
    _, okey = await api_key_factory(world.t, "owner", None)
    owner_email = await account_for_key(okey)
    app_client.cookies.clear()
    ocsrf = await sign_in(app_client, okey)
    await turn_on(app_client, ocsrf)
    _, okey2 = await api_key_factory(world.t, "owner", "chu2")  # a second owner, a different account
    app_client.cookies.clear()
    o2 = await sign_in(app_client, okey2)
    first = next(u for u in (await app_client.get("/api/v1/team")).json()["items"] if u["email"] == owner_email)
    r = await app_client.post(f"/api/v1/team/{first['id']}/mfa/disable", json={"password": PASSWORD}, headers=h(o2))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "OWNER_MFA"
    scsrf, _ = await staff(app_client, world, api_key_factory, "nv2")
    assert (await app_client.post(f"/api/v1/team/{first['id']}/mfa/disable", json={"password": PASSWORD}, headers=h(scsrf))).status_code == 403


async def test_the_operator_resets_an_owner_from_the_command_line(app_client, world, api_key_factory, capsys):
    _, okey = await api_key_factory(world.t, "owner", None)
    email = await account_for_key(okey)
    app_client.cookies.clear()
    await turn_on(app_client, await sign_in(app_client, okey))
    await cli.cmd_reset_mfa(argparse.Namespace(email=email))
    assert "mfa=off" in capsys.readouterr().out
    app_client.cookies.clear()
    assert "mfa_required" not in (await login(app_client, email)).json()
    assert any(e.action == "mfa.reset" for e in await rows(world, m.AuditEvent))
