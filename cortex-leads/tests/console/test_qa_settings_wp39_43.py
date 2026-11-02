"""QA (Agent B) for WP39-43, written without looking at Agent A's own tests: tenant isolation (three businesses), who may call what,
CSRF, refused input, a secret that shows once, the SSRF checks on a webhook, and the forgot-password surface (same answer, same speed,
one-shot link, nothing secret kept)."""
import asyncio
import json
import logging
import re
import statistics
import time

import pytest
from sqlalchemy import text
from support import PASSWORD, account_for_key, h, sign_in
from wp5_support import World, rows

from cortex_leads.config import get_settings
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.notify.mailer import MemoryMailer, set_mailer

S = "/api/v1/settings"
A = "/api/v1/auth"
BASE = "https://cortex.example.vn"
GOOD = {"name": "Trung tâm Minh Khai", "timezone": "Asia/Ho_Chi_Minh", "hours": {"start": "07:30", "end": "20:00"}, "ai_name": "Mai"}


# --- helpers -----------------------------------------------------------------------------------------
async def scan(owner_engine, *needles: str) -> dict[str, int]:
    """Rows of every base table whose text form contains a needle (owner connection: row security does not hide anything)."""
    out: dict[str, int] = {}
    async with owner_engine.connect() as c:
        tables = [r[0] for r in await c.execute(text("select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE' and table_name<>'alembic_version'"))]
        for t in tables:
            for n in needles:
                k = (await c.execute(text(f'select count(*) from "{t}" where "{t}"::text ilike :n'), {"n": f"%{n}%"})).scalar_one()
                if k:
                    out[f"{t}:{n}"] = k
    return out


@pytest.fixture
async def three(world: World, tenant_factory, sandbox_factory, connector_factory, api_key_factory, app_client):
    """`world` is business A. B and C each have a sandbox and a channel. Returns A's owner client and the ids of B and C."""
    b = await tenant_factory("Beta")
    sb_b = await sandbox_factory(b)
    cn_b = await connector_factory(sb_b)
    c = await tenant_factory("Gamma")
    sb_c = await sandbox_factory(c)
    cn_c = await connector_factory(sb_c)
    async with tenant_session(b.id) as s:
        s.add(m.NotifyTarget(tenant_id=b.id, kind="telegram", address="-1009999999", label="beta-chat"))
    _, key = await api_key_factory(world.t, "owner", None)
    csrf = await sign_in(app_client, key)
    return {"c": app_client, "h": h(csrf), "b": (b, sb_b, cn_b), "cc": (c, sb_c, cn_c)}


# --- 1. isolation (A1) / actor from the session (A3) ----------------------------------------------------
async def test_a_business_sees_and_changes_only_its_own_channels_targets_and_profile(three, world, owner_engine):
    c, hd = three["c"], three["h"]
    b, sb_b, cn_b = three["b"]
    _cc, _sb_c, cn_c = three["cc"]
    ch = (await c.get(f"{S}/channels")).json()
    ids = {x["id"] for x in ch["items"]}
    assert ids == {world.cn.id} and cn_b.id not in ids and cn_c.id not in ids  # connector has no RLS: the filter is by hand
    assert {x["id"] for x in ch["sandboxes"]} == {str(world.sb.id)}
    # removing B's channel, by its id, as A
    r = await c.delete(f"{S}/channels/{cn_b.id}", headers=hd)
    assert r.status_code == 404
    async with system_session() as s:
        assert (await s.get(m.Connector, cn_b.id)).status != "disabled"
    # adding a channel on B's sandbox, as A
    r = await c.post(f"{S}/channels", json={"kind": "messenger", "sandbox_id": str(sb_b.id)}, headers=hd)
    assert r.status_code == 404
    # a body that names another business is not read (A3)
    r = await c.post(f"{S}/channels", json={"kind": "messenger", "sandbox_id": str(world.sb.id), "tenant_id": str(b.id)}, headers=hd)
    assert r.status_code == 201
    async with system_session() as s:
        assert (await s.get(m.Connector, r.json()["id"])).tenant_id == world.t.id
    # push targets
    assert (await c.get(f"{S}/notify-targets")).json()["items"] == []  # B's "beta-chat" is not A's
    async with tenant_session(b.id) as s:
        tid_b = (await s.execute(text("select id from notify_target"))).scalar_one()
    assert (await c.delete(f"{S}/notify-targets/{tid_b}", headers=hd)).status_code == 404
    assert (await c.post(f"{S}/notify-targets/{tid_b}/test", headers=hd)).status_code == 404
    r = await c.post(f"{S}/notify-targets", json={"kind": "telegram", "address": "-100123456", "sandbox_id": str(sb_b.id)}, headers=hd)
    assert r.status_code == 404  # bind to someone else's sandbox
    # the profile: A's change reaches neither B nor C
    assert (await c.put(f"{S}/business", json=GOOD, headers=hd)).status_code == 200
    async with owner_engine.connect() as conn:
        names = dict((await conn.execute(text("select name, ai_name from tenant"))).all())
        hours = (await conn.execute(text("select tenant_id, business_hours from sandbox"))).all()
    assert names["Beta"] is None and names["Gamma"] is None
    assert sum(1 for t, bh in hours if bh.get("start") == "07:30") == 1


