"""Contract tests built from the Meta webhook/Send API docs (fetched 2026-10-12; see bridges/messenger/README.md).
No call to Meta: httpx is mocked."""
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from bridges.messenger.app import Settings, create_app
from bridges.messenger.mapper import map_messaging
from bridges.messenger.sender import Sender
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.ingest.format import Event
from cortex_leads.ingest.signing import sign

PAGE, OWN_APP, PSID = "page1", "111", "psid9"
T0 = 1_760_000_000_000  # ms
SECRET, APP_SECRET, PAGE_TOKEN = "conn-secret", "app-secret", "PAGE-TOKEN-xyz"


def settings(**kw) -> Settings:
    base = dict(app_secret=APP_SECRET, verify_token="vt", page_token=PAGE_TOKEN, page_id=PAGE, own_app_id=OWN_APP,
                ingest_url="http://test/ingest/v1/events", connector_id="conn_x", connector_secret=SECRET,
                policy={"ai_send": True})
    return Settings(**{**base, **kw})


def inbound(mid: str, text: str = "Giá bao nhiêu?", t: int = 0) -> dict:
    return {"sender": {"id": PSID}, "recipient": {"id": PAGE}, "timestamp": T0 + t,
            "message": {"mid": mid, "text": text}}


def echo(mid: str, app_id: str | None, t: int = 0) -> dict:
    msg = {"mid": mid, "text": "Dạ em báo giá ạ", "is_echo": True, **({"app_id": app_id} if app_id else {})}
    return {"sender": {"id": PAGE}, "recipient": {"id": PSID}, "timestamp": T0 + t, "message": msg}


def payload(*entries: list[dict]) -> bytes:
    return json.dumps({"object": "page", "entry": [{"id": PAGE, "time": T0, "messaging": e} for e in entries]}).encode()


def meta_sig(body: bytes, secret: str = APP_SECRET) -> dict[str, str]:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}


# --- mapper: sender.role (R13) -------------------------------------------------------------------
def test_sender_roles(caplog) -> None:
    kw = dict(page_id=PAGE, own_app_id=OWN_APP, human_apps=frozenset({"222"}), bot_apps=frozenset({"333"}))
    cust = map_messaging(inbound("m1"), **kw)
    assert cust["sender"] == {"role": "customer"} and cust["conversation"]["external_id"] == PSID
    assert map_messaging(echo("m2", OWN_APP), **kw)["sender"] == {"role": "bot"}      # Cortex's own send
    human = map_messaging(echo("m3", "222"), **kw)                                     # Pancake inbox (configured)
    assert human["sender"] == {"role": "staff"} and human["meta"] == {"echo_app": "222"}
    assert map_messaging(echo("m4", "333"), **kw)["sender"] == {"role": "bot"}         # known bot (configured)
    staff = map_messaging(echo("m5", None), **kw)                                      # typed in Page inbox
    assert staff["sender"] == {"role": "staff"} and staff["conversation"]["external_id"] == PSID
    with caplog.at_level("WARNING"):                                                   # unknown app: staff + warn once
        u1, u2 = map_messaging(echo("m6", "777"), **kw), map_messaging(echo("m7", "777"), **kw)
    assert u1["sender"] == {"role": "staff"} and u1["meta"] == {"echo_app": "unknown:777"} and u2["sender"] == u1["sender"]
    assert caplog.text.count("unknown app_id 777") == 1


def test_app_id_lists_from_env(monkeypatch, tmp_path) -> None:
    env = dict(MESSENGER_APP_SECRET="a", MESSENGER_VERIFY_TOKEN="v", MESSENGER_PAGE_TOKEN="t", MESSENGER_PAGE_ID="p",
               MESSENGER_OWN_APP_ID="1", CL_INGEST_URL="http://x", CL_CONNECTOR_ID="c", CL_CONNECTOR_SECRET="s",
               MESSENGER_HUMAN_APP_IDS="222, 223", MESSENGER_BOT_APP_IDS="333")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    st = Settings.from_env(tmp_path)
    assert st.human_apps == {"222", "223"} and st.bot_apps == {"333"}


