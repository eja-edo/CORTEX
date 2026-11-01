"""WP29: outside data sources and MCP servers."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from support import h, sign_in
from wp5_support import rows

from cortex_leads.connectors import mcp_remote
from cortex_leads.connectors.http_readonly import ConnectorError
from cortex_leads.core.context import RunContext, Scope, SystemPrincipal
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.tools.external import ExternalArgs, _make_external_lookup

HTTP = {"kind": "http_readonly", "name": "kho-hang", "description": "Tồn kho theo mã", "url": "https://api.shop.example/v1/stock?sku={q}",
        "host": "api.shop.example", "auth_header": "X-Api-Key", "secret": "sk-very-secret-123"}
TOOLS = [{"name": "get_schedule", "description": "Lịch học của một lớp", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
         {"name": "update_schedule", "description": "Đổi lịch học", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": False}}]


async def as_owner(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "owner", None)
    app_client.cookies.clear()
    csrf = await sign_in(app_client, key)
    r = await app_client.post("/api/v1/sandboxes", json={"template": "owner_digest", "title": "Báo cáo cho chủ"}, headers=h(csrf))
    return csrf, r.json()["id"]


@pytest.fixture
def fake_mcp(monkeypatch):
    state = {"tools": TOOLS}

    async def describe(source, secret, **_):
        return state["tools"]
    monkeypatch.setattr(mcp_remote, "describe", describe)
    return state


async def test_adding_an_http_source_pins_it_encrypts_the_key_and_never_shows_it_again(app_client, world, api_key_factory):
    csrf, digest = await as_owner(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/sources", json={**HTTP, "sandbox_id": digest}, headers=h(csrf))
    assert r.status_code == 201
    row = (await rows(world, m.ToolConnector))[0]
    assert row.secret_enc and b"sk-very-secret" not in row.secret_enc and len(row.pin_sha256) == 64
    d = (await app_client.get(f"/api/v1/sources/{r.json()['id']}")).json()
    assert d["auth_saved"] is True and d["pin_ok"] and d["host"] == "api.shop.example" and d["sandbox"]["title"] == "Báo cáo cho chủ"
    assert "sk-very-secret" not in (await app_client.get("/api/v1/sources")).text + str(d)
    ev = [e for e in await rows(world, m.AuditEvent) if e.action == "source.created"]
    assert len(ev) == 1 and "sk-very-secret" not in str(ev[0].metadata_) and ev[0].metadata_["has_key"] is True


async def test_a_source_cannot_be_attached_to_a_sandbox_that_talks_to_customers(app_client, world, api_key_factory):
    csrf, digest = await as_owner(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/sources", json={**HTTP, "sandbox_id": str(world.sb.id)}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SANDBOX_TALKS_TO_CUSTOMERS"
    lst = (await app_client.get("/api/v1/sources")).json()
    assert [x["id"] for x in lst["attachable"]] == [digest] and [x["id"] for x in lst["blocked"]] == [str(world.sb.id)]
    r = await app_client.post("/api/v1/sources", json={**HTTP, "sandbox_id": digest, "url": "http://api.shop.example/{q}"}, headers=h(csrf))
    assert r.status_code == 422
    r = await app_client.post("/api/v1/sources", json={**HTTP, "sandbox_id": digest, "host": "evil.example"}, headers=h(csrf))
    assert r.status_code == 422
    await app_client.post("/api/v1/sources", json={**HTTP, "sandbox_id": digest}, headers=h(csrf))
    assert (await app_client.post("/api/v1/sources", json={**HTTP, "sandbox_id": digest}, headers=h(csrf))).json()["detail"]["code"] == "NAME_TAKEN"


async def test_mcp_shows_what_the_server_offers_and_pins_exactly_one_read_only_tool(app_client, world, api_key_factory, fake_mcp):
    csrf, digest = await as_owner(app_client, world, api_key_factory)
    body = {"url": "https://mcp.lms.example/mcp", "host": "mcp.lms.example", "secret": "tok-123"}
    offered = (await app_client.post("/api/v1/sources/mcp/describe", json=body, headers=h(csrf))).json()["tools"]
    assert [(t["name"], t["read_only"]) for t in offered] == [("get_schedule", True), ("update_schedule", False)]
    mk = {**body, "kind": "mcp", "name": "mcp-lich-hoc", "sandbox_id": digest}
    assert (await app_client.post("/api/v1/sources", json={**mk, "tool": "update_schedule"}, headers=h(csrf))).json()["detail"]["code"] == "NOT_READ_ONLY"
    assert (await app_client.post("/api/v1/sources", json=mk, headers=h(csrf))).status_code == 422  # no tool chosen
    assert (await app_client.post("/api/v1/sources", json={**mk, "tool": "get_schedule", "arg": "lop"}, headers=h(csrf))).status_code == 201
    row = (await rows(world, m.ToolConnector))[0]
    assert row.kind == "mcp" and row.source["expose"] == [{"remote": "get_schedule", "arg": "lop"}] and row.source["tool_pin"]


async def test_a_changed_tool_definition_locks_the_source_and_a_review_pins_the_new_one(app_client, world, api_key_factory, fake_mcp, monkeypatch):
    csrf, digest = await as_owner(app_client, world, api_key_factory)
    body = {"url": "https://mcp.lms.example/mcp", "host": "mcp.lms.example", "kind": "mcp", "name": "mcp-lich-hoc", "sandbox_id": digest, "tool": "get_schedule"}
    sid = (await app_client.post("/api/v1/sources", json=body, headers=h(csrf))).json()["id"]

    async def changed(conn, query, **_):
        raise ConnectorError("TOOL_CHANGED")
    monkeypatch.setattr(mcp_remote, "call", changed)
    look = _make_external_lookup(lambda: None, None)
    async with tenant_session(world.t.id) as s:
        other = next(x.id for x in await rows(world, m.Sandbox) if x.id != world.sb.id)
        ctx = RunContext(run_id=uuid4(), tenant_id=world.t.id, sandbox_id=other, profile="digest", profile_version=1, principal=SystemPrincipal(job="t"), scope=Scope())
        res = await look(ctx, s, ExternalArgs(connector="mcp-lich-hoc", query="lop 7"))
    assert res.status == "error"
    d = (await app_client.get(f"/api/v1/sources/{sid}")).json()
    assert d["state"] == "alert" and "đã thay đổi" in d["alert"]
    fake_mcp["tools"] = [{**TOOLS[0], "description": "Lịch học (đã đổi nghĩa)"}]
    assert (await app_client.post(f"/api/v1/sources/{sid}/review", headers=h(csrf))).json() == {"state": "active"}
    d2 = (await app_client.get(f"/api/v1/sources/{sid}")).json()
    assert d2["state"] == "active" and d2["alert"] is None and d2["pin_ok"]
    fake_mcp["tools"] = [{**TOOLS[0], "annotations": {"destructiveHint": True}}]
    assert (await app_client.post(f"/api/v1/sources/{sid}/review", headers=h(csrf))).status_code == 422  # no longer read-only: refused


async def test_locking_hides_a_source_and_keeps_it_and_restoring_brings_it_back(app_client, world, api_key_factory):
    csrf, digest = await as_owner(app_client, world, api_key_factory)
    sid = (await app_client.post("/api/v1/sources", json={**HTTP, "sandbox_id": digest}, headers=h(csrf))).json()["id"]
    assert (await app_client.post(f"/api/v1/sources/{sid}/unlock", headers=h(csrf))).status_code == 409
    assert (await app_client.post(f"/api/v1/sources/{sid}/lock", headers=h(csrf))).json() == {"state": "deleted"}
    row = (await rows(world, m.ToolConnector))[0]
    assert row.status == "disabled" and row.deleted_at and row.deleted_by == "staff:owner" and row.secret_enc  # everything is kept
    lst = (await app_client.get("/api/v1/sources")).json()
    assert lst["counts"] == {"all": 0, "deleted": 1} and lst["items"][0]["state"] == "deleted"
    assert (await app_client.post(f"/api/v1/sources/{sid}/unlock", headers=h(csrf))).json() == {"state": "active"}
    assert (await app_client.get("/api/v1/sources")).json()["counts"] == {"all": 1, "deleted": 0}
    assert {e.action for e in await rows(world, m.AuditEvent)} >= {"source.lock", "source.unlock"}


async def test_the_page_shows_calls_errors_and_the_last_call_from_the_log(app_client, world, api_key_factory, seed):
    csrf, digest = await as_owner(app_client, world, api_key_factory)
    await app_client.post("/api/v1/sources", json={**HTTP, "sandbox_id": digest}, headers=h(csrf))
    for st in ("ok", "ok", "error"):
        await seed(m.ActionLog(tenant_id=world.t.id, action_id=uuid4(), actor="run", tool="external_lookup", args_masked={"connector": "kho-hang"},
                               status=st, evidence={}, at=datetime.now(UTC)))
    it = (await app_client.get("/api/v1/sources")).json()["items"][0]
    assert (it["calls_7d"], it["errors_7d"]) == (3, 1) and it["last_at"].endswith("Z")


async def test_sources_are_the_owners_page(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    await sign_in(app_client, key)
    assert (await app_client.get("/api/v1/sources")).status_code == 403
