"""WP7 — walking skeleton on real Postgres: Pancake-shaped messages -> signed ingest -> silence
clock -> job -> select -> run (FakeProvider) -> draft -> staff review -> supervisor read-model.
No network, no real LLM. Also the cross-cutting invariants A1/A3/A6/A8/A9 and PII (DESIGN §5.0)."""
import ast
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from wp5_support import GOOD_DRAFT, SKILLS, gateway, reply

from bridges.pancake.mapper import map_message
from cortex_leads.app import create_app
from cortex_leads.clock.sweeper import sweep_once
from cortex_leads.core.vocabulary import OUTPUT_KINDS
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.ingest.signing import sign
from cortex_leads.llm.types import LLMResult, ToolCall
from cortex_leads.runner.customer_run import run_pending
from cortex_leads.skills.loader import sync_dir
from cortex_leads.skills.registry import promote
from cortex_leads.tools.registry import default_registry

SECRET = "e2e-connector-secret"
PAGE = "page123"
CUSTOMER = {"id": "psid_1001", "name": "Nguyễn Văn An"}
ASK = "Chào shop, em là Nguyễn Văn An, sđt 0901 234 567. Khóa IELTS giá bao nhiêu?"
STAFF_REPLY = "Dạ khóa IELTS bên em có nhiều lớp, chị xem giúp em nhé"
CUSTOMER_PII = ("0901", "234 567", "Nguyễn Văn An")


def pmsg(mid: str, text: str, at: datetime, frm: dict) -> dict:
    """A Pancake message as the API returns it (UTC, no offset)."""
    return {"id": mid, "inserted_at": at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "original_message": text, "from": frm, "attachments": []}


def event(mid: str, text: str, at: datetime, *, staff: bool = False, conv: str = "psid_1001",
          customer: dict = CUSTOMER) -> dict:
    frm = {"id": PAGE, "admin_id": "adm_7"} if staff else customer
    ev = map_message(pmsg(mid, text, at, frm), page_id=PAGE, conversation_id=conv,
                     customer=customer, channel_kind="messenger")
    assert ev is not None
    return ev


async def post(client, connector, events: list[dict], *, secret: str = SECRET,
               envelope_extra: dict | None = None, connector_id: str | None = None):
    body = json.dumps({"format": "cortex.event/1", "events": events, **(envelope_extra or {})}).encode()
    ts = int(time.time())
    return await client.post("/ingest/v1/events", content=body, headers={
        "X-Connector-Id": connector_id or connector.id, "X-Timestamp": str(ts),
        "X-Signature": sign(secret.encode(), ts, body), "Content-Type": "application/json"})


def statuses(resp) -> list[str]:
    assert resp.status_code == 202, resp.text
    return [r["status"] for r in resp.json()["results"]]


def hdr(key: str) -> dict:
    return {"X-Api-Key": key}


class Env:
    pass


@pytest.fixture
async def env(tenant_factory, sandbox_factory, connector_factory, catalog_factory,
              api_key_factory) -> Env:
    e = Env()
    e.t = await tenant_factory()
    e.sb = await sandbox_factory(e.t)
    e.cn = await connector_factory(e.sb, secret=SECRET)
    await catalog_factory(e.t, code="KH01", name="Khóa IELTS", price=2_500_000)
    async with tenant_session(e.t.id) as s:  # only the silence skill is live at first
        await sync_dir(s, e.t.id, e.sb.id, SKILLS)
        await promote(s, e.sb.id, "hoi-lai-khach-im", 4, "shadow")
        await promote(s, e.sb.id, "hoi-lai-khach-im", 4, "live")
    _, e.staff_key = await api_key_factory(e.t, "staff", "nv1")
    _, e.sup_key = await api_key_factory(e.t, "supervisor", None)
    e.t0 = datetime.now(UTC)
    return e


