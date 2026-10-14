import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from bridges.pancake.client import PancakeClient, PancakeError, TokenBucket, load_token
from bridges.pancake.mapper import map_message, sender_role
from bridges.pancake.run import load_cursor, run_once
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.ingest.format import Event

FIX = Path(__file__).parent / "fixtures"
CONVS = json.loads((FIX / "conversations.json").read_text())
MSGS = json.loads((FIX / "messages_psid_1001.json").read_text())
CUSTOMER = MSGS["conv_from"]
NOW = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
TOKEN = "SECRET-PAGE-TOKEN-xyz"


def mapped(msg):
    return map_message(msg, page_id="page123", conversation_id="psid_1001", customer=CUSTOMER,
                       channel_kind="messenger")


def by_id(mid):
    return next(x for x in MSGS["messages"] if x["id"] == mid)


# --- mapper contract: sender.role is load-bearing -----------------------------------------------
def test_roles_customer_staff_bot() -> None:
    assert mapped(by_id("m1"))["sender"] == {"role": "customer"}
    staff = mapped(by_id("m4"))
    assert staff["sender"] == {"role": "staff"} and staff["staff"] == {"external_id": "adm_7"}
    assert mapped(by_id("m3"))["sender"] == {"role": "bot"}


def test_role_rules_edge_cases() -> None:
    assert sender_role({"id": "page123", "admin_id": "a", "is_automated": True}, "page123")[0] == "bot"
    assert sender_role({"id": "page123", "ai_generated": True}, "page123")[0] == "bot"
    assert sender_role({"id": "page123", "uid": "u1"}, "page123") == ("staff", "u1")
    # page-side with no proof of a human: bot, never customer and never staff
    assert sender_role({"id": "page123"}, "page123")[0] == "bot"
    assert sender_role({"id": "psid_9"}, "page123")[0] == "customer"


def test_external_id_stable_utc_and_valid_event() -> None:
    a, b = mapped(by_id("m1")), mapped(by_id("m1"))
    assert a["external_id"] == b["external_id"] == "pancake:page123:m1"
    ev = Event.model_validate(a)  # passes the strict ingest model
    assert ev.occurred_at == datetime(2026, 10, 9, 3, 0, tzinfo=UTC)
    assert Event.model_validate(mapped(by_id("m2"))).attachments  # attachment-only is valid


def test_empty_and_removed_messages_skipped() -> None:
    assert mapped({**by_id("m1"), "original_message": "", "attachments": []}) is None
    assert mapped({**by_id("m1"), "is_removed": True}) is None


# --- client ---------------------------------------------------------------------------------
async def _nosleep(_s: float) -> None:
    return None


def fake_pancake(calls: list[httpx.Request]):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        assert req.url.params["page_access_token"] == TOKEN
        if req.url.path.endswith("/conversations"):
            assert "/v2/" in req.url.path and req.url.params["type"] == "INBOX"
            return httpx.Response(200, json=CONVS)
        assert req.url.path.endswith("/conversations/psid_1001/messages")
        if int(req.url.params.get("current_count", 0)):  # no older page in the fixture
            return httpx.Response(200, json={**MSGS, "messages": []})
        return httpx.Response(200, json=MSGS)
    return handler


def pancake_client(handler, **kw) -> PancakeClient:
    return PancakeClient("page123", TOKEN, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                         sleep=_nosleep, **kw)


async def test_client_get_only_and_retries_429_5xx() -> None:
    seq = iter([429, 503, 200])
    calls: list[httpx.Request] = []

    def handler(req):
        calls.append(req)
        s = next(seq)
        return httpx.Response(s, json=CONVS if s == 200 else {})
    out = await pancake_client(handler).conversations()
    assert len(out) == 1 and len(calls) == 3
    assert {c.method for c in calls} == {"GET"}


