"""WP20: http_readonly connector. One GET to a listed host; nothing else gets through."""
import json
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from cortex_leads.config import get_settings
from cortex_leads.connectors.http_readonly import ConnectorError, fetch, pin_of, validate_source
from cortex_leads.core.context import CustomerPrincipal, RunContext, Scope, SystemPrincipal
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.tools.external import register_external
from cortex_leads.tools.registry import ToolRegistry

SOURCE = {"url": "https://api.shop.example/v1/stock?sku={q}", "allow_hosts": ["api.shop.example"]}
PUBLIC = lambda host: _ret(["93.184.216.34"])


async def _ret(v):
    return v


def conn(**kw) -> m.ToolConnector:
    src = kw.pop("source", SOURCE)
    base = dict(id=uuid4(), tenant_id=uuid4(), sandbox_id=uuid4(), name="kho", kind="http_readonly", source=src,
                description="", secret_enc=None, pin_sha256=pin_of("http_readonly", src), status="active")
    return m.ToolConnector(**{**base, **kw})


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ok_json(body, status=200, ctype="application/json"):
    return lambda req: httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": ctype})


def test_source_must_be_https_listed_and_hold_a_query_slot():
    validate_source(SOURCE)
    for bad in ({**SOURCE, "url": "http://api.shop.example/{q}"}, {**SOURCE, "allow_hosts": []},
                {**SOURCE, "allow_hosts": ["other.example"]}, {**SOURCE, "url": "https://api.shop.example/v1"},
                {"url": "https://{q}.shop.example/", "allow_hosts": ["x"]}):
        with pytest.raises(ValueError):
            validate_source(bad)


async def test_answer_is_untrusted_scrubbed_and_the_query_leaves_redacted():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return ok_json({"items": [{"name": "Giày", "contact": "gọi 0901 234 567 hoặc a@x.vn", "stock": 3}]})(req)

    r = await fetch(conn(), "SKU 0901 234 567", client=client(handler), resolve=PUBLIC)
    assert r["untrusted"] is True and r["result"]["items"][0]["stock"] == 3
    assert "0901" not in json.dumps(r) and "a@x.vn" not in json.dumps(r)
    assert "0901" not in seen[0] and "%5BPHONE_1%5D" in seen[0]  # the customer's number never reaches the other side