async def ingest_price_chat(client, env: Env) -> None:
    """Customer asks the price 30h ago, staff answers an hour later, customer goes quiet."""
    evs = [event("m1", ASK, env.t0 - timedelta(hours=30)),
           event("m2", STAFF_REPLY, env.t0 - timedelta(hours=29), staff=True)]
    assert statuses(await post(client, env.cn, evs)) == ["accepted", "accepted"]


def catalog_then_draft(draft: dict = GOOD_DRAFT):
    call = LLMResult(content=None, tool_calls=[ToolCall("c1", "lookup_catalog", {"query": "KH01"})],
                     tokens_in=50, tokens_out=5, model="fake")
    return gateway(call, reply(draft))


async def count(env: Env, model) -> int:
    async with tenant_session(env.t.id) as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


# --- the walking skeleton -----------------------------------------------------------------------
async def test_walking_skeleton(app_client, env):
    await ingest_price_chat(app_client, env)
    (conv,) = await rows_for(env, m.Conversation)
    assert conv.intent == "hoi_gia" and conv.next_check_at is not None

    now = datetime.now(UTC)
    assert await sweep_once(now) == 1  # the silence clock fires once
    (job,) = await rows_for(env, m.FollowupJob)
    assert job.skill_name == "hoi-lai-khach-im" and job.event_type == "conversation.silent"
    assert job.dedupe_key == f"silent:{conv.id}:{conv.last_customer_msg_id}"

    gw, prov = catalog_then_draft()
    assert await run_pending(now, gw) == 1
    (job,) = await rows_for(env, m.FollowupJob)
    (run,) = await rows_for(env, m.TriggerRun)
    (draft,) = await rows_for(env, m.Draft)
    assert (job.status, run.status, run.act, draft.status) == ("done", "ok", "draft", "proposed")
    assert draft.run_id == run.id and len(prov.calls) == 2

    r = await app_client.get("/review/drafts", headers=hdr(env.staff_key))
    (d,) = r.json()["drafts"]
    assert "2.500.000" in d["text"] and d["window"]["basis"] == "human_agent"

    r = await app_client.post(f"/review/drafts/{d['id']}/action", json={"action": "sent"},
                              headers=hdr(env.staff_key))
    assert r.status_code == 200
    (sa,) = await rows_for(env, m.StaffAction)
    (run,) = await rows_for(env, m.TriggerRun)
    assert sa.action == "sent" and sa.staff_ref == "nv1" and run.staff_outcome == "sent"

    r = await app_client.get("/supervisor/summary", headers=hdr(env.sup_key))
    assert r.status_code == 200
    blob = r.text
    for secret_text in ("IELTS", "2.500.000", "Nguyễn", "0901", "giá", draft.text, ASK):
        assert secret_text not in blob
    assert "text" not in r.json()
    # staff key cannot read the supervisor view, supervisor cannot read drafts
    assert (await app_client.get("/supervisor/summary", headers=hdr(env.staff_key))).status_code == 403
    assert (await app_client.get("/review/drafts", headers=hdr(env.sup_key))).status_code == 403


async def rows_for(env: Env, model):
    async with tenant_session(env.t.id) as s:
        return list((await s.execute(select(model))).scalars())