async def test_another_businesss_conversation_cannot_be_exported_or_erased(three):
    c, hd = three["c"], three["h"]
    # a conversation of B, made through the owner connection of the fixture world of B is not available here; use a random id and B's
    # real one found through the owner engine
    _b, _sb_b, _cn_b = three["b"]
    assert (await c.get("/api/v1/customers/00000000-0000-0000-0000-000000000000/export")).status_code == 404
    assert (await c.post("/api/v1/customers/00000000-0000-0000-0000-000000000000/erase", json={"confirm": True}, headers=hd)).status_code == 404


async def test_another_businesss_real_conversation_is_not_reachable(three, conversation_factory, owner_engine):
    c, hd = three["c"], three["h"]
    _b, _sb_b, cn_b = three["b"]
    conv_b = await conversation_factory(cn_b, external_id="b-conv", display_name="Khách của B")
    assert (await c.get(f"/api/v1/customers/{conv_b.id}/export")).status_code == 404
    assert (await c.post(f"/api/v1/customers/{conv_b.id}/erase", json={"confirm": True}, headers=hd)).status_code == 404
    async with owner_engine.connect() as conn:
        assert (await conn.execute(text("select opted_out from contact where id=(select contact_id from conversation where id=:i)"), {"i": conv_b.id})).scalar_one() is False


# --- 2. who may call what, and CSRF -----------------------------------------------------------------------
OWNER_CALLS = [
    ("GET", f"{S}/business", None), ("PUT", f"{S}/business", GOOD), ("GET", f"{S}/notify-targets", None),
    ("POST", f"{S}/notify-targets", {"kind": "telegram", "address": "-100123456"}),
    ("DELETE", f"{S}/notify-targets/00000000-0000-0000-0000-000000000001", None),
    ("POST", f"{S}/notify-targets/00000000-0000-0000-0000-000000000001/test", None),
    ("GET", f"{S}/channels", None), ("POST", f"{S}/channels", {"kind": "messenger", "sandbox_id": "00000000-0000-0000-0000-000000000001"}),
    ("DELETE", f"{S}/channels/x", None), ("GET", f"{S}/ai", None),
    ("GET", "/api/v1/customers/00000000-0000-0000-0000-000000000001/export", None),
    ("POST", "/api/v1/customers/00000000-0000-0000-0000-000000000001/erase", {"confirm": True}),
]


@pytest.mark.parametrize("method,url,body", OWNER_CALLS)
async def test_staff_cannot_call_the_owners_settings(app_client, world, api_key_factory, method, url, body):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    hd = h(await sign_in(app_client, key))
    r = await app_client.request(method, url, json=body, headers=hd)
    assert r.status_code == 403, (url, r.status_code, r.text)


@pytest.mark.parametrize("method,url,body", [c for c in OWNER_CALLS if c[0] != "GET"])
async def test_a_write_without_the_csrf_token_is_refused(three, method, url, body):
    r = await three["c"].request(method, url, json=body)  # cookie yes, header no
    assert r.status_code in (403, 400), (url, r.status_code, r.text)
    assert r.status_code != 404


@pytest.mark.parametrize("method,url,body", OWNER_CALLS)
async def test_a_call_without_a_session_is_refused(app_client, method, url, body):
    r = await app_client.request(method, url, json=body)
    assert r.status_code == 401, (url, r.status_code)


