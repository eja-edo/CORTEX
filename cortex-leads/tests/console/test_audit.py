"""WP28: the activity log — what it records, who may read it, and that nobody can rewrite it."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from support import PASSWORD, account_for_key, h, sign_in
from wp5_support import rows

from cortex_leads.audit.service import diff, record, verify
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session


async def events(world, owner_engine=None):
    return sorted(await rows(world, m.AuditEvent), key=lambda e: e.seq)


async def test_logins_leave_a_trail_with_address_browser_and_request_id(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    email = await account_for_key(key)
    r = await app_client.post("/api/v1/session/login", json={"email": email, "password": PASSWORD},
                              headers={"User-Agent": "TestBrowser/1", "X-Request-Id": "req-abc-12345"})
    assert r.headers["X-Request-Id"] == "req-abc-12345"
    (ev,) = await events(world)
    assert (ev.action, ev.actor, ev.actor_role, ev.result, ev.category) == ("login.ok", "staff:nv1", "staff", "success", "auth")
    assert ev.ip and ev.user_agent == "TestBrowser/1" and ev.request_id == "req-abc-12345" and ev.session_id.startswith("s:")
    assert PASSWORD not in str(ev.metadata_) and ev.metadata_["email"] == email


async def test_a_failed_login_keeps_the_email_never_the_password(app_client, world, api_key_factory, owner_engine):
    tried = "Guess-guess-0001"
    for _ in range(2):
        assert (await app_client.post("/api/v1/session/login", json={"email": "ai-do@nowhere.test", "password": tried})).status_code == 401
    async with owner_engine.begin() as c:
        got = (await c.execute(text("select tenant_id, actor, result, metadata, hash from audit_event where action = 'login.failed'"))).all()
    assert len(got) == 2 and all(g[0] is None and g[1] == "unknown" and g[2] == "failed" and g[4] is not None for g in got)
    assert got[0][3]["reason"] == "unknown_email" and got[0][3]["email"] == "ai-do@nowhere.test" and tried not in str(got[0][3])
    assert not await events(world)  # an unknown address belongs to no business, so no business can read it


async def test_a_password_pasted_into_the_email_box_is_never_kept(app_client, world, owner_engine):
    await app_client.post("/api/v1/session/login", json={"email": "Matkhau-That-Cua-Toi-9", "password": "x"})
    async with owner_engine.begin() as c:
        meta = (await c.execute(text("select metadata from audit_event where action = 'login.failed'"))).scalar_one()
    assert "Matkhau" not in str(meta) and meta["email"] == "(không phải email)"


async def test_a_wrong_password_for_a_real_person_is_traced_to_their_business(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    email = await account_for_key(key)
    await app_client.post("/api/v1/session/login", json={"email": email, "password": "sai-mat-khau-9"})
    (ev,) = await events(world)
    assert (ev.action, ev.actor, ev.metadata_["reason"], ev.object_label) == ("login.failed", "staff:nv1", "bad_password", "Người nv1")


async def test_refusals_are_recorded_as_denied(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    csrf = await sign_in(app_client, key)
    assert (await app_client.post("/api/v1/kill-switch", json={"paused": True}, headers=h(csrf))).status_code == 403
    assert (await app_client.post("/api/v1/session/logout")).status_code == 403  # no CSRF header
    got = [(e.action, e.result) for e in await events(world)]
    assert ("permission.refused", "denied") in got and ("csrf.refused", "denied") in got


async def test_staff_read_only_their_own_trail_and_the_owner_reads_all(app_client, world, api_key_factory):
    _, skey = await api_key_factory(world.t, "staff", "nv1")
    await sign_in(app_client, skey)
    mine = (await app_client.get("/api/v1/audit")).json()
    assert mine["total"] == 1 and mine["items"][0]["actor"] == "staff:nv1" and mine["actors"] == ["staff:nv1"]
    assert (await app_client.get("/api/v1/audit/verify")).status_code == 403
    assert (await app_client.get("/api/v1/audit/export")).status_code == 403
    app_client.cookies.clear()
    _, okey = await api_key_factory(world.t, "owner", None)
    await sign_in(app_client, okey)
    allv = (await app_client.get("/api/v1/audit")).json()
    assert allv["total"] == 4 and {i["actor"] for i in allv["items"]} == {"staff:nv1", "staff:owner"}  # + the two refusals of staff
    theirs = [i for i in allv["items"] if i["action"] == "login.ok" and i["actor"] == "staff:nv1"][0]["id"]
    assert (await app_client.get(f"/api/v1/audit/{theirs}")).json()["metadata"]["email"].startswith("nv1@")
    assert (await app_client.get("/api/v1/audit/verify")).json()["ok"] is True


async def test_a_member_of_staff_cannot_open_a_colleagues_line(app_client, world, api_key_factory):
    _, okey = await api_key_factory(world.t, "owner", None)
    await sign_in(app_client, okey)
    oid = (await app_client.get("/api/v1/audit")).json()["items"][0]["id"]
    app_client.cookies.clear()
    _, skey = await api_key_factory(world.t, "staff", "nv1")
    await sign_in(app_client, skey)
    assert (await app_client.get(f"/api/v1/audit/{oid}")).status_code == 404


async def test_pages_have_a_total_and_a_size_from_the_allowed_list(app_client, world, api_key_factory):
    _, okey = await api_key_factory(world.t, "owner", None)
    csrf = await sign_in(app_client, okey)
    async with tenant_session(world.t.id) as s:
        for i in range(25):
            await record(s, world.t.id, actor="staff:owner", role="owner", category="data", action="x", summary=f"việc {i}")
    p1 = (await app_client.get("/api/v1/audit?page_size=10")).json()
    p3 = (await app_client.get("/api/v1/audit?page_size=10&page=3")).json()
    assert (p1["total"], p1["pages"], len(p1["items"]), len(p3["items"])) == (26, 3, 10, 6)
    assert p1["items"][0]["seq"] > p1["items"][-1]["seq"] > p3["items"][0]["seq"]
    assert (await app_client.get("/api/v1/audit?page_size=7")).status_code == 422
    assert (await app_client.get("/api/v1/audit?q=việc 24")).json()["total"] == 1
    assert (await app_client.get("/api/v1/audit?category=auth")).json()["total"] == 1
    assert (await app_client.get("/api/v1/audit?date_from=2999-01-01")).json()["total"] == 0
    assert (await app_client.get("/api/v1/audit?date_from=hôm-qua")).status_code == 422
    csv = await app_client.get("/api/v1/audit/export?q=" + "việc 1")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv") and "việc 1" in csv.text
    assert csrf


async def test_a_line_cannot_be_changed_or_removed_even_by_the_owner_of_the_database(app_client, world, api_key_factory, owner_engine):
    _, key = await api_key_factory(world.t, "owner", None)
    await sign_in(app_client, key)
    for sql in ("update audit_event set summary = 'x'", "delete from audit_event"):
        with pytest.raises(DBAPIError):
            async with owner_engine.begin() as c:
                await c.execute(text(sql))
    async with tenant_session(world.t.id) as s:
        with pytest.raises(DBAPIError):
            await s.execute(text("update audit_event set summary = 'x'"))


async def test_the_chain_notices_a_line_that_was_altered_behind_its_back(app_client, world, api_key_factory, owner_engine):
    _, key = await api_key_factory(world.t, "owner", None)
    await sign_in(app_client, key)
    async with tenant_session(world.t.id) as s:
        for i in range(3):
            await record(s, world.t.id, actor="staff:owner", role="owner", category="data", action="x", summary=f"s{i}")
    async with tenant_session(world.t.id) as s:
        assert (await verify(s, world.t.id))["ok"]
    async with owner_engine.begin() as c:  # a superuser who disables the guard and edits a line
        await c.execute(text("alter table audit_event disable trigger audit_event_no_change"))
        await c.execute(text("update audit_event set summary = 'đã sửa' where summary = 's1'"))
        await c.execute(text("alter table audit_event enable trigger audit_event_no_change"))
    async with tenant_session(world.t.id) as s:
        res = await verify(s, world.t.id)
    assert res["ok"] is False and res["checked"] == 3  # login(1), s0, s1 ← first bad


async def test_other_businesses_never_see_these_lines(app_client, world, api_key_factory, tenant_factory):
    other = await tenant_factory()
    async with tenant_session(other.id) as s:
        await record(s, other.id, actor="staff:x", role="owner", category="data", action="x", summary="của tenant khác")
    _, key = await api_key_factory(world.t, "owner", None)
    await sign_in(app_client, key)
    assert "của tenant khác" not in (await app_client.get("/api/v1/audit?page_size=100")).text
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(text("select count(*) from audit_event where tenant_id = :t"), {"t": other.id})).scalar_one() == 0


async def test_secrets_are_masked_and_changes_show_before_and_after(world):
    async with tenant_session(world.t.id) as s:
        row = await record(s, world.t.id, actor="staff:owner", role="owner", category="config", action="connector.updated", summary="s",
                           changes=diff({"url": "a", "secret": "old", "n": {"x": 1}}, {"url": "b", "secret": "new", "n": {"x": 1}}),
                           metadata={"api_key": "sk-live-123"})
    assert row.metadata_["api_key"] == "***"
    assert row.metadata_["changes"] == [{"field": "secret", "before": "***", "after": "***"}] or \
        {c["field"] for c in row.metadata_["changes"]} == {"url"}


async def test_opening_the_same_thing_twice_is_one_visit(world):
    async with tenant_session(world.t.id) as s:
        from datetime import timedelta
        a = await record(s, world.t.id, actor="staff:nv1", role="staff", category="view", action="conversation.viewed", summary="v",
                         obj=("conversation", "c1", None), once_within=timedelta(minutes=15))
        b = await record(s, world.t.id, actor="staff:nv1", role="staff", category="view", action="conversation.viewed", summary="v",
                         obj=("conversation", "c1", None), once_within=timedelta(minutes=15))
    assert a is not None and b is None