# --- A6: a second skill goes live with data only ---------------------------------------------------
async def test_a6_second_skill_by_sync_and_promote_only(app_client, env):
    ev = event("p1", "Tuần sau em báo lại shop nhé", env.t0 - timedelta(hours=30))
    assert statuses(await post(app_client, env.cn, [ev])) == ["accepted"]
    today = datetime.now(UTC).date()
    async with tenant_session(env.t.id) as s:
        await s.execute(update(m.Conversation).values(
            promised_date=today - timedelta(days=1),
            next_check_at=datetime.now(UTC) - timedelta(hours=1)))

    # not live yet: the clock fires, the engine finds no skill, no job
    assert await sweep_once(datetime.now(UTC)) == 1
    assert await rows_for(env, m.FollowupJob) == []

    async with tenant_session(env.t.id) as s:  # the only "deployment": sync + promote
        await sync_dir(s, env.t.id, env.sb.id, SKILLS)
        await promote(s, env.sb.id, "hoi-lai-dung-hen", 3, "shadow")
        await promote(s, env.sb.id, "hoi-lai-dung-hen", 3, "live")
        await s.execute(update(m.Conversation).values(
            next_check_at=datetime.now(UTC) - timedelta(hours=1)))
    now = datetime.now(UTC)
    assert await sweep_once(now) == 1
    (job,) = await rows_for(env, m.FollowupJob)
    assert (job.skill_name, job.event_type) == ("hoi-lai-dung-hen", "conversation.promised_date_reached")

    gw, _ = gateway(reply({"act": "draft", "reason_code": "chua_san_sang", "has_new_info": True,
                           "claims": [], "text": "Chào chị, hôm nay là ngày chị hẹn báo lại, chị sắp xếp được chưa ạ?"}))
    assert await run_pending(now, gw) == 1
    (run,) = await rows_for(env, m.TriggerRun)
    (draft,) = await rows_for(env, m.Draft)
    assert run.skill_name == "hoi-lai-dung-hen" and draft.status == "proposed"