# --- 3. refused input -----------------------------------------------------------------------------------
@pytest.mark.parametrize("patch", [
    {"hours": {"start": "24:00", "end": "23:59"}}, {"hours": {"start": "07:60", "end": "20:00"}}, {"hours": {"start": "07:00", "end": "07:00"}},
    {"hours": {"start": "", "end": ""}}, {"hours": {"start": "07:00:00", "end": "20:00"}}, {"timezone": "UTC+7"}, {"timezone": ""},
    {"timezone": "Asia/Ho_Chi_Minh\n"}, {"ai_name": "Mai\r\nLinh"}, {"ai_name": "https://x.vn"}, {"ai_name": "Mai.vn/abc"}, {"ai_name": "a" * 61},
    {"name": "x"}, {"name": "n" * 81},
])
async def test_bad_profiles_are_refused_with_nothing_saved(three, world, patch):
    r = await three["c"].put(f"{S}/business", json={**GOOD, **patch}, headers=three["h"])
    assert r.status_code in (422, 400), (patch, r.status_code, r.text)
    async with tenant_session(world.t.id) as s:
        assert (await s.get(m.Tenant, world.t.id)).name == "Acme"


async def test_the_ai_name_cannot_pose_as_a_person_other_than_an_ai(three):
    """The disclosure always starts with "Trợ lý AI" whatever name is typed; a name that tries to hide that is judged here."""
    for n in ("Nhân viên Lan", "Giám đốc", "Admin", "Mai (người thật)"):
        r = await three["c"].put(f"{S}/business", json={**GOOD, "ai_name": n}, headers=three["h"])
        if r.status_code == 200:
            assert r.json()["disclosure"].startswith("Trợ lý AI"), r.json()


@pytest.fixture
def resolves(monkeypatch):
    table: dict[str, list[str]] = {}

    async def resolve(host):
        return table.get(host, ["93.184.216.34"])

    monkeypatch.setattr("cortex_leads.connectors.egress.resolve_host", resolve)
    return table


@pytest.mark.parametrize("url", [
    "http://webhook.mezon.ai/x", "https://127.0.0.1/x", "http://127.0.0.1/x", "https://localhost/x", "https://169.254.169.254/latest/meta-data",
    "https://[::1]/x", "https://evil.example/x", "https://webhook.mezon.ai@evil.example/x", "https://user:pw@webhook.mezon.ai/x",
    "https://webhook.mezon.ai.evil.example/x", "https://webhook.mezon.ai:8443/x", "https://webhook.mezon.ai:22/x", "ftp://webhook.mezon.ai/x",
    "file:///etc/passwd", "//webhook.mezon.ai/x", "https://webhook.mezon.ai\\@evil.example/", "https://0x7f000001/", "https://2130706433/",
    "https://webhook.mezon.ai/" + "a" * 600, "javascript:alert(1)", "",
])
async def test_a_webhook_that_points_anywhere_but_the_allowed_host_is_refused(three, resolves, url):
    r = await three["c"].post(f"{S}/notify-targets", json={"kind": "mezon", "address": url or "   "}, headers=three["h"])
    assert r.status_code in (422, 400), (url, r.status_code, r.text)
    async with tenant_session(three["b"][0].id):
        pass
    assert (await three["c"].get(f"{S}/notify-targets")).json()["items"] == []


async def test_an_allowed_name_that_resolves_inside_is_refused_and_a_public_one_is_masked(three, resolves):
    resolves["webhook.mezon.ai"] = ["10.0.0.5"]
    r = await three["c"].post(f"{S}/notify-targets", json={"kind": "mezon", "address": "https://webhook.mezon.ai/hooks/SECRET-TOKEN"}, headers=three["h"])
    assert r.status_code == 422
    resolves["webhook.mezon.ai"] = ["93.184.216.34", "169.254.169.254"]  # one public, one not
    r = await three["c"].post(f"{S}/notify-targets", json={"kind": "mezon", "address": "https://webhook.mezon.ai/hooks/SECRET-TOKEN"}, headers=three["h"])
    assert r.status_code == 422
    resolves["webhook.mezon.ai"] = ["93.184.216.34"]
    r = await three["c"].post(f"{S}/notify-targets", json={"kind": "mezon", "address": "https://webhook.mezon.ai/hooks/SECRET-TOKEN"}, headers=three["h"])
    assert r.status_code == 201 and "SECRET-TOKEN" not in r.text
    assert "SECRET-TOKEN" not in (await three["c"].get(f"{S}/notify-targets")).text