def test_event_shape_and_validity() -> None:
    ev = map_messaging(inbound("m1"), page_id=PAGE)
    assert ev["external_id"] == f"messenger:{PAGE}:m1"
    assert Event.model_validate(ev).occurred_at == datetime.fromtimestamp(T0 / 1000, UTC)
    assert ev["channel"] == {"kind": "messenger", "account_ref": PAGE}


def test_non_message_events_ignored() -> None:
    for item in ({"sender": {"id": PSID}, "timestamp": T0, "delivery": {"mids": ["m"]}},
                 {"sender": {"id": PSID}, "timestamp": T0, "read": {"watermark": T0}},
                 {"sender": {"id": PSID}, "timestamp": T0, "postback": {"title": "x", "payload": "y"}},
                 inbound("m1", text="  ")):
        assert map_messaging(item, page_id=PAGE) is None
    att = inbound("m5", text="")
    att["message"]["attachments"] = [{"type": "image", "payload": {"url": "https://x/i.png"}}]
    assert Event.model_validate(map_messaging(att, page_id=PAGE)).attachments == [
        {"type": "image", "url": "https://x/i.png"}]


# --- webhook ---------------------------------------------------------------------------------------
def bridge(tmp_path: Path, handler=None, **kw):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler or (lambda r: httpx.Response(202, json={}))))
    app = create_app(settings(**kw), http=http, data_dir=tmp_path)
    return app, AsyncClient(transport=ASGITransport(app=app), base_url="http://bridge")


async def test_verify_challenge(tmp_path) -> None:
    _, c = bridge(tmp_path)
    ok = await c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "1234"})
    assert (ok.status_code, ok.text) == (200, "1234")
    bad = await c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "1"})
    assert bad.status_code == 403


async def test_webhook_signature(tmp_path) -> None:
    app, c = bridge(tmp_path)
    body = payload([inbound("m1")])
    assert (await c.post("/webhook", content=body)).status_code == 401
    assert (await c.post("/webhook", content=body, headers=meta_sig(body, "wrong"))).status_code == 401
    assert (await c.post("/webhook", content=body + b" ", headers=meta_sig(body))).status_code == 401  # tampered
    assert app.state.forwarder.queue == []
    assert (await c.post("/webhook", content=body, headers=meta_sig(body))).status_code == 200
    assert len(app.state.forwarder.queue) == 1


async def test_batch_many_entries_queued_in_order(tmp_path) -> None:
    app, c = bridge(tmp_path)
    body = payload([inbound("m1", t=0), echo("m2", None, t=1000)], [inbound("m3", t=2000)])
    await c.post("/webhook", content=body, headers=meta_sig(body))
    assert [e["external_id"][-2:] for e in app.state.forwarder.queue] == ["m1", "m2", "m3"]


async def test_forwarder_signs_and_retries_with_backoff(tmp_path) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(503 if len(seen) < 3 else 202, json={})
    sleeps: list[float] = []

    async def sleep(s: float) -> None:
        sleeps.append(s)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(settings(), http=http, data_dir=tmp_path, sleep=sleep)
    app.state.forwarder.add([map_messaging(inbound("m1"), page_id=PAGE)])
    await app.state.forwarder.flush()
    assert len(seen) == 3 and sleeps == [0.5, 1.0] and app.state.forwarder.queue == []
    r = seen[-1]
    assert r.headers["X-Signature"] == sign(SECRET.encode(), int(r.headers["X-Timestamp"]), r.content)
    assert r.headers["X-Connector-Id"] == "conn_x"


async def test_forwarder_keeps_events_when_ingest_down(tmp_path) -> None:
    async def sleep(_s: float) -> None: ...
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    app = create_app(settings(), http=http, data_dir=tmp_path, sleep=sleep)
    app.state.forwarder.add([map_messaging(inbound("m1"), page_id=PAGE)])
    await app.state.forwarder.flush(attempts=2)
    assert len(app.state.forwarder.queue) == 1


