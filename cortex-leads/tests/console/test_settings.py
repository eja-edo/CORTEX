"""WP39-41: the business profile, where pushes go, the channels, and the AI overview. Owner only; a secret is shown once."""
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from support import h, sign_in
from wp5_support import rows

from cortex_leads.config import get_settings
from cortex_leads.core.identity import ai_disclosure, clean_ai_name
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session

B = "/api/v1/settings"


@pytest.fixture
async def owner(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "owner", None)
    csrf = await sign_in(app_client, key)
    return app_client, h(csrf)


@pytest.fixture
def public_ip(monkeypatch):
    async def resolve(_host):
        return ["93.184.216.34"]

    monkeypatch.setattr("cortex_leads.connectors.egress.resolve_host", resolve)


GOOD = {"name": "Trung tâm Minh Khai", "timezone": "Asia/Ho_Chi_Minh", "hours": {"start": "07:30", "end": "20:00"}, "ai_name": "Mai"}


# --- WP39 ---------------------------------------------------------------------------------------------
def test_the_ai_line_always_says_it_is_an_ai_whatever_name_it_is_given():
    assert ai_disclosure("Trung tâm ABC") == "Trợ lý AI của Trung tâm ABC"
    assert ai_disclosure("Trung tâm ABC", "Mai") == "Trợ lý AI Mai của Trung tâm ABC"
    assert clean_ai_name("  Mai   Linh ") == "Mai Linh" and clean_ai_name("   ") is None and clean_ai_name(None) is None
    for bad in ("http://x.vn", "Mai\nLinh", "a" * 41, "<b>Mai</b>", "Mai@x"):
        with pytest.raises(ValueError):
            clean_ai_name(bad)


async def test_the_profile_is_read_and_saved_to_every_sandbox_and_the_change_is_logged(owner, world):
    client, hd = owner
    before = (await client.get(f"{B}/business")).json()
    assert before["name"] == "Acme" and before["hours"] == {"start": "08:00", "end": "21:00"} and before["ai_name"] is None
    assert before["disclosure"] == "Trợ lý AI của Acme"
    r = await client.put(f"{B}/business", json=GOOD, headers=hd)
    assert r.status_code == 200, r.text
    assert r.json()["disclosure"] == "Trợ lý AI Mai của Trung tâm Minh Khai"
    async with tenant_session(world.t.id) as s:
        t = await s.get(m.Tenant, world.t.id)
        assert (t.name, t.ai_name) == ("Trung tâm Minh Khai", "Mai")
        assert all(sb.business_hours["start"] == "07:30" and sb.business_hours["end"] == "20:00" for sb in (await s.execute(select(m.Sandbox))).scalars())
    ev = [e for e in await rows(world, m.AuditEvent) if e.action == "settings.updated"]
    assert len(ev) == 1 and {c["field"] for c in ev[0].metadata_["changes"]} >= {"name", "hours.start", "hours.end", "ai_name"}
    await client.put(f"{B}/business", json=GOOD, headers=hd)  # nothing changed: no second line
    assert len([e for e in await rows(world, m.AuditEvent) if e.action == "settings.updated"]) == 1


@pytest.mark.parametrize("patch,code", [
    ({"hours": {"start": "25:00", "end": "20:00"}}, "BAD_HOURS"), ({"hours": {"start": "9:00", "end": "20:00"}}, "BAD_HOURS"),
    ({"hours": {"start": "20:00", "end": "08:00"}}, "BAD_HOURS"), ({"hours": {"start": "08:00", "end": "08:00"}}, "BAD_HOURS"),
    ({"timezone": "Mars/Phobos"}, "BAD_TIMEZONE"), ({"timezone": "../../etc/passwd"}, "BAD_TIMEZONE"),
    ({"ai_name": "http://evil.vn"}, "BAD_AI_NAME"), ({"ai_name": "Mai\nLinh"}, "BAD_AI_NAME"), ({"name": " x "}, "BAD_NAME"),
])
async def test_a_profile_that_cannot_work_is_refused_and_nothing_changes(owner, world, patch, code):
    client, hd = owner
    r = await client.put(f"{B}/business", json={**GOOD, **patch}, headers=hd)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code
    async with tenant_session(world.t.id) as s:
        assert (await s.get(m.Tenant, world.t.id)).name == "Acme"