@pytest.mark.parametrize("addr", ["abc", "-100 123", "-100123456/../x", "1e9", "-", "https://x.vn", "-1001234567890123456789"])
async def test_a_bad_telegram_chat_id_is_refused(three, addr):
    r = await three["c"].post(f"{S}/notify-targets", json={"kind": "telegram", "address": addr}, headers=three["h"])
    assert r.status_code in (422, 400), (addr, r.status_code)


async def test_an_unknown_channel_kind_or_a_non_care_sandbox_is_refused(three, world):
    r = await three["c"].post(f"{S}/channels", json={"kind": "../etc", "sandbox_id": str(world.sb.id)}, headers=three["h"])
    assert r.status_code == 422
    r = await three["c"].post(f"{S}/channels", json={"kind": "messenger", "sandbox_id": "not-a-uuid"}, headers=three["h"])
    assert r.status_code == 422


# --- 4. a channel secret is shown once ---------------------------------------------------------------------
async def test_the_channel_secret_is_in_the_answer_that_made_it_and_nowhere_else(three, world, owner_engine, caplog):
    caplog.set_level(logging.DEBUG)
    c, hd = three["c"], three["h"]
    r = await c.post(f"{S}/channels", json={"kind": "messenger", "sandbox_id": str(world.sb.id)}, headers=hd)
    assert r.status_code == 201
    secret = r.json()["secret"]
    assert len(secret) >= 32
    assert secret not in (await c.get(f"{S}/channels")).text
    assert secret not in (await c.get("/api/v1/audit")).text if (await c.get("/api/v1/audit")).status_code == 200 else True
    hits = await scan(owner_engine, secret)
    assert hits == {}, hits  # not in the DB in clear (only the Fernet copy)
    assert secret not in caplog.text
    # it works once as the bridge's key: the stored copy decrypts to it
    from cryptography.fernet import Fernet
    async with system_session() as s:
        row = await s.get(m.Connector, r.json()["id"])
        assert Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(row.secret_enc).decode() == secret
    # switching it off refuses the bridge from then on (ingest) and is logged without the secret
    assert (await c.delete(f"{S}/channels/{r.json()['id']}", headers=hd)).status_code == 200
    assert (await c.delete(f"{S}/channels/{r.json()['id']}", headers=hd)).status_code == 404
    ev = [e for e in await rows(world, m.AuditEvent) if e.action.startswith("channel.")]
    assert len(ev) == 2 and secret not in json.dumps([e.metadata_ for e in ev]) + "".join(e.summary for e in ev)


async def test_a_webhook_address_never_reaches_the_audit_trail_or_the_log(three, world, resolves, caplog):
    caplog.set_level(logging.DEBUG)
    addr = "https://webhook.mezon.ai/hooks/TOP-SECRET-TOKEN-123"
    r = await three["c"].post(f"{S}/notify-targets", json={"kind": "mezon", "address": addr, "label": "kênh giáo viên"}, headers=three["h"])
    assert r.status_code == 201
    tid = r.json()["id"]
    await three["c"].delete(f"{S}/notify-targets/{tid}", headers=three["h"])
    blob = json.dumps([[e.summary, e.metadata_, e.object_label] for e in await rows(world, m.AuditEvent)], default=str)
    assert "TOP-SECRET-TOKEN-123" not in blob and "TOP-SECRET-TOKEN-123" not in caplog.text


async def test_a_removed_target_receives_nothing_and_is_not_listed(three, resolves):
    r = await three["c"].post(f"{S}/notify-targets", json={"kind": "telegram", "address": "-100123456"}, headers=three["h"])
    tid = r.json()["id"]
    assert (await three["c"].delete(f"{S}/notify-targets/{tid}", headers=three["h"])).status_code == 200
    assert (await three["c"].get(f"{S}/notify-targets")).json()["items"] == []
    assert (await three["c"].post(f"{S}/notify-targets/{tid}/test", headers=three["h"])).status_code == 404


# --- 5. forgot password ----------------------------------------------------------------------------------
@pytest.fixture
def mail(monkeypatch):
    box = MemoryMailer()
    set_mailer(box)
    monkeypatch.setattr(get_settings(), "PUBLIC_BASE_URL", BASE)
    monkeypatch.setattr(get_settings(), "RESET_MAX_PER_IP_HOUR", 1000)
    monkeypatch.setattr(get_settings(), "RESET_MAX_PER_EMAIL_HOUR", 1000)
    yield box
    set_mailer(None)