async def test_end_to_end_into_core_ingest(tenant_factory, sandbox_factory, connector_factory, app_client,
                                           tmp_path) -> None:
    t = await tenant_factory()
    sb = await sandbox_factory(t)
    conn = await connector_factory(sb, secret=SECRET)
    app = create_app(settings(connector_id=conn.id), http=app_client, data_dir=tmp_path)
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://bridge")
    body = payload([inbound("m1", t=0), echo("m2", OWN_APP, t=1000), echo("m3", None, t=2000)])
    await c.post("/webhook", content=body, headers=meta_sig(body))
    await app.state.forwarder.flush()
    await c.post("/webhook", content=body, headers=meta_sig(body))  # Meta retry: same mids
    await app.state.forwarder.flush()
    async with tenant_session(t.id) as s:
        roles = dict((await s.execute(select(m.Message.external_id, m.Message.sender_role))).all())
        n = (await s.execute(select(func.count()).select_from(m.Message))).scalar()
    assert roles == {f"messenger:{PAGE}:m1": "customer", f"messenger:{PAGE}:m2": "bot",
                     f"messenger:{PAGE}:m3": "staff"} and n == 3  # duplicates deduped by the core


# --- chiều ra ----------------------------------------------------------------------------------------
def action(aid: str = "a1", actor: str = "ai:drafter@1", basis: str | None = "free", open_: bool = True,
           disclosure: str | None = "Trợ lý AI của Acme", **kw) -> dict:
    return {"format": "cortex.action/1", "action_id": aid, "type": "send_message",
            "channel": {"kind": "messenger", "account_ref": PAGE}, "conversation": {"external_id": PSID},
            "actor": actor, "text": "Dạ em chào", "disclosure": disclosure,
            "window": {"open": open_, "basis": basis if open_ else None, "expires_at": None},
            "source": {"skill": "s@1", "run_id": "r"}, **kw}


class Graph:
    def __init__(self, status: int = 200) -> None:
        self.calls: list[httpx.Request] = []
        self.status = status

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if isinstance(self.status, Exception):
            raise self.status
        self.calls.append(req)
        return httpx.Response(self.status, json={"recipient_id": PSID, "message_id": "m.out1"})


def sender(tmp_path, graph: Graph, **policy) -> Sender:
    return Sender(page_token=PAGE_TOKEN, version="v25.0", policy={"ai_send": True, **policy},
                  store=tmp_path / "actions.json", http=httpx.AsyncClient(transport=httpx.MockTransport(graph)),
                  clock=lambda: 1_760_000_000)  # 2025-10-09 15:53 Asia/Ho_Chi_Minh


async def test_free_window_sends_response_with_disclosure(tmp_path) -> None:
    g = Graph()
    res = await sender(tmp_path, g).handle(action())
    assert res == {"status": "sent", "external_message_id": "m.out1"}
    req = g.calls[0]
    assert req.url.path == "/v25.0/me/messages" and PAGE_TOKEN not in str(req.url)
    assert req.headers["Authorization"] == f"Bearer {PAGE_TOKEN}"
    assert json.loads(req.content) == {"recipient": {"id": PSID}, "messaging_type": "RESPONSE",
                                       "message": {"text": "Dạ em chào\n— Trợ lý AI của Acme"}}


async def test_human_agent_staff_only(tmp_path) -> None:
    g = Graph()
    s = sender(tmp_path, g)
    assert await s.handle(action("a1", actor="ai:x@1", basis="human_agent")) == {
        "status": "refused", "reason": "PLATFORM_POLICY"}
    assert g.calls == []
    ok = await s.handle(action("a2", actor="staff:lan", basis="human_agent", disclosure=None))
    assert ok["status"] == "sent"
    body = json.loads(g.calls[0].content)
    assert body["messaging_type"] == "MESSAGE_TAG" and body["tag"] == "HUMAN_AGENT"
    assert body["message"]["text"] == "Dạ em chào"


async def test_refusals(tmp_path) -> None:
    g = Graph()
    s = sender(tmp_path, g)
    assert (await s.handle(action("a1", open_=False)))["reason"] == "WINDOW_CLOSED"
    assert (await s.handle(action("a2", actor="staff:lan", open_=False)))["reason"] == "WINDOW_CLOSED"
    assert (await s.handle(action("a3", type="add_tag")))["reason"] == "NOT_SUPPORTED"
    off = sender(tmp_path / "off", g, ai_send=False)
    assert (await off.handle(action("a4")))["reason"] == "AI_SEND_DISABLED"
    assert (await off.handle(action("a5", actor="staff:lan")))["status"] == "sent"  # staff unaffected
    assert len(g.calls) == 1