async def test_client_error_never_leaks_token(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    c = pancake_client(lambda r: httpx.Response(500), retries=1)
    with pytest.raises(PancakeError) as e:
        await c.conversations()
    assert TOKEN not in str(e.value) and TOKEN not in repr(c) and TOKEN not in caplog.text
    with pytest.raises(PancakeError) as e2:
        await pancake_client(lambda r: httpx.Response(403)).conversations()
    assert TOKEN not in str(e2.value)


async def test_token_bucket_caps_at_5_per_second() -> None:
    t = [0.0]
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)
        t[0] += s
    b = TokenBucket(5, clock=lambda: t[0], sleep=sleep)
    for _ in range(10):
        await b.acquire()
    assert t[0] == pytest.approx(1.0)  # 5 burst + 5 more takes one second


def test_load_token_env_then_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PANCAKE_PAGE_TOKEN", raising=False)
    with pytest.raises(PancakeError):
        load_token(tmp_path)
    (tmp_path / "pancake_page_token").write_text("from-file\n")
    assert load_token(tmp_path) == "from-file"
    monkeypatch.setenv("PANCAKE_PAGE_TOKEN", "from-env")
    assert load_token(tmp_path) == "from-env"


# --- end to end: bridge -> signed POST -> create_app() ingest ------------------------------------
async def test_bridge_end_to_end(tenant_factory, sandbox_factory, connector_factory, app_client,
                                 tmp_path) -> None:
    t = await tenant_factory()
    other = await tenant_factory(name="Other")
    sb = await sandbox_factory(t)
    conn = await connector_factory(sb, secret="bridge-secret")
    calls: list[httpx.Request] = []
    cursor = tmp_path / "cursor.json"
    kw = dict(ingest_url="http://test/ingest/v1/events", connector_id=conn.id,
              secret="bridge-secret", channel_kind="messenger", cursor_path=cursor, now=NOW)

    first = await run_once(pancake_client(fake_pancake(calls)), app_client, **kw)
    assert first == {"accepted": 4, "duplicate": 0, "rejected": 0}
    assert all(c.method == "GET" for c in calls)
    async with tenant_session(t.id) as s:
        roles = dict((await s.execute(select(m.Message.external_id, m.Message.sender_role))).all())
        conv = (await s.execute(select(m.Conversation))).scalar_one()
    assert roles == {"pancake:page123:m1": "customer", "pancake:page123:m2": "customer",
                     "pancake:page123:m3": "bot", "pancake:page123:m4": "staff"}
    assert conv.last_staff_at == datetime(2026, 10, 9, 3, 10, tzinfo=UTC)  # bot m3 did not count
    async with tenant_session(other.id) as s:
        assert (await s.execute(select(func.count()).select_from(m.Message))).scalar() == 0

    # cursor advanced to the conversation's updated_at: next poll sends nothing new
    assert load_cursor(cursor, "page123") == int(datetime(2026, 10, 9, 3, 10, tzinfo=UTC).timestamp())
    # replay from scratch (cursor lost) -> server answers duplicate, no second copy
    cursor.unlink()
    again = await run_once(pancake_client(fake_pancake(calls)), app_client, **kw)
    assert again == {"accepted": 0, "duplicate": 4, "rejected": 0}
    async with tenant_session(t.id) as s:
        assert (await s.execute(select(func.count()).select_from(m.Message))).scalar() == 4


async def test_bridge_bad_signature_does_not_advance_cursor(tenant_factory, sandbox_factory,
                                                            connector_factory, app_client,
                                                            tmp_path) -> None:
    sb = await sandbox_factory(await tenant_factory())
    conn = await connector_factory(sb, secret="right")
    cursor = tmp_path / "cursor.json"
    with pytest.raises(httpx.HTTPStatusError):
        await run_once(pancake_client(fake_pancake([])), app_client,
                       ingest_url="http://test/ingest/v1/events", connector_id=conn.id,
                       secret="wrong", channel_kind="messenger", cursor_path=cursor, now=NOW)
    assert not cursor.exists()