@pytest.fixture
async def person(world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    return await account_for_key(key)


def token_in(box: MemoryMailer, n: int = -1) -> str:
    return re.search(r"#token=([\w\-]+)", box.sent[n]["body"]).group(1)


async def asgi_post(path: str, body: dict, headers: dict[str, str] | None = None) -> tuple[int, bytes, float, float]:
    """One POST through the app, timed to the last byte of the answer: (status, body, seconds to the answer, seconds to the end of the app
    call). Starlette sends the answer first and runs background work after it; the first number is what a visitor can feel."""
    from cortex_leads.app import create_app

    app = _app_cache.setdefault("app", create_app())
    raw = json.dumps(body).encode()
    hs = [(b"content-type", b"application/json"), (b"host", b"test"), *[(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "path": path, "raw_path": path.encode(), "query_string": b"",
             "headers": hs, "client": ("203.0.113.9", 1234), "server": ("test", 80), "scheme": "http", "root_path": ""}
    sent = False
    t0 = time.perf_counter()
    out: dict = {"status": 0, "body": b"", "answered": 0.0}

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await asyncio.sleep(3600)

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")
            if not msg.get("more_body"):
                out["answered"] = time.perf_counter() - t0

    await app(scope, receive, send)
    return out["status"], out["body"], out["answered"], time.perf_counter() - t0


_app_cache: dict = {}


async def test_forgot_gives_the_same_answer_for_an_account_a_stranger_a_disabled_account_and_a_limited_address(mail, person, world, monkeypatch):
    async with tenant_session(world.t.id) as s:
        from cortex_leads.auth.users import create_user
        u2, _ = await create_user(s, world.t.id, email="off@x.vn", name="Off", role="staff", password=PASSWORD, created_by="t", staff_ref="off")
        u2.status = "disabled"
    answers = []
    for email in (person, "nobody@nowhere.vn", "off@x.vn", person.upper(), f" {person} "):
        st, body, _, _ = await asgi_post(f"{A}/forgot", {"email": email})
        answers.append((st, body))
    assert len(set(answers)) == 1, answers
    assert answers[0][0] == 200
    await asyncio.sleep(0.5)
    assert len(mail.sent) == 3 and {x["to"] for x in mail.sent} == {person}  # real account (3 spellings); none for the stranger or the disabled one
    monkeypatch.setattr(get_settings(), "RESET_MAX_PER_EMAIL_HOUR", 3)
    st, body, _, _ = await asgi_post(f"{A}/forgot", {"email": person})  # the 4th for this address in the hour (3 were spent above)
    assert (st, body) == answers[0] and len(mail.sent) == 3


async def test_forgot_does_not_answer_faster_or_slower_when_the_address_has_an_account(mail, person):
    for _ in range(3):  # warm up
        await asgi_post(f"{A}/forgot", {"email": person})
        await asgi_post(f"{A}/forgot", {"email": "ghost@nowhere.vn"})
    have, none = [], []
    for i in range(40):
        have.append((await asgi_post(f"{A}/forgot", {"email": person}))[2])
        none.append((await asgi_post(f"{A}/forgot", {"email": f"ghost{i}@nowhere.vn"}))[2])
    mh, mn = statistics.median(have), statistics.median(none)
    print(f"\nforgot, median to the answer: existing {mh*1000:.2f} ms  unknown {mn*1000:.2f} ms  (p90 {sorted(have)[35]*1000:.2f} / {sorted(none)[35]*1000:.2f})")
    assert abs(mh - mn) < max(0.005, 0.25 * max(mh, mn)), (mh, mn)


async def test_the_link_is_built_from_the_configured_address_never_from_the_host_header(mail, person):
    st, _, _, _ = await asgi_post(f"{A}/forgot", {"email": person}, {"Host": "evil.example", "X-Forwarded-Host": "evil.example", "Origin": "https://evil.example"})
    assert st == 200
    await asyncio.sleep(0.3)
    body = mail.sent[-1]["body"]
    assert f"{BASE}/app/reset#token=" in body and "evil.example" not in body
    assert "mật khẩu hiện tại" in body and PASSWORD not in body


async def test_reset_answers_every_bad_token_alike_and_a_good_one_works_exactly_once(mail, person, world, owner_engine):
    await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.3)
    good = token_in(mail)
    bad = []
    for tok in ("x" * 43, "A" * 20, good[:-1] + ("a" if good[-1] != "a" else "b"), good.upper(), good + "x", " " + good):
        st, body, _, _ = await asgi_post(f"{A}/reset", {"token": tok, "password": "Mat-khau-moi-7391"})
        bad.append((st, body))
    assert len(set(bad)) == 1 and bad[0][0] == 400, bad
    # token left in the DB as a hash only
    hits = await scan(owner_engine, good)
    assert hits == {}, hits
    async with owner_engine.connect() as conn:
        n = (await conn.execute(text("select count(*) from password_reset where token_hash=:t"), {"t": good})).scalar_one()
    assert n == 0
    # too short a token is a validation error (a different body): it says nothing about any real token
    st, body, _, _ = await asgi_post(f"{A}/reset", {"token": "short", "password": "x"})
    print("\nshort token ->", st)
    st, body, _, _ = await asgi_post(f"{A}/reset", {"token": good, "password": "Mat-khau-moi-7391"})
    assert st == 200
    again = await asgi_post(f"{A}/reset", {"token": good, "password": "Mat-khau-khac-5555"})
    assert (again[0], again[1]) == bad[0]
    # expired
    await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.3)
    old = token_in(mail)
    async with owner_engine.begin() as conn:
        await conn.execute(text("update password_reset set expires_at = now() - interval '1 minute' where used_at is null"))
    again = await asgi_post(f"{A}/reset", {"token": old, "password": "Mat-khau-moi-7391"})
    assert (again[0], again[1]) == bad[0]


async def test_a_weak_password_does_not_spend_the_link_and_the_rules_apply(mail, person, client_login=None):
    await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.3)
    tok = token_in(mail)
    for weak in ("short1", "12345678901234", "aaaaaaaaaaaaaaaa", person):
        st, body, _, _ = await asgi_post(f"{A}/reset", {"token": tok, "password": weak})
        assert st in (422, 400), (weak, st, body)
        assert b"BAD_RESET_TOKEN" not in body, weak  # the link is still alive
    st, *_ = await asgi_post(f"{A}/reset", {"token": tok, "password": "Mat-khau-moi-7391"})
    assert st == 200