async def test_clearing_the_ai_name_goes_back_to_the_business_name(owner):
    client, hd = owner
    await client.put(f"{B}/business", json=GOOD, headers=hd)
    r = await client.put(f"{B}/business", json={**GOOD, "ai_name": ""}, headers=hd)
    assert r.json()["ai_name"] is None and r.json()["disclosure"] == "Trợ lý AI của Trung tâm Minh Khai"


async def test_staff_can_neither_read_nor_change_the_profile(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    hd = h(await sign_in(app_client, key))
    assert (await app_client.get(f"{B}/business")).status_code == 403
    assert (await app_client.put(f"{B}/business", json=GOOD, headers=hd)).status_code == 403


async def test_a_change_without_the_csrf_token_is_refused(owner):
    client, _ = owner
    assert (await client.put(f"{B}/business", json=GOOD)).status_code == 403


# --- WP40 ---------------------------------------------------------------------------------------------
async def test_a_push_target_is_added_masked_when_shown_and_switched_off_not_deleted(owner, world, public_ip):
    client, hd = owner
    tg = await client.post(f"{B}/notify-targets", json={"kind": "telegram", "address": "-1001234567890", "label": "Nhóm tư vấn"}, headers=hd)
    mz = await client.post(f"{B}/notify-targets", json={"kind": "mezon", "address": "https://webhook.mezon.ai/hook/SECRET-TOKEN-123"}, headers=hd)
    assert tg.status_code == mz.status_code == 201
    shown = (await client.get(f"{B}/notify-targets")).json()
    text_ = str(shown)
    assert "SECRET-TOKEN-123" not in text_ and "1001234567890" not in text_  # a webhook address is a credential; a chat id needs only its tail
    assert {i["address"] for i in shown["items"]} == {"…7890", "webhook.mezon.ai/…"}
    assert all("SECRET" not in str(e.metadata_) + e.summary for e in await rows(world, m.AuditEvent))
    assert (await client.delete(f"{B}/notify-targets/{tg.json()['id']}", headers=hd)).status_code == 200
    assert [i["kind"] for i in (await client.get(f"{B}/notify-targets")).json()["items"]] == ["mezon"]
    async with tenant_session(world.t.id) as s:  # the row stays, off: the role has no DELETE and the trail points at it
        assert (await s.get(m.NotifyTarget, __import__("uuid").UUID(tg.json()["id"]))).active is False
    assert (await client.delete(f"{B}/notify-targets/{tg.json()['id']}", headers=hd)).status_code == 404


@pytest.mark.parametrize("kind,address", [
    ("mezon", "http://webhook.mezon.ai/hook/x"), ("mezon", "https://169.254.169.254/latest/meta-data"), ("mezon", "https://10.0.0.5/admin"),
    ("mezon", "https://evil.example.com/hook"), ("mezon", "https://user:pw@webhook.mezon.ai/hook"), ("mezon", "https://webhook.mezon.ai:8443/hook"),
    ("telegram", "abc"), ("telegram", "-12"), ("telegram", "-100 123 456"),
])
async def test_a_destination_that_could_leak_or_reach_inside_is_refused(owner, public_ip, kind, address):
    client, hd = owner
    r = await client.post(f"{B}/notify-targets", json={"kind": kind, "address": address}, headers=hd)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_ADDRESS", (address, r.text)
    assert (await client.get(f"{B}/notify-targets")).json()["items"] == []


async def test_a_webhook_whose_name_points_inside_is_refused_even_on_an_allowed_host(owner, monkeypatch):
    async def inside(_host):
        return ["10.0.0.9"]

    monkeypatch.setattr("cortex_leads.connectors.egress.resolve_host", inside)
    client, hd = owner
    assert (await client.post(f"{B}/notify-targets", json={"kind": "mezon", "address": "https://webhook.mezon.ai/hook/x"}, headers=hd)).status_code == 422


async def test_a_target_can_be_bound_to_a_sandbox_of_this_business_only(owner, world, tenant_factory, sandbox_factory):
    client, hd = owner
    ok = await client.post(f"{B}/notify-targets", json={"kind": "telegram", "address": "-100999888", "sandbox_id": str(world.sb.id)}, headers=hd)
    assert ok.status_code == 201 and ok.json()["sandbox_id"] == str(world.sb.id)
    other = await sandbox_factory(await tenant_factory("Khác"))
    r = await client.post(f"{B}/notify-targets", json={"kind": "telegram", "address": "-100999888", "sandbox_id": str(other.id)}, headers=hd)
    assert r.status_code == 404


async def test_the_test_message_goes_through_the_real_senders_and_says_when_it_cannot(owner, world, monkeypatch, public_ip):
    client, hd = owner
    sent = []

    async def tg(_c, token, chat, text_):
        sent.append(("telegram", token, chat, text_))
        return True

    async def mz(_c, url, text_):
        sent.append(("mezon", url, text_))
        return False

    monkeypatch.setattr("cortex_leads.notify.worker._send", tg)
    monkeypatch.setattr("cortex_leads.notify.worker._send_mezon", mz)
    a = (await client.post(f"{B}/notify-targets", json={"kind": "telegram", "address": "-100123456"}, headers=hd)).json()["id"]
    b = (await client.post(f"{B}/notify-targets", json={"kind": "mezon", "address": "https://webhook.mezon.ai/hook/x"}, headers=hd)).json()["id"]
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_TOKEN", None)
    r = await client.post(f"{B}/notify-targets/{a}/test", headers=hd)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_CONFIGURED" and sent == []  # no bot token: say so, send nothing
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_TOKEN", "bot-token-for-test")
    assert (await client.post(f"{B}/notify-targets/{a}/test", headers=hd)).json() == {"ok": True}
    assert (await client.post(f"{B}/notify-targets/{b}/test", headers=hd)).json() == {"ok": False}
    assert sent[0][:3] == ("telegram", "bot-token-for-test", "-100123456") and "Tin thử" in sent[0][3]  # nothing of a customer in it
    assert [e.result for e in await rows(world, m.AuditEvent) if e.action == "notify_target.tested"] == ["success", "failed"]


async def test_one_business_cannot_see_or_switch_off_the_targets_of_another(owner, world, tenant_factory):
    client, hd = owner
    other = await tenant_factory("Khác")
    async with tenant_session(other.id) as s:
        t = m.NotifyTarget(tenant_id=other.id, kind="telegram", address="-100777666")
        s.add(t)
        await s.flush()
        theirs = t.id
    assert (await client.get(f"{B}/notify-targets")).json()["items"] == []
    assert (await client.delete(f"{B}/notify-targets/{theirs}", headers=hd)).status_code == 404
    assert (await client.post(f"{B}/notify-targets/{theirs}/test", headers=hd)).status_code == 404


# --- WP41 ---------------------------------------------------------------------------------------------
async def test_a_channel_is_made_with_its_secret_shown_once_and_stored_encrypted(owner, world, monkeypatch):
    client, hd = owner
    monkeypatch.setattr(get_settings(), "PUBLIC_BASE_URL", "https://cortex.example.vn")
    r = await client.post(f"{B}/channels", json={"kind": "messenger", "sandbox_id": str(world.sb.id)}, headers=hd)
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["id"].startswith("conn_") and len(made["secret"]) >= 40 and made["ingest_url"] == "https://cortex.example.vn/ingest/v1/events"
    async with system_session() as s:
        row = await s.get(m.Connector, made["id"])
    assert row.tenant_id == world.t.id and row.sandbox_id == world.sb.id and row.trust == "custom" and row.status == "active"
    assert Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(row.secret_enc).decode() == made["secret"] and made["secret"].encode() not in row.secret_enc
    listing = (await client.get(f"{B}/channels")).json()
    assert made["secret"] not in str(listing) and {c["id"] for c in listing["items"]} == {made["id"], world.cn.id}
    assert next(c for c in listing["items"] if c["id"] == made["id"])["last_event_at"] is None
    trail = "".join(e.summary + str(e.metadata_) + str(e.object_id) for e in await rows(world, m.AuditEvent))
    assert made["secret"] not in trail and made["secret"] not in r.headers.get("set-cookie", "")


async def test_the_channel_list_shows_when_something_last_arrived(owner, world):
    client, _ = owner
    async with tenant_session(world.t.id) as s:
        s.add(m.IngestEvent(tenant_id=world.t.id, connector_id=world.cn.id, external_id="e1", type="message.created", payload={}, status="processed"))
    item = next(c for c in (await client.get(f"{B}/channels")).json()["items"] if c["id"] == world.cn.id)
    assert item["last_event_at"] is not None and item["kind"] == "messenger" and item["sandbox"]


@pytest.mark.parametrize("body", [{"kind": "telegram"}, {"kind": "../x"}, {"kind": ""}])
async def test_a_channel_of_an_unknown_kind_is_refused(owner, world, body):
    client, hd = owner
    r = await client.post(f"{B}/channels", json={**body, "sandbox_id": str(world.sb.id)}, headers=hd)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "UNKNOWN_CHANNEL"


async def test_a_channel_cannot_be_put_on_another_businesss_sandbox_nor_switched_off_by_another(owner, world, tenant_factory, sandbox_factory, connector_factory):
    client, hd = owner
    other_t = await tenant_factory("Khác")
    other_sb = await sandbox_factory(other_t)
    theirs = await connector_factory(other_sb)
    assert (await client.post(f"{B}/channels", json={"kind": "messenger", "sandbox_id": str(other_sb.id)}, headers=hd)).status_code == 404
    assert theirs.id not in str((await client.get(f"{B}/channels")).json())  # `connector` has no row level security: the filter is the guard
    assert (await client.delete(f"{B}/channels/{theirs.id}", headers=hd)).status_code == 404
    async with system_session() as s:
        assert (await s.get(m.Connector, theirs.id)).status == "active"


async def test_switching_a_channel_off_stops_its_bridge_and_is_logged(owner, world):
    client, hd = owner
    assert (await client.delete(f"{B}/channels/{world.cn.id}", headers=hd)).status_code == 200
    async with system_session() as s:
        assert (await s.get(m.Connector, world.cn.id)).status == "disabled"
    assert next(c for c in (await client.get(f"{B}/channels")).json()["items"] if c["id"] == world.cn.id)["status"] == "disabled"
    assert (await client.delete(f"{B}/channels/{world.cn.id}", headers=hd)).status_code == 404
    assert any(e.action == "channel.removed" for e in await rows(world, m.AuditEvent))


# --- the AI tab ---------------------------------------------------------------------------------------
async def test_the_ai_overview_gathers_mode_status_and_what_the_skills_forbid(owner, world):
    client, hd = owner
    data = (await client.get(f"{B}/ai")).json()
    assert data["disclosure"] == "Trợ lý AI của Acme"
    (sb,) = data["sandboxes"]
    assert sb["id"] == str(world.sb.id) and sb["send_mode"] == "manual" and sb["status"] == "active"
    assert {k["name"] for k in sb["skills"]} >= {"hoi-lai-khach-im", "hoi-lai-dung-hen"} and isinstance(sb["never_say"], list)
    assert (await client.post(f"/api/v1/sandboxes/{world.sb.id}/send-mode", json={"mode": "auto"}, headers=hd)).status_code == 200
    assert (await client.get(f"{B}/ai")).json()["sandboxes"][0]["send_mode"] == "auto"  # it reads the same state the existing endpoint writes