async def test_quiet_hours_ai_only(tmp_path) -> None:
    g = Graph()
    s = sender(tmp_path, g, quiet_hours=[15, 17])  # clock says 15:53 local
    assert (await s.handle(action("a1")))["reason"] == "QUIET_HOURS"
    assert (await s.handle(action("a2", actor="staff:lan")))["status"] == "sent"
    wrap = sender(tmp_path / "w", g, quiet_hours=[22, 16])  # wraps midnight
    assert (await wrap.handle(action("a3")))["reason"] == "QUIET_HOURS"


async def test_rate_limit_is_transient(tmp_path) -> None:
    g = Graph()
    s = sender(tmp_path, g, max_per_minute=1)
    assert (await s.handle(action("a1")))["status"] == "sent"
    assert (await s.handle(action("a2"))) == {"status": "refused", "reason": "RATE_LIMIT"}
    s._sent_at.clear()
    assert (await s.handle(action("a2")))["status"] == "sent"  # not remembered as refused


async def test_idempotent_by_action_id_across_restart(tmp_path) -> None:
    g = Graph()
    first = await sender(tmp_path, g).handle(action("dup"))
    again = await sender(tmp_path, g).handle(action("dup"))  # new instance, same store file
    assert first == again and len(g.calls) == 1
    refused = sender(tmp_path / "r", g, ai_send=False)
    assert await refused.handle(action("x")) == await refused.handle(action("x"))


async def test_send_api_errors(tmp_path) -> None:
    for status, retryable in ((500, True), (503, True), (429, True), (400, False), (403, False)):
        res = await sender(tmp_path / str(status), Graph(status)).handle(action())
        assert res == {"status": "error", "retryable": retryable}, status
    net = Graph()
    net.status = httpx.ConnectError("down")
    s = sender(tmp_path / "net", net)
    assert await s.handle(action("n1")) == {"status": "error", "retryable": True}
    assert "n1" not in s._done  # errors are not remembered: the core may retry


async def test_error_does_not_leak_token(tmp_path, caplog) -> None:
    caplog.set_level("DEBUG")
    await sender(tmp_path, Graph(400)).handle(action())
    assert PAGE_TOKEN not in caplog.text and PAGE_TOKEN not in repr(settings())


async def test_actions_endpoint_signature(tmp_path) -> None:
    g = Graph()
    http = httpx.AsyncClient(transport=httpx.MockTransport(g))
    app = create_app(settings(), http=http, data_dir=tmp_path)
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://bridge")
    body = json.dumps(action("e2e")).encode()
    ts = int(time.time())

    def hdr(sig: str, t: int = ts) -> dict:
        return {"X-Cortex-Timestamp": str(t), "X-Cortex-Signature": sig}
    assert (await c.post("/actions", content=body, headers=hdr("sha256=00"))).status_code == 401
    assert (await c.post("/actions", content=body, headers=hdr(sign(b"wrong", ts, body)))).status_code == 401
    old = ts - 3600  # replay outside skew
    assert (await c.post("/actions", content=body, headers=hdr(sign(SECRET.encode(), old, body), old))).status_code == 401
    assert g.calls == []
    r = await c.post("/actions", content=body, headers=hdr(sign(SECRET.encode(), ts, body)))
    assert r.status_code == 200 and r.json()["status"] == "sent" and len(g.calls) == 1


def test_settings_missing_secret_fails(monkeypatch, tmp_path) -> None:
    for k in ("MESSENGER_APP_SECRET", "MESSENGER_VERIFY_TOKEN", "MESSENGER_PAGE_TOKEN", "MESSENGER_PAGE_ID",
              "MESSENGER_OWN_APP_ID", "CL_INGEST_URL", "CL_CONNECTOR_ID", "CL_CONNECTOR_SECRET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="app_secret"):
        Settings.from_env(tmp_path)
    (tmp_path / "messenger_page_token").write_text("from-file\n")
    with pytest.raises(RuntimeError) as e:
        Settings.from_env(tmp_path)
    assert "page_token" not in str(e.value)  # read from the file, so not reported missing
