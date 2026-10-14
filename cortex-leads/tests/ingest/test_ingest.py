import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from wp5_support import live_skills

from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.ingest.signing import sign, verify

SECRET = "test-connector-secret"


@pytest.fixture
async def env(tenant_factory, sandbox_factory, connector_factory):
    t = await tenant_factory()
    sb = await sandbox_factory(t)
    c = await connector_factory(sb, secret=SECRET)
    return t, sb, c


def ev(ext="e1", role="customer", text="Học phí bao nhiêu?", conv="c1", at=None, **kw):
    d = {"type": "message.created", "external_id": ext,
         "occurred_at": (at or datetime.now(UTC)).isoformat(),
         "channel": {"kind": "messenger", "account_ref": "p1"},
         "conversation": {"external_id": conv},
         "contact": {"external_id": "psid1", "display_name": "An"},
         "sender": {"role": role}, "text": text}
    d.update(kw)
    return d


async def post(client, connector, events, *, secret=SECRET, ts=None, raw=None, cid=None):
    body = raw if raw is not None else json.dumps(
        {"format": "cortex.event/1", "events": events}).encode()
    ts = int(time.time()) if ts is None else ts
    return await client.post("/ingest/v1/events", content=body, headers={
        "X-Connector-Id": cid or connector.id, "X-Timestamp": str(ts),
        "X-Signature": sign(secret.encode(), ts, body), "Content-Type": "application/json"})


def test_sign_verify_roundtrip() -> None:
    now = datetime.now(UTC)
    ts = int(now.timestamp())
    sig = sign(b"k", ts, b"{}")
    assert sig.startswith("sha256=")
    assert verify(b"k", ts, b"{}", sig, now=now, max_skew_s=300)
    assert not verify(b"k", ts, b"{ }", sig, now=now, max_skew_s=300)
    assert not verify(b"x", ts, b"{}", sig, now=now, max_skew_s=300)
    assert not verify(b"k", ts, b"{}", sig, now=now + timedelta(seconds=301), max_skew_s=300)


async def test_bad_signature_skew_unknown_connector_are_401(app_client, env) -> None:
    _, _, c = env
    assert (await post(app_client, c, [ev()], secret="wrong")).status_code == 401
    assert (await post(app_client, c, [ev()], ts=int(time.time()) - 1000)).status_code == 401
    assert (await post(app_client, c, [ev()], cid="conn_nope")).status_code == 401
    r = await app_client.post("/ingest/v1/events", content=b"{}")
    assert r.status_code == 401


async def test_disabled_connector_is_403(app_client, tenant_factory, sandbox_factory,
                                         connector_factory) -> None:
    sb = await sandbox_factory(await tenant_factory())
    c = await connector_factory(sb, secret=SECRET, status="disabled")
    assert (await post(app_client, c, [ev()])).status_code == 403


async def test_batch_too_large_is_413(app_client, env) -> None:
    _, _, c = env
    r = await post(app_client, c, [ev(ext=f"e{i}") for i in range(101)])
    assert r.status_code == 413


async def test_bad_envelope_is_400(app_client, env) -> None:
    _, _, c = env
    assert (await post(app_client, c, [], raw=b"not json")).status_code == 400
    raw = json.dumps({"format": "other/1", "events": []}).encode()
    assert (await post(app_client, c, [], raw=raw)).status_code == 400


async def test_schema_errors_are_rejected_with_reason(app_client, env) -> None:
    _, _, c = env
    bad_role = ev("e1", role="alien")
    no_ext = ev("e2")
    del no_ext["external_id"]
    naive = ev("e3", at=datetime(2026, 1, 1))
    extra = ev("e4", tenant_id=str(uuid4()))
    wrong_chan = ev("e5", channel={"kind": "zalo_oa"})
    r = await post(app_client, c, [bad_role, no_ext, naive, extra, wrong_chan])
    assert r.status_code == 202
    res = r.json()["results"]
    assert [x["status"] for x in res] == ["rejected"] * 5
    assert all(x["error"] for x in res)
    assert res[1]["external_id"] is None
    # a corrected resend of a rejected event is processed, not "duplicate"
    r = await post(app_client, c, [ev("e1")])
    assert r.json()["results"][0]["status"] == "accepted"


