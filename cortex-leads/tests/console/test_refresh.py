"""Access token and refresh token (auth/sessions.py `refresh`, POST /session/refresh): the access token is short, the refresh token is long, opaque,
swapped on every use, and a spent one coming back after a moment ends the whole sign-in."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from support import PASSWORD, account_for_key, h, sign_in

from cortex_leads.app import create_app
from cortex_leads.auth import tokens
from cortex_leads.config import get_settings

R = "/api/v1/session/refresh"


async def _in(app_client, world, api_key_factory, role="staff", ref="nv1"):
    _, key = await api_key_factory(world.t, role, ref if role == "staff" else None)
    app_client.cookies.clear()
    csrf = await sign_in(app_client, key)
    return csrf, await account_for_key(key)


def _device():
    from httpx import ASGITransport, AsyncClient
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


def _jar(client, name):
    return next((c.value for c in client.cookies.jar if c.name == name), None)


async def test_signing_in_hands_out_a_short_access_token_and_a_seven_day_refresh_token(app_client, world, api_key_factory):
    await _in(app_client, world, api_key_factory)
    cfg = get_settings()
    access, refresh = _jar(app_client, "cl_session"), _jar(app_client, "cl_refresh")
    c = tokens.decode(access)
    assert c.expires_at - c.issued_at == timedelta(minutes=cfg.ACCESS_TOKEN_MINUTES) and cfg.ACCESS_TOKEN_MINUTES <= 15
    assert refresh and refresh.count(".") == 1 and refresh.split(".")[0] == str(c.sid)  # `<sign-in>.<secret>`, nothing a person could read
    cookie = next(x for x in app_client.cookies.jar if x.name == "cl_refresh")
    assert cookie.path == "/api/v1/session"  # only the sign-in endpoints ever see it
    assert 6 * 86400 < (cookie.expires - datetime.now(UTC).timestamp()) <= 7 * 86400


async def test_the_refresh_token_is_never_stored_only_its_hash(app_client, world, api_key_factory, owner_engine):
    await _in(app_client, world, api_key_factory)
    sid, secret = _jar(app_client, "cl_refresh").split(".")
    async with owner_engine.begin() as c:
        row = (await c.execute(text("select refresh_hash, refresh_prev_hash from auth_session where id = :i"), {"i": sid})).one()
    assert row.refresh_hash and secret not in row.refresh_hash and row.refresh_prev_hash is None


def _from(resp, name):
    """The value of a cookie a response asked the browser to keep (None: not mentioned; "": asked to delete it)."""
    for raw in resp.headers.get_list("set-cookie"):
        if raw.startswith(name + "="):
            return raw.split(";", 1)[0].split("=", 1)[1].strip('"')
    return None


async def _call(client, method, path, access=None, refresh=None, **kw):
    """One request as a browser would make it holding exactly these two cookies (no jar, so no test ever sends a stale one by accident)."""
    client.cookies.clear()
    cookie = "; ".join(f"{k}={v}" for k, v in (("cl_session", access), ("cl_refresh", refresh)) if v)
    return await client.request(method, path, headers={**kw.pop("headers", {}), **({"Cookie": cookie} if cookie else {})}, **kw)


async def _expired_access(world, email, minutes=20):
    from sqlalchemy import select

    from cortex_leads.db import models as m
    from cortex_leads.db.session import tenant_session
    now = datetime.now(UTC)
    async with tenant_session(world.t.id) as s:
        user = (await s.execute(select(m.AppUser).where(m.AppUser.email == email))).scalar_one()
        sid = (await s.execute(select(m.AuthSession.id).where(m.AuthSession.user_id == user.id, m.AuthSession.revoked_at.is_(None)))).scalars().first()
        return tokens.issue(user, await s.get(m.Tenant, user.tenant_id), sid, now - timedelta(minutes=minutes), now - timedelta(minutes=minutes))


async def _start(app_client, world, api_key_factory, role="staff", ref="nv1"):
    csrf, email = await _in(app_client, world, api_key_factory, role, ref)
    return csrf, email, _jar(app_client, "cl_session"), _jar(app_client, "cl_refresh")


async def test_an_expired_access_token_is_swapped_for_a_new_one_through_the_refresh_token(app_client, world, api_key_factory, owner_engine):
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    old = await _expired_access(world, email)
    assert (await _call(app_client, "GET", "/api/v1/session", old, refresh)).status_code == 401  # the access token alone is gone
    r = await _call(app_client, "POST", R, old, refresh)
    assert r.status_code == 200 and r.json()["email"] == email and r.json()["csrf"] == csrf  # the page's CSRF token survives: it belongs to the sign-in
    new_access, new_refresh = _from(r, "cl_session"), _from(r, "cl_refresh")
    assert new_access and new_refresh and new_refresh != refresh  # the refresh token was swapped, not kept
    assert (await _call(app_client, "GET", "/api/v1/session", new_access, new_refresh)).status_code == 200
    sid = refresh.split(".")[0]
    async with owner_engine.begin() as c:
        row = (await c.execute(text("select refresh_hash, refresh_prev_hash, refresh_expires_at, last_seen_at from auth_session where id = :i"), {"i": sid})).one()
    assert row.refresh_prev_hash and row.refresh_hash != row.refresh_prev_hash and row.refresh_expires_at > datetime.now(UTC) + timedelta(days=6)
    assert datetime.now(UTC) - row.last_seen_at < timedelta(minutes=1)


async def test_the_refresh_token_can_be_renewed_again_and_again(app_client, world, api_key_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "REFRESH_REUSE_GRACE_SECONDS", 0)
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    for _ in range(4):
        r = await _call(app_client, "POST", R, access, refresh)
        assert r.status_code == 200
        access, refresh = _from(r, "cl_session"), _from(r, "cl_refresh")
    assert (await _call(app_client, "GET", "/api/v1/session", access, refresh)).status_code == 200


async def test_a_spent_refresh_token_a_moment_later_is_two_tabs_not_a_thief(app_client, world, api_key_factory):
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    first = await _call(app_client, "POST", R, None, refresh)
    second = await _call(app_client, "POST", R, None, refresh)  # the other tab, with the cookie it had before the first answer arrived
    assert first.status_code == 200 and second.status_code == 200
    assert _from(second, "cl_session") and _from(second, "cl_refresh") is None  # an access token only: the new refresh token is already in the browser
    assert (await _call(app_client, "GET", "/api/v1/session", _from(second, "cl_session"), _from(first, "cl_refresh"))).status_code == 200


async def test_a_spent_refresh_token_after_the_grace_ends_the_whole_sign_in(app_client, world, api_key_factory, monkeypatch):
    from sqlalchemy import select

    from cortex_leads.db import models as m
    from cortex_leads.db.session import tenant_session
    monkeypatch.setattr(get_settings(), "REFRESH_REUSE_GRACE_SECONDS", 0)
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    mine = await _call(app_client, "POST", R, None, refresh)  # the owner of the browser renews
    assert mine.status_code == 200
    thief = await _call(app_client, "POST", R, None, refresh)  # someone holding the copy that has just been spent
    assert thief.status_code == 401 and thief.json()["detail"]["code"] == "REFRESH_INVALID"
    assert _from(thief, "cl_refresh") == "" and _from(thief, "cl_session") == ""  # and the browser is told to forget both
    assert (await _call(app_client, "POST", R, None, _from(mine, "cl_refresh"))).status_code == 401  # the honest holder is out too: nobody can tell which it was
    assert (await _call(app_client, "GET", "/api/v1/session", _from(mine, "cl_session"), None)).status_code == 401
    async with tenant_session(world.t.id) as s:
        acts = {e.action for e in (await s.execute(select(m.AuditEvent))).scalars()}
    assert "refresh.reused" in acts


async def test_a_refresh_token_ends_after_its_seven_days_and_the_sign_in_after_its_own_end(app_client, world, api_key_factory, owner_engine):
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    async with owner_engine.begin() as c:
        await c.execute(text("update auth_session set refresh_expires_at = now() - interval '1 second' where id = :i"), {"i": refresh.split(".")[0]})
    assert (await _call(app_client, "POST", R, None, refresh)).status_code == 401  # unused for a week
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    async with owner_engine.begin() as c:
        await c.execute(text("update auth_session set expires_at = now() - interval '1 second' where id = :i"), {"i": refresh.split(".")[0]})
    assert (await _call(app_client, "POST", R, None, refresh)).status_code == 401  # renewed all along, but the sign-in has reached its end


async def test_a_renewed_refresh_token_never_outlives_the_sign_in(app_client, world, api_key_factory, owner_engine):
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    sid = refresh.split(".")[0]
    async with owner_engine.begin() as c:
        await c.execute(text("update auth_session set expires_at = now() + interval '1 day' where id = :i"), {"i": sid})
    assert (await _call(app_client, "POST", R, None, refresh)).status_code == 200
    async with owner_engine.begin() as c:
        row = (await c.execute(text("select refresh_expires_at, expires_at from auth_session where id = :i"), {"i": sid})).one()
    assert row.refresh_expires_at <= row.expires_at  # seven days from now would be past the end: it is cut to the end


async def test_forged_or_missing_refresh_tokens_get_nothing(app_client, world, api_key_factory):
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    sid, secret = refresh.split(".")
    for bad in (None, "x", f"{sid}.{'A' * len(secret)}", f"00000000-0000-0000-0000-000000000000.{secret}", f"{sid}.{secret}x", secret):
        r = await _call(app_client, "POST", R, None, bad)
        assert r.status_code == 401 and r.json()["detail"]["code"] == "REFRESH_INVALID", bad
    assert (await _call(app_client, "POST", R, None, refresh)).status_code == 200  # the real one is untouched by the failed guesses


async def test_signing_out_with_only_the_refresh_token_still_ends_it_for_good(app_client, world, api_key_factory):
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    assert (await _call(app_client, "POST", "/api/v1/session/logout", None, refresh)).status_code == 200  # the access token ran out; the person signs out anyway
    assert (await _call(app_client, "POST", R, None, refresh)).status_code == 401
    assert (await _call(app_client, "GET", "/api/v1/session", access, None)).status_code == 401  # and the access token that was still around is dead too


async def test_a_locked_account_cannot_refresh(app_client, world, api_key_factory):
    from sqlalchemy import select

    from cortex_leads.auth.users import change_role_or_status
    from cortex_leads.db import models as m
    from cortex_leads.db.session import tenant_session
    csrf, email, access, refresh = await _start(app_client, world, api_key_factory)
    async with tenant_session(world.t.id) as s:
        user = (await s.execute(select(m.AppUser).where(m.AppUser.email == email))).scalar_one()
        await change_role_or_status(s, user, role=None, status="disabled", now=datetime.now(UTC))
    assert (await _call(app_client, "POST", R, None, refresh)).status_code == 401


async def test_signing_one_device_out_or_all_of_them_takes_the_refresh_token_with_it(app_client, world, api_key_factory):
    csrf, email, a_access, a_refresh = await _start(app_client, world, api_key_factory)
    async with _device() as phone:
        b = await phone.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})
        b_refresh = _from(b, "cl_refresh")
        others = [x for x in (await _call(app_client, "GET", "/api/v1/session/sessions", a_access, a_refresh)).json()["items"] if not x["current"]]
        assert (await _call(app_client, "POST", f"/api/v1/session/sessions/{others[0]['id']}/revoke", a_access, a_refresh, headers=h(csrf))).status_code == 200
        assert (await _call(phone, "POST", R, None, b_refresh)).status_code == 401  # that device cannot refresh back in
        a2 = await _call(app_client, "POST", R, None, a_refresh)
        assert a2.status_code == 200  # the other one carries on
        assert (await _call(app_client, "POST", "/api/v1/session/logout-all", _from(a2, "cl_session"), a_refresh, headers=h(csrf))).status_code == 200
        assert (await _call(app_client, "POST", R, None, a_refresh)).status_code == 401
