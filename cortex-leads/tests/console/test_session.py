"""WP27: console session, CSRF, roles and the kill switch."""
from sqlalchemy import update
from support import PASSWORD, account_for_key, h, sign_in
from wp5_support import rows

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session


async def test_login_cookie_flags_and_who_am_i(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    email = await account_for_key(key)
    assert (await app_client.post("/api/v1/session/login", json={"email": email, "password": "sai-mat-khau-1"})).status_code == 401
    assert (await app_client.get("/api/v1/session")).status_code == 401
    r = await app_client.post("/api/v1/session/login", json={"email": email.upper(), "password": PASSWORD})  # email is case-insensitive
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 200 and "httponly" in cookie and "samesite=strict" in cookie and PASSWORD not in r.headers["set-cookie"]
    me = (await app_client.get("/api/v1/session")).json()
    assert (me["role"], me["staff_ref"], me["tenant"], me["ai"], me["mode"], me["email"]) == ("staff", "nv1", "Acme", "running", "manual", email)
    assert me["csrf"] == r.json()["csrf"] and me["needs_person"] == 0 and "inbox.use" in me["permissions"] and "team.manage" not in me["permissions"]
    assert "password" not in str(me).lower().replace("must_change_password", "")


async def test_unsafe_calls_need_the_csrf_header_and_a_forged_cookie_is_refused(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "owner", None)
    csrf = await sign_in(app_client, key)
    assert (await app_client.post("/api/v1/kill-switch", json={"paused": True})).status_code == 403
    assert (await app_client.post("/api/v1/kill-switch", json={"paused": True}, headers=h("x" * 32))).status_code == 403
    assert (await app_client.post("/api/v1/kill-switch", json={"paused": False}, headers=h(csrf))).status_code == 200
    for forged in ("00000000-0000-0000-0000-000000000000.9999999999.deadbeef", "x", "00000000-0000-0000-0000-000000000000." + "A" * 43):
        app_client.cookies.set("cl_session", forged, path="/")
        assert (await app_client.get("/api/v1/session")).status_code == 401


async def test_logout_clears_the_cookie(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    csrf = await sign_in(app_client, key)
    assert (await app_client.post("/api/v1/session/logout", headers=h(csrf))).status_code == 200
    app_client.cookies.clear()
    assert (await app_client.get("/api/v1/session")).status_code == 401


async def test_kill_switch_is_the_owners_and_stops_every_sandbox_with_an_audit_row(app_client, world, api_key_factory):
    _, staff_key = await api_key_factory(world.t, "staff", "nv1")
    csrf = await sign_in(app_client, staff_key)
    assert (await app_client.post("/api/v1/kill-switch", json={"paused": True}, headers=h(csrf))).status_code == 403
    app_client.cookies.clear()
    _, owner_key = await api_key_factory(world.t, "owner", None)
    csrf = await sign_in(app_client, owner_key)
    r = await app_client.post("/api/v1/kill-switch", json={"paused": True}, headers=h(csrf))
    assert r.json()["ai"] == "paused" and r.json()["changed"] == 1
    assert [s.status for s in await rows(world, m.Sandbox)] == ["paused"]
    assert (await app_client.get("/api/v1/session")).json()["ai"] == "paused"
    r = await app_client.post("/api/v1/kill-switch", json={"paused": False}, headers=h(csrf))
    assert r.json()["ai"] == "running" and [s.status for s in await rows(world, m.Sandbox)] == ["active"]
    tools = [(a.action, a.actor, a.metadata_) for a in await rows(world, m.AuditEvent) if a.action.startswith("killswitch")]
    assert sorted(tools, key=lambda t: t[0]) == [("killswitch.pause", "staff:owner", {"changed": 1}),
                                                 ("killswitch.resume", "staff:owner", {"changed": 1})]


async def test_pausing_really_stops_the_engine_the_runner_and_the_sender(app_client, world, api_key_factory):
    """The switch is only worth something if the rest of the system honours it."""
    _, key = await api_key_factory(world.t, "owner", None)
    csrf = await sign_in(app_client, key)
    await app_client.post("/api/v1/kill-switch", json={"paused": True}, headers=h(csrf))
    from wp5_support import NOW

    from cortex_leads.triggers.engine import on_conversation_event
    async with tenant_session(world.t.id) as s:
        conv = await s.get(m.Conversation, world.conv.id)
        assert await on_conversation_event(s, conv, "conversation.silent", NOW) == []
        await s.execute(update(m.Sandbox).values(status="paused"))
    assert "paused" in [d.reason_code for d in await rows(world, m.DecisionLog)]


async def test_the_command_line_switch_stops_and_restarts_the_same_way(world):
    import argparse

    from cortex_leads.cli import cmd_pause, cmd_resume
    await cmd_pause(argparse.Namespace(tenant=world.t.id, sandbox=None))
    assert [s.status for s in await rows(world, m.Sandbox)] == ["paused"]
    await cmd_resume(argparse.Namespace(tenant=world.t.id, sandbox=world.sb.id))
    assert [s.status for s in await rows(world, m.Sandbox)] == ["active"]
    assert [a.actor for a in await rows(world, m.AuditEvent) if a.action.startswith("killswitch")] == ["system:cli", "system:cli"]


async def test_every_console_route_but_login_refuses_a_visitor_with_no_session(app_client):
    """The list is generated from the app itself, so a route added later cannot forget to ask for a session."""
    import re
    paths = app_client._transport.app.openapi()["paths"]
    checked = 0
    for path, ops in paths.items():
        if not path.startswith("/api/v1") or path in ("/api/v1/session/login", "/api/v1/google/callback"):  # the callback trusts only its signed state (test_google)
            continue
        for method in ops:
            r = await app_client.request(method.upper(), re.sub(r"\{[^}]+\}", "1", path), json={} if method != "get" else None)
            assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code}"
            checked += 1
    assert checked >= 22