# --- A9: one send path -----------------------------------------------------------------------------------
def test_a9_one_send_path_tool_outbox_worker():
    reg = default_registry()
    assert [s.name for s in reg._tools.values() if s.effect == "customer"] == ["send_message"]
    assert [k for k in OUTPUT_KINDS if "send" in k] == ["send_to_customer"]

    # No HTTP route sends by itself: the only way is a staff click on an existing draft action.
    known = {"/ingest/v1/events", "/review/drafts", "/review/drafts/{draft_id}/action",
             "/supervisor/summary", "/health", "/review/conversations/{conversation_id}/facts",
             "/review/conversations/{conversation_id}/outcome",
             "/review/conversations/{conversation_id}/offchannel", "/review/facts/{fact_id}/{op}",
             "/review/confirmations"}
    # WP27 console: the same actions as above plus owner-only controls; each is behind the session (tested in tests/console)
    known |= {"/api/v1/assistant/chat", "/api/v1/bookings/{booking_id}/cancel", "/api/v1/conversations",
              "/api/v1/conversations/{conversation_id}", "/api/v1/conversations/{conversation_id}/booking",
              "/api/v1/conversations/{conversation_id}/outcome", "/api/v1/conversations/{conversation_id}/reply",
              "/api/v1/drafts/{draft_id}/action", "/api/v1/facts/{fact_id}/{verb}", "/api/v1/kill-switch", "/api/v1/proposals",
              "/api/v1/proposals/{proposal_id}/{verb}", "/api/v1/sandboxes", "/api/v1/sandboxes/{sandbox_id}/{verb}",
              "/api/v1/session", "/api/v1/session/login", "/api/v1/session/logout", "/api/v1/skills", "/api/v1/skills/form-options",
              "/api/v1/skills/preview", "/api/v1/skills/{skill_id}", "/api/v1/skills/{skill_id}/{verb}",
              "/api/v1/sandboxes/{sandbox_id}", "/api/v1/sandboxes/{sandbox_id}/send-mode", "/api/v1/sandboxes/{sandbox_id}/tools/{tool}", "/api/v1/sandboxes/{sandbox_id}/tools/{tool}/{state}",
              "/api/v1/skills/{skill_id}/revert", "/api/v1/sources", "/api/v1/sources/mcp/describe", "/api/v1/sources/{source_id}", "/api/v1/sources/{source_id}/review",
              "/api/v1/sources/{source_id}/sandbox", "/api/v1/sources/{source_id}/{verb}", "/api/v1/tools",
              "/api/v1/session/password", "/api/v1/session/sessions", "/api/v1/session/sessions/{session_id}/revoke", "/api/v1/session/logout-all",
              "/api/v1/team", "/api/v1/team/{user_id}", "/api/v1/team/{user_id}/reset-password", "/api/v1/team/{user_id}/end-sessions",
              "/api/v1/audit", "/api/v1/audit/export", "/api/v1/audit/verify", "/api/v1/audit/{event_id}",
              "/api/v1/lessons", "/api/v1/lessons/{lesson_id}", "/api/v1/lessons/upload/session", "/api/v1/lessons/{lesson_id}/media", "/api/v1/grading", "/api/v1/grading/{item_id}", "/api/v1/grading/{item_id}/decision",
              "/api/v1/assignments", "/api/v1/assignments/ai", "/api/v1/assignments/{draft_id}/decision",
              "/api/v1/google/accounts", "/api/v1/google/accounts/connect", "/api/v1/google/accounts/{account_id}/revoke", "/api/v1/google/accounts/{account_id}/courses",
              "/api/v1/google/callback", "/api/v1/google/classroom-sources", "/api/v1/classes", "/api/v1/classes/{class_id}",
              "/api/v1/google/accounts/{account_id}/folders", "/api/v1/google/lesson-sources", "/api/v1/google/sources/{kind}/{source_id}/active",
         "/api/v1/google/accounts/{account_id}", "/api/v1/google/accounts/{account_id}/reconnect", "/api/v1/classes/{class_id}/relink",
         "/api/v1/classes/{class_id}/assignments", "/api/v1/assignments/{assignment_id}/grade", "/api/v1/grading/{item_id}/grade", "/api/v1/lessons/{lesson_id}/release"}
    assert {p for p in create_app().openapi()["paths"] if not p.startswith("/staff")} == known

    # Network libraries are imported only by the LLM provider, the outbound worker (customers, A9) and the
    # staff push worker (WP17: fixed text built from counts, no customer data, never a customer's address) and
    # the read-only connectors (WP20/23: one request to a host the business listed, query redacted, no customer
    # address) and the cell router (WP25: forwards a bridge's signed batch untouched, holds no data).
    root = Path(__file__).resolve().parents[2] / "cortex_leads"
    net = {"httpx", "requests", "aiohttp", "urllib3", "smtplib", "socket", "openai", "http"}
    offenders = []
    for py in root.rglob("*.py"):
        if py.parent.name in ("llm", "outbound", "notify", "connectors", "cells"):
            continue
        for node in ast.walk(ast.parse(py.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            if {n.split(".")[0] for n in names} & net:
                offenders.append(str(py.relative_to(root)))
    assert offenders == [], f"network libraries outside llm/, outbound/, notify/, connectors/ and cells/: {offenders}"


# --- A1/A3: tenant isolation ---------------------------------------------------------------------------
async def test_a1_a3_tenant_isolation(app_client, env, tenant_factory, sandbox_factory,
                                      api_key_factory):
    other = await tenant_factory("Other")
    await sandbox_factory(other)
    _, key_b = await api_key_factory(other, "staff", "nvb")
    _, sup_b = await api_key_factory(other, "supervisor", None)

    await ingest_price_chat(app_client, env)
    assert await sweep_once(datetime.now(UTC)) == 1
    gw, _ = catalog_then_draft()
    await run_pending(datetime.now(UTC), gw)
    assert len(await rows_for(env, m.Draft)) == 1

    assert (await app_client.get("/review/drafts", headers=hdr(key_b))).json() == {"drafts": []}
    for status in ("proposed", "sent", "blocked", "expired"):
        assert (await app_client.get(f"/review/drafts?status={status}", headers=hdr(key_b))).json()["drafts"] == []
    s_b = (await app_client.get("/supervisor/summary", headers=hdr(sup_b))).json()
    assert s_b["runs"] is None and s_b["status"] == {}
    async with tenant_session(other.id) as s:
        for model in (m.Conversation, m.Message, m.FollowupJob, m.Draft, m.TriggerRun):
            assert (await s.execute(select(func.count()).select_from(model))).scalar_one() == 0

    # a forged tenant in the body is rejected (event) or refused (envelope); nothing lands anywhere
    forged = {**event("x1", "hi", env.t0 - timedelta(hours=1)), "tenant_id": str(other.id)}
    r = await post(app_client, env.cn, [forged])
    assert statuses(r) == ["rejected"]
    r = await post(app_client, env.cn, [], envelope_extra={"tenant_id": str(other.id)})
    assert r.status_code == 400
    # an unknown connector id does not authenticate (same 401 as a bad signature)
    assert (await post(app_client, env.cn, [], connector_id="cn_unknown")).status_code == 401
    assert await count_in(other, m.IngestEvent) == 0


async def count_in(tenant, model) -> int:
    async with tenant_session(tenant.id) as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


# --- A8: idempotent ingest -------------------------------------------------------------------------------
async def test_a8_resend_is_duplicate(app_client, env):
    evs = [event("m1", ASK, env.t0 - timedelta(hours=30)),
           event("m2", STAFF_REPLY, env.t0 - timedelta(hours=29), staff=True)]
    assert statuses(await post(app_client, env.cn, evs)) == ["accepted", "accepted"]
    assert await sweep_once(datetime.now(UTC)) == 1
    before = [await count(env, mod) for mod in (m.Message, m.FollowupJob, m.Conversation, m.Contact)]
    assert statuses(await post(app_client, env.cn, evs)) == ["duplicate", "duplicate"]
    assert await sweep_once(datetime.now(UTC)) == 0  # one shot per silence
    assert [await count(env, mod) for mod in (m.Message, m.FollowupJob, m.Conversation, m.Contact)] == before


# --- new customer message kills the draft ---------------------------------------------------------------
async def test_new_customer_message_expires_draft_and_sent_is_stale(app_client, env):
    await ingest_price_chat(app_client, env)
    await sweep_once(datetime.now(UTC))
    gw, _ = catalog_then_draft()
    await run_pending(datetime.now(UTC), gw)
    (d,) = (await app_client.get("/review/drafts", headers=hdr(env.staff_key))).json()["drafts"]

    back = event("m3", "Em quay lại rồi, cho em hỏi lịch khai giảng", datetime.now(UTC))
    assert statuses(await post(app_client, env.cn, [back])) == ["accepted"]
    (draft,) = await rows_for(env, m.Draft)
    assert draft.status == "expired"
    r = await app_client.post(f"/review/drafts/{d['id']}/action", json={"action": "sent"},
                              headers=hdr(env.staff_key))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STALE"
    assert await rows_for(env, m.StaffAction) == []


# --- fabricated price is blocked -------------------------------------------------------------------------
async def test_invented_price_is_blocked(app_client, env):
    await ingest_price_chat(app_client, env)
    await sweep_once(datetime.now(UTC))
    fake = {**GOOD_DRAFT, "claims": [{"value": 1_900_000, "source_id": "KH01"}],
            "text": "Chào chị, khóa IELTS đang giá 1.900.000đ, chị đăng ký không ạ?"}
    gw, _ = catalog_then_draft(fake)
    await run_pending(datetime.now(UTC), gw)
    (run,) = await rows_for(env, m.TriggerRun)
    (draft,) = await rows_for(env, m.Draft)
    assert run.status == "blocked" and "UNVERIFIED_CLAIM" in run.blocked_codes
    assert draft.status == "blocked"
    assert (await app_client.get("/review/drafts", headers=hdr(env.staff_key))).json()["drafts"] == []


# --- PII never reaches the model ---------------------------------------------------------------------------
async def test_pii_not_sent_to_llm(app_client, env):
    await ingest_price_chat(app_client, env)
    await sweep_once(datetime.now(UTC))
    gw, prov = catalog_then_draft()
    await run_pending(datetime.now(UTC), gw)
    assert len(prov.calls) == 2
    sent = json.dumps([c["messages"] for c in prov.calls], ensure_ascii=False)
    assert "Khóa IELTS giá bao nhiêu" in sent  # the conversation itself is there ...
    for piece in CUSTOMER_PII:
        assert piece not in sent, f"{piece!r} leaked to the LLM"
