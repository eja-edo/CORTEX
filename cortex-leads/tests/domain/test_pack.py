"""Domain pack (DESIGN A6) and the wave-2 schema (supervisor views, CHECKs)."""
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from cortex_leads.core.context import CustomerPrincipal, RunContext, Scope
from cortex_leads.core.vocabulary import CORE_FACT_KINDS, EVENT_TYPES
from cortex_leads.db import models as m
from cortex_leads.db.session import supervisor_session, tenant_session
from cortex_leads.domain.pack import DomainPackError, load_pack, load_pack_file, parse_pack
from cortex_leads.ingest.signing import sign
from cortex_leads.skills.loader import lint, parse_skill_md
from cortex_leads.skills.profile import load_profile
from cortex_leads.tools.registry import default_registry

CARE = Path(__file__).resolve().parents[2] / "sandboxes" / "customer_care"
PACK = load_pack_file(CARE / "domain.yaml")


def make_ctx(t, sb, conv) -> RunContext:
    return RunContext(run_id=uuid4(), tenant_id=t.id, sandbox_id=sb.id, profile="customer_drafter",
                      profile_version=1, principal=CustomerPrincipal(contact_id=conv.contact_id),
                      scope=Scope(conversation_id=conv.id))


async def call(t, ctx, name, args):
    async with tenant_session(t.id) as s:
        return await default_registry().execute(ctx, s, name, args, allowlist=[name],
                                                effect_ceiling="internal")


def test_shipped_pack_loads_and_vocabulary_is_structural():
    assert set(PACK.intents) == {"hoi_gia", "hoi_lich"} and len(PACK.reason_codes) == 6
    assert PACK.all_fact_kinds == CORE_FACT_KINDS | {
        "decision_maker", "need", "budget", "objection", "preference",
        "goal", "current_level", "study_time", "deadline"}
    assert {"conversation.silent", "conversation.promised_date_reached"} <= EVENT_TYPES
    assert not any(e.startswith("lead.") for e in EVENT_TYPES)


@pytest.mark.parametrize("msg,intent", [
    ("Học phí bao nhiêu vậy shop?", "hoi_gia"), ("HOC PHI khoa nay", "hoi_gia"),
    ("giá?", "hoi_gia"), ("Khi nào khai giảng ạ", "hoi_lich"),
    ("cảm ơn shop", None), ("giáo viên là ai", None), ("", None)])
def test_match_intent_whole_word_no_diacritics_case_insensitive(msg, intent):
    assert PACK.match_intent(msg) == intent


def test_empty_pack_is_valid_and_matches_nothing():
    pack = load_pack(SimpleNamespace(domain_pack={}))
    assert pack.match_intent("giá bao nhiêu") is None and pack.reason_codes == []


@pytest.mark.parametrize("bad", [
    {"intents": {"x": {"keywords": ["a"]}}},  # label missing
    {"intents": [], "reason_codes": "so_sanh"},
    {"outcome_keywords": {"maybe": ["x"]}},
    {"surprise": 1}])
def test_malformed_pack_is_a_clear_error(bad):
    with pytest.raises(DomainPackError, match="invalid domain pack"):
        parse_pack(bad)
    with pytest.raises(DomainPackError, match="not found"):
        load_pack_file(CARE / "nope.yaml")


def test_lint_checks_intent_against_the_pack():
    manifest, _ = parse_skill_md(CARE / "skills" / "hoi-lai-khach-im" / "SKILL.md")
    profile = load_profile("customer_drafter@1")
    assert lint(manifest, profile, PACK) == []
    assert any("domain pack" in e for e in lint(manifest, profile, parse_pack({})))


async def test_draft_reason_code_follows_the_pack(tenant_factory, sandbox_factory, connector_factory,
                                                  conversation_factory):
    t = await tenant_factory()
    sb = await sandbox_factory(t, domain_pack={"reason_codes": ["moi_la"]})
    conv = await conversation_factory(await connector_factory(sb))
    args = {"text": "Chào chị ạ", "has_new_info": True}
    ctx = make_ctx(t, sb, conv)
    r = await call(t, ctx, "draft_followup", {**args, "reason_code": "soc_gia"})
    assert r.error.fields == ["reason_code"]  # valid in customer_care, unknown to this pack
    assert (await call(t, ctx, "draft_followup", {**args, "reason_code": "moi_la"})).status == "proposed"
    bare = await sandbox_factory(t, name="bare", domain_pack={})
    conv2 = await conversation_factory(await connector_factory(bare), external_id="c2")
    r = await call(t, make_ctx(t, bare, conv2), "draft_followup", {**args, "reason_code": "khong_ro"})
    assert r.error.fields == ["reason_code"]


async def _send(client, connector, text_, ext):
    body = json.dumps({"format": "cortex.event/1", "events": [{
        "type": "message.created", "external_id": ext, "occurred_at": datetime.now(UTC).isoformat(),
        "channel": {"kind": "messenger", "account_ref": "p1"}, "conversation": {"external_id": ext},
        "contact": {"external_id": ext}, "sender": {"role": "customer"}, "text": text_}]}).encode()
    ts = int(time.time())
    r = await client.post("/ingest/v1/events", content=body, headers={
        "X-Connector-Id": connector.id, "X-Timestamp": str(ts),
        "X-Signature": sign(b"test-connector-secret", ts, body), "Content-Type": "application/json"})
    assert r.json()["results"][0]["status"] == "accepted"