async def test_resend_is_duplicate(app_client, env) -> None:
    t, _, c = env
    e = ev("same")
    assert (await post(app_client, c, [e])).json()["results"][0]["status"] == "accepted"
    assert (await post(app_client, c, [e])).json()["results"][0]["status"] == "duplicate"
    r = await post(app_client, c, [ev("dup"), ev("dup")])
    assert [x["status"] for x in r.json()["results"]] == ["accepted", "duplicate"]
    async with tenant_session(t.id) as s:
        n = len((await s.execute(select(m.Message))).scalars().all())
    assert n == 2


async def test_tenant_comes_from_connector_not_body(app_client, env, tenant_factory) -> None:
    t, sb, c = env
    other = await tenant_factory("Other")
    e = ev("t1", meta={"tenant_id": str(other.id), "sandbox_id": str(uuid7())})
    assert (await post(app_client, c, [e])).json()["results"][0]["status"] == "accepted"
    async with tenant_session(t.id) as s:
        conv = (await s.execute(select(m.Conversation))).scalar_one()
        assert conv.tenant_id == t.id and conv.sandbox_id == sb.id
        assert conv.intent == "hoi_gia" and conv.last_customer_msg_id == "t1"
    async with tenant_session(other.id) as s:
        assert (await s.execute(select(m.Message))).first() is None


async def test_staff_message_updates_last_staff_at_and_clock(app_client, env) -> None:
    t, _, c = env
    base = datetime.now(UTC) - timedelta(hours=2)
    await post(app_client, c, [ev("a", at=base)])
    await post(app_client, c, [ev("b", role="staff", text="Dạ chào", at=base + timedelta(hours=1),
                                  staff={"external_id": "nv1"})])
    await post(app_client, c, [ev("bot", role="bot", text="auto", at=base + timedelta(hours=1, minutes=5))])
    async with tenant_session(t.id) as s:
        conv = (await s.execute(select(m.Conversation))).scalar_one()
        staff_msg = (await s.execute(select(m.Message).where(m.Message.external_id == "b"))).scalar_one()
    assert conv.last_staff_at == base + timedelta(hours=1)
    assert conv.last_customer_at == base
    assert conv.next_check_at == base + timedelta(hours=25)
    assert staff_msg.staff_ref == "nv1"


async def test_next_check_follows_live_skill_after(app_client, env) -> None:
    t, sb, c = env
    await live_skills(t, sb)  # hoi-lai-khach-im: after 20h
    base = datetime.now(UTC) - timedelta(hours=2)
    await post(app_client, c, [ev("a", at=base)])
    async with tenant_session(t.id) as s:
        conv = (await s.execute(select(m.Conversation))).scalar_one()
    assert conv.next_check_at == base + timedelta(hours=20)


async def test_new_message_cancels_pending_jobs_and_expires_drafts(
        app_client, env, conversation_factory, seed) -> None:
    t, sb, c = env
    conv = await conversation_factory(c, external_id="c1")
    job = await seed(m.FollowupJob(tenant_id=t.id, sandbox_id=sb.id, conversation_id=conv.id,
                                   skill_name="s", skill_version=1, event_type="conversation.silent",
                                   dedupe_key="k1"))
    running = await seed(m.FollowupJob(tenant_id=t.id, sandbox_id=sb.id, conversation_id=conv.id,
                                       skill_name="s", skill_version=1, event_type="conversation.silent",
                                       dedupe_key="k2", status="running"))
    draft = await seed(m.Draft(tenant_id=t.id, sandbox_id=sb.id, conversation_id=conv.id,
                               text="nháp", status="proposed"))
    sent = await seed(m.Draft(tenant_id=t.id, sandbox_id=sb.id, conversation_id=conv.id,
                              text="đã gửi", status="sent"))
    r = await post(app_client, c, [ev("new1", text="Chào shop, còn khóa không?")])
    assert r.json()["results"][0]["status"] == "accepted"
    async with tenant_session(t.id) as s:
        st = lambda model, i: s.scalar(select(model.status).where(model.id == i))  # noqa: E731
        assert await st(m.FollowupJob, job.id) == "skipped"
        assert await st(m.FollowupJob, running.id) == "running"
        assert await st(m.Draft, draft.id) == "expired"
        assert await st(m.Draft, sent.id) == "sent"
        logs = (await s.execute(select(m.DecisionLog))).scalars().all()
    by = {x.decision: x for x in logs}
    assert by["job_cancelled_new_message"].detail == {"count": 1, "sender_role": "customer"}
    assert by["draft_expired"].detail["count"] == 1
    assert "Chào shop" not in json.dumps([x.detail for x in logs])