async def test_using_the_link_ends_every_session_and_the_old_password_stops_working(mail, person, app_client):
    r = await app_client.post("/api/v1/session/login", json={"email": person, "password": PASSWORD})
    assert r.status_code == 200
    assert (await app_client.get("/api/v1/session")).status_code == 200
    await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.3)
    st, *_ = await asgi_post(f"{A}/reset", {"token": token_in(mail), "password": "Mat-khau-moi-7391"})
    assert st == 200
    assert (await app_client.get("/api/v1/session")).status_code == 401
    assert (await app_client.post("/api/v1/session/login", json={"email": person, "password": PASSWORD})).status_code in (401, 400, 403)
    assert (await app_client.post("/api/v1/session/login", json={"email": person, "password": "Mat-khau-moi-7391"})).status_code == 200


async def test_a_link_issued_before_the_account_was_disabled_no_longer_works(mail, person, world, owner_engine):
    await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.3)
    tok = token_in(mail)
    async with owner_engine.begin() as conn:
        await conn.execute(text("update app_user set status='disabled' where email=:e"), {"e": person})
    st, body, *_ = await asgi_post(f"{A}/reset", {"token": tok, "password": "Mat-khau-moi-7391"})
    assert st == 400 and b"BAD_RESET_TOKEN" in body
    async with owner_engine.begin() as conn:
        assert (await conn.execute(text("select status from app_user where email=:e"), {"e": person})).scalar_one() == "disabled"


async def test_two_uses_of_one_link_at_once_succeed_only_once(mail, person):
    await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.3)
    tok = token_in(mail)
    await asgi_post(f"{A}/reset", {"token": "x" * 43, "password": "Mat-khau-moi-7391"})  # makes the throttle row first (see the next test)
    res = await asyncio.gather(*[asgi_post(f"{A}/reset", {"token": tok, "password": f"Mat-khau-moi-73{i}1"}) for i in range(6)])
    codes = sorted(r[0] for r in res)
    assert codes.count(200) == 1 and codes.count(400) == 5, codes