@pytest.mark.parametrize("addr", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1", "::1"])
async def test_private_addresses_are_refused(addr):
    with pytest.raises(ConnectorError) as e:
        await fetch(conn(), "x", client=client(ok_json({})), resolve=lambda h: _ret([addr]))
    assert e.value.code == "PRIVATE_ADDRESS"


async def test_one_private_answer_among_public_ones_is_still_refused():
    with pytest.raises(ConnectorError) as e:
        await fetch(conn(), "x", client=client(ok_json({})), resolve=lambda h: _ret(["93.184.216.34", "10.0.0.5"]))
    assert e.value.code == "PRIVATE_ADDRESS"


@pytest.mark.parametrize("handler,code", [
    (lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/"}), "UPSTREAM"),  # no redirects
    (lambda r: httpx.Response(500), "UPSTREAM"),
    (ok_json({"a": 1}, ctype="text/html"), "BAD_RESPONSE"),
    (lambda r: httpx.Response(200, content=b"x" * 70_000, headers={"content-type": "application/json"}), "TOO_LARGE"),
    (lambda r: httpx.Response(200, content=b"not json", headers={"content-type": "application/json"}), "BAD_RESPONSE"),
])
async def test_bad_answers_become_named_errors(handler, code):
    with pytest.raises(ConnectorError) as e:
        await fetch(conn(), "x", client=client(handler), resolve=PUBLIC)
    assert e.value.code == code


async def test_edited_config_or_disabled_connector_is_refused():
    edited = conn()
    edited.source = {**SOURCE, "url": "https://api.shop.example/v1/other?x={q}"}  # changed after it was pinned
    with pytest.raises(ConnectorError) as e:
        await fetch(edited, "x", client=client(ok_json({})), resolve=PUBLIC)
    assert e.value.code == "PIN_MISMATCH"
    with pytest.raises(ConnectorError) as e:
        await fetch(conn(status="disabled"), "x", client=client(ok_json({})), resolve=PUBLIC)
    assert e.value.code == "DISABLED"


async def test_secret_goes_in_the_named_header_only():
    src = {**SOURCE, "auth_header": "X-Api-Key"}
    got = {}

    def handler(req):
        got.update(req.headers)
        return ok_json({})(req)
    enc = Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(b"s3cret")
    await fetch(conn(source=src, pin_sha256=pin_of("http_readonly", src), secret_enc=enc), "x",
                client=client(handler), resolve=PUBLIC)
    assert got["x-api-key"] == "s3cret" and "authorization" not in got


async def test_depth_and_size_of_the_answer_are_capped():
    deep: dict = {}
    cur = deep
    for _ in range(12):
        cur["n"] = {}
        cur = cur["n"]
    r = await fetch(conn(), "x", client=client(ok_json({"deep": deep, "many": list(range(500))})), resolve=PUBLIC)
    assert len(r["result"]["many"]) == 50 and "n" in r["result"]["deep"]
    depth, cur = 0, r["result"]["deep"]
    while isinstance(cur, dict) and cur.get("n") is not None:
        depth, cur = depth + 1, cur["n"]
    assert depth <= 6


# --- the tool ---------------------------------------------------------------------------------------
def ctx_for(w, principal) -> RunContext:
    return RunContext(run_id=uuid4(), tenant_id=w.t.id, sandbox_id=w.sb.id, profile="digest_template", profile_version=1,
                      principal=principal, scope=Scope())


@pytest.fixture
def reg():
    r = ToolRegistry()
    register_external(r, client_factory=lambda: client(ok_json({"stock": 3})), resolver=PUBLIC)
    return r


async def seed_conn(w, **kw):
    async with tenant_session(w.t.id) as s:
        s.add(m.ToolConnector(tenant_id=w.t.id, sandbox_id=w.sb.id, name="kho", source=SOURCE,
                              pin_sha256=pin_of("http_readonly", SOURCE), **kw))


async def run_tool(reg, w, principal, args):
    async with tenant_session(w.t.id) as s:
        return await reg.execute(ctx_for(w, principal), s, "external_lookup", args,
                                 allowlist=["external_lookup"], effect_ceiling="read")


async def test_tool_reads_for_a_system_run_and_never_for_a_customer_run(world, reg):
    await seed_conn(world)
    ok = await run_tool(reg, world, SystemPrincipal(job="digest"), {"connector": "kho", "query": "A1"})
    assert ok.status == "ok" and ok.data["untrusted"] is True and ok.data["result"] == {"stock": 3}
    no = await run_tool(reg, world, CustomerPrincipal(contact_id=uuid4()), {"connector": "kho", "query": "A1"})
    assert no.status == "blocked" and no.violations[0].detail == "untrusted_run"


async def test_unknown_connector_lists_the_known_ones_and_other_tenants_are_invisible(world, reg, tenant_factory, sandbox_factory):
    await seed_conn(world)
    r = await run_tool(reg, world, SystemPrincipal(job="digest"), {"connector": "nope", "query": "A1"})
    assert r.status == "not_found" and r.data == {"connectors": ["kho"]}
    other = await tenant_factory()
    sb2 = await sandbox_factory(other)
    async with tenant_session(other.id) as s:
        s.add(m.ToolConnector(tenant_id=other.id, sandbox_id=sb2.id, name="secret-kho", source=SOURCE,
                              pin_sha256=pin_of("http_readonly", SOURCE)))
    r = await run_tool(reg, world, SystemPrincipal(job="digest"), {"connector": "secret-kho", "query": "A1"})
    assert r.status == "not_found" and "secret-kho" not in json.dumps(r.data)


async def test_upstream_failure_says_not_to_guess(world):
    r = ToolRegistry()
    register_external(r, client_factory=lambda: client(lambda req: httpx.Response(503)), resolver=PUBLIC)
    await seed_conn(world)
    out = await run_tool(r, world, SystemPrincipal(job="digest"), {"connector": "kho", "query": "A1"})
    assert out.status == "error" and "đừng đoán" in out.note.lower() and out.error.retryable