async def _intent(tenant, ext):
    async with tenant_session(tenant.id) as s:
        return (await s.execute(select(m.Conversation.intent).where(
            m.Conversation.external_id == ext))).scalar_one()


async def test_changing_the_pack_changes_intent_without_code(app_client, tenant_factory, sandbox_factory,
                                                             connector_factory):
    t = await tenant_factory()
    sb = await sandbox_factory(t, domain_pack={"intents": {"hoi_xe": {"label": "Hỏi xe", "keywords": ["xe máy"]}}})
    bare = await sandbox_factory(t, name="bare", domain_pack={})
    c, cb = await connector_factory(sb), await connector_factory(bare)
    await _send(app_client, c, "Giá xe máy này?", "a")
    await _send(app_client, cb, "Giá xe máy này?", "b")
    assert await _intent(t, "a") == "hoi_xe"  # the shipped customer_care words are not in the core
    assert await _intent(t, "b") is None  # empty pack: no intent, no error


async def test_supervisor_reads_new_views_but_not_text_columns(tenant_factory, sandbox_factory,
                                                              connector_factory, conversation_factory,
                                                              seed):
    t = await tenant_factory()
    cn = await connector_factory(await sandbox_factory(t))
    conv = await conversation_factory(cn)
    await seed(m.ContactFact(tenant_id=t.id, contact_id=conv.contact_id, kind="need",
                             value="bí mật 0901234567", source="ai", status="active"))
    await seed(m.Deal(tenant_id=t.id, connector_id=cn.id, external_id="d1", status="won",
                      value=100, occurred_at=datetime.now(UTC)))
    await seed(m.Outbox(tenant_id=t.id, action_id=uuid4(), conversation_id=conv.id, connector_id=cn.id,
                        actor="staff:s1", text="Nội dung gửi khách", status="queued"))
    async with supervisor_session(t.id) as s:
        assert (await s.execute(text("select kind, source, status from supervisor_fact_view"))).one() \
            == ("need", "ai", "active")
        assert (await s.execute(text("select status, currency, linked from supervisor_deal_view"))).one() \
            == ("won", "VND", False)
        assert (await s.execute(text("select actor_kind, status from supervisor_outbox_view"))).one() \
            == ("staff", "queued")
        for q in ("select value from contact_fact", "select text from outbox", "select * from outbox",
                  "select external_id from deal"):
            with pytest.raises(DBAPIError):
                async with s.begin_nested():
                    await s.execute(text(q))
    async with supervisor_session(uuid4()) as s:  # another tenant sees nothing (RLS via invoker view)
        assert (await s.execute(text("select count(*) from supervisor_outbox_view"))).scalar_one() == 0


async def test_new_tables_are_tenant_isolated_and_checked(tenant_factory, sandbox_factory,
                                                          connector_factory, conversation_factory):
    a, b = await tenant_factory("A"), await tenant_factory("B")
    cn = await connector_factory(await sandbox_factory(a))
    conv = await conversation_factory(cn)
    async with tenant_session(a.id) as s:
        s.add(m.Deal(tenant_id=a.id, connector_id=cn.id, external_id="d", status="booked",
                     occurred_at=datetime.now(UTC)))
    async with tenant_session(b.id) as s:
        assert (await s.execute(select(m.Deal))).first() is None
        with pytest.raises(DBAPIError):  # WITH CHECK: cannot write another tenant's row
            s.add(m.Deal(tenant_id=a.id, connector_id=cn.id, external_id="x", status="won",
                         occurred_at=datetime.now(UTC)))
            await s.flush()
    for row in (m.Deal(tenant_id=a.id, connector_id=cn.id, external_id="y", status="maybe",
                       occurred_at=datetime.now(UTC)),
                m.ContactFact(tenant_id=a.id, contact_id=conv.contact_id, kind="k", value=1, status="x")):
        with pytest.raises(DBAPIError):
            async with tenant_session(a.id) as s:
                s.add(row)
    async with tenant_session(a.id) as s:  # new states are accepted
        (await s.get(m.Conversation, conv.id)).state = "booked"


def test_reason_codes_accept_list_and_labelled_dict():
    plain = parse_pack({"reason_codes": ["a", "b"]})
    assert "a" in plain.reason_codes and plain.reason_label("a") == "a"
    labelled = parse_pack({"reason_codes": {"a": "Nhãn A"}})
    assert "a" in labelled.reason_codes and "b" not in labelled.reason_codes
    assert labelled.reason_label("a") == "Nhãn A" and labelled.reason_label("zz") == "zz"
    assert PACK.reason_label("soc_gia") == "Có thể sốc giá"


@pytest.mark.parametrize(("text", "outcome"), [
    ("Mình đăng ký rồi nhé", "won"), ("em chuyển khoản rồi ạ", "won"), ("Mình đã đăng ký", "won"),
    ("em đặt lịch rồi", "booked"), ("chị chưa đăng ký đâu", None), ("khoá này giá bao nhiêu", None),
])
def test_shipped_pack_reads_how_people_say_it_is_done(text, outcome):
    assert PACK.match_outcome(text) == outcome