async def test_a_new_request_voids_the_older_link(mail, person):
    await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.3)
    first = token_in(mail)
    await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.3)
    assert (await asgi_post(f"{A}/reset", {"token": first, "password": "Mat-khau-moi-7391"}))[0] == 400
    assert (await asgi_post(f"{A}/reset", {"token": token_in(mail), "password": "Mat-khau-moi-7391"}))[0] == 200


async def test_the_limits_hold_and_one_address_cannot_be_flooded(mail, person, monkeypatch):
    monkeypatch.setattr(get_settings(), "RESET_MAX_PER_EMAIL_HOUR", 3)
    monkeypatch.setattr(get_settings(), "RESET_MAX_PER_IP_HOUR", 10)
    codes = [(await asgi_post(f"{A}/forgot", {"email": f"user{i}@nowhere.vn"}))[0] for i in range(14)]
    assert codes[:10] == [200] * 10 and 429 in codes[10:], codes
    # (same client address for all calls here, as in a test; the one address now locked is the visitor's, not the account's)


async def test_griefing_an_account_with_forgot_requests_blocks_its_owners_own_request(mail, person, monkeypatch):
    """Documented, not a pass/fail of the code's intent: the per-address limit is spent by anyone who types the address, so a
    stranger can use up the owner's 3 mails an hour (R-QA1)."""
    monkeypatch.setattr(get_settings(), "RESET_MAX_PER_EMAIL_HOUR", 3)
    monkeypatch.setattr(get_settings(), "RESET_MAX_PER_IP_HOUR", 1000)
    for _ in range(4):
        await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.5)
    sent_to_owner = len([x for x in mail.sent if x["to"] == person])
    print(f"\nafter 4 asks by 'a stranger': {sent_to_owner} mail(s) delivered; the 4th ask (the owner's) gets none")
    assert sent_to_owner == 3  # the 4th, whoever made it, is silent


async def test_a_mail_server_that_fails_shows_the_visitor_nothing_and_logs_no_address(mail, person, caplog):
    caplog.set_level(logging.DEBUG)
    mail.fail = True
    st, body, _, _ = await asgi_post(f"{A}/forgot", {"email": person})
    assert st == 200 and json.loads(body) == {"status": "ok"}
    await asyncio.sleep(0.3)
    assert person not in caplog.text
    assert "Traceback" not in body.decode()


async def test_the_token_is_nowhere_but_the_mail_and_the_audit_lines_name_no_token(mail, person, world, caplog):
    caplog.set_level(logging.DEBUG)
    await asgi_post(f"{A}/forgot", {"email": person})
    await asyncio.sleep(0.3)
    tok = token_in(mail)
    await asgi_post(f"{A}/reset", {"token": tok, "password": "Mat-khau-moi-7391"})
    blob = json.dumps([[e.summary, e.metadata_, e.object_label, e.actor] for e in await rows(world, m.AuditEvent)], default=str)
    assert tok not in blob and "Mat-khau-moi-7391" not in blob
    assert tok not in caplog.text and "Mat-khau-moi-7391" not in caplog.text
    actions = [e.action for e in await rows(world, m.AuditEvent)]
    assert "password.reset_requested" in actions and "password.reset_by_email" in actions


async def test_the_recovery_status_is_public_and_reveals_only_on_or_off(app_client, mail):
    r = await app_client.get(f"{A}/recovery")
    assert r.status_code == 200 and r.json() == {"enabled": True}


async def test_the_onboarding_steps_count_only_this_businesss_channel_and_conversations(three, world):
    c = three["c"]
    # A has its own channel (the `world` one); take it away and B's and C's channels must not make step 1 "done"
    async with system_session() as s:
        (await s.get(m.Connector, world.cn.id)).status = "disabled"
    r = (await c.get("/api/v1/onboarding")).json()
    ch = next(x for x in r["steps"] if x["id"] == "channel")
    assert ch["done"] is False and ch["count"] == 0


async def test_the_first_requests_from_a_new_address_at_the_same_time_do_not_crash(mail, person):
    res = await asyncio.gather(*[asgi_post(f"{A}/forgot", {"email": f"n{i}@nowhere.vn"}) for i in range(6)], return_exceptions=True)
    assert all(isinstance(r, tuple) and r[0] == 200 for r in res), [type(r).__name__ if not isinstance(r, tuple) else r[0] for r in res]
