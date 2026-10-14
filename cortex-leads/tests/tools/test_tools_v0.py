from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from cortex_leads.core.context import CustomerPrincipal, RunContext, Scope, StaffPrincipal
from cortex_leads.core.envelope import BlockedCode, ErrorCode, ToolResult
from cortex_leads.core.errors import CortexError, TenantScopeError
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.tools.refs import resolve
from cortex_leads.tools.registry import ToolRegistry, ToolSpec, default_registry

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
ALL = ["read_messages", "read_contact", "lookup_catalog", "list_dropped_leads", "draft_followup"]
reg = default_registry(clock=lambda: NOW)


def make_ctx(tenant, sandbox, conv=None, principal=None) -> RunContext:
    return RunContext(
        run_id=uuid4(), tenant_id=tenant.id, sandbox_id=sandbox.id, profile="customer_drafter",
        profile_version=1, principal=principal or CustomerPrincipal(contact_id=uuid4()),
        scope=Scope(conversation_id=conv.id if conv else None))


@pytest.fixture
async def world(tenant_factory, sandbox_factory, connector_factory, conversation_factory,
                message_factory, catalog_factory):
    t = await tenant_factory()
    sb = await sandbox_factory(t)
    cn = await connector_factory(sb)
    conv = await conversation_factory(cn, display_name="Nguyễn Văn An", intent="hoi_gia")
    await message_factory(conv, "Em là Nguyễn Văn An, sđt 0901 234 567, mail an@x.vn. Giá sao?",
                          occurred_at=NOW - timedelta(hours=30))
    await catalog_factory(t, code="KH01", name="Khóa IELTS", price=2_500_000)
    return t, sb, cn, conv


async def call(t, ctx, name, args, *, allow=ALL, ceiling="internal", **kw) -> ToolResult:
    async with tenant_session(t.id) as s:
        return await reg.execute(ctx, s, name, args, allowlist=allow, effect_ceiling=ceiling, **kw)


async def test_not_allowed_and_effect_ceiling(world):
    t, sb, _, conv = world
    ctx = make_ctx(t, sb, conv)
    r = await call(t, ctx, "read_contact", {}, allow=["read_messages"])
    assert r.status == "blocked" and r.violations[0].code == BlockedCode.NOT_ALLOWED
    r = await call(t, ctx, "draft_followup", {}, ceiling="read")
    assert r.violations[0].code == BlockedCode.EFFECT_CEILING


async def test_invalid_args_lists_fields_and_forbids_scope_args(world):
    t, sb, _, conv = world
    ctx = make_ctx(t, sb, conv)
    r = await call(t, ctx, "read_messages", {"last_n": 99})
    assert r.status == "error" and r.error.code == ErrorCode.INVALID_ARGS
    assert r.error.fields == ["last_n"] and r.error.retryable
    # A3: tenant / conversation can never come from args
    r = await call(t, ctx, "read_messages", {"tenant_id": str(uuid4()), "conversation_id": "x"})
    assert r.error.code == ErrorCode.INVALID_ARGS
    assert set(r.error.fields) == {"tenant_id", "conversation_id"}


async def test_read_messages_is_redacted(world):
    t, sb, _, conv = world
    r = await call(t, make_ctx(t, sb, conv), "read_messages", {})
    body = r.data["messages"][0]["text"]
    assert r.status == "ok"
    for leak in ("0901", "an@x.vn", "Nguyễn Văn An"):
        assert leak not in body
    assert "[PHONE_1]" in body and "[EMAIL_1]" in body and "[NAME_1]" in body


async def test_scope_comes_from_context_only(world, conversation_factory, message_factory):
    t, sb, cn, conv = world
    other = await conversation_factory(cn, external_id="conv-2")
    await message_factory(other, "tin của hội thoại khác")
    r = await call(t, make_ctx(t, sb, conv), "read_messages", {"last_n": 30})
    assert [x["text"] for x in r.data["messages"]] != ["tin của hội thoại khác"]
    assert len(r.data["messages"]) == 1
    r = await call(t, make_ctx(t, sb, None), "read_messages", {})
    assert r.error.code == ErrorCode.PERMISSION_DENIED
    # a conversation of another sandbox is invisible even inside the same tenant
    r = await call(t, make_ctx(t, type("S", (), {"id": uuid4()})(), conv), "read_messages", {})
    assert r.status == "not_found"


async def test_rls_other_tenant_sees_nothing(world, tenant_factory, sandbox_factory):
    t, sb, _, conv = world
    t2 = await tenant_factory(name="Other")
    sb2 = await sandbox_factory(t2)
    ctx = make_ctx(t2, sb2, conv)  # B's context pointing at A's conversation
    for name in ("read_messages", "read_contact"):
        assert (await call(t2, ctx, name, {})).status == "not_found"
    r = await call(t2, ctx, "draft_followup", {"text": "hi", "reason_code": "khong_ro",
                                               "has_new_info": True})
    assert r.status == "not_found"
    r = await call(t2, make_ctx(t2, sb2), "lookup_catalog", {"query": "KH01"})
    assert r.status == "not_found" and r.data["options"] == []
    # session scoped to B while ctx says A -> refuse outright
    with pytest.raises(TenantScopeError):
        await call(t2, make_ctx(t, sb, conv), "read_messages", {})


async def test_read_contact_has_no_pii(world):
    t, sb, _, conv = world
    r = await call(t, make_ctx(t, sb, conv), "read_contact", {})
    assert r.data["intent"] == "hoi_gia" and "display_name" not in r.data and "phone" not in r.data


async def test_empty_result_gets_note(world, conversation_factory, connector_factory):
    t, sb, cn, _ = world
    empty = await conversation_factory(cn, external_id="empty")
    r = await call(t, make_ctx(t, sb, empty), "read_messages", {})
    assert r.status == "ok" and r.data == {"messages": []}
    assert r.note


async def test_lookup_catalog_branches(world, catalog_factory):
    t, sb, _, conv = world
    await catalog_factory(t, code="KH02", name="Khóa IELTS Nâng cao", price=3_000_000)
    await catalog_factory(t, code="OLD", name="Khóa cũ", active=False)
    await catalog_factory(t, code="EXP", name="Khóa hết hạn", valid_until=NOW - timedelta(days=1))
    ctx = make_ctx(t, sb, conv)
    r = await call(t, ctx, "lookup_catalog", {"query": "kh01"})
    assert r.status == "ok" and r.data["items"][0]["price"] == 2_500_000
    r = await call(t, ctx, "lookup_catalog", {"query": "ielts"})
    assert r.status == "ambiguous" and len(r.data["options"]) == 2
    r = await call(t, ctx, "lookup_catalog", {"query": "toeic"})
    assert r.status == "not_found" and r.note and {o["code"] for o in r.data["options"]} == {"KH01", "KH02"}
    r = await call(t, ctx, "lookup_catalog", {"query": "Khóa cũ"})
    assert r.status == "not_found"


async def test_list_dropped_leads(world, conversation_factory, seed):
    t, sb, cn, conv = world
    async with tenant_session(t.id) as s:
        c = await s.get(m.Conversation, conv.id)
        c.last_customer_at = NOW - timedelta(hours=30)
    fresh = await conversation_factory(cn, external_id="fresh", last_customer_at=NOW - timedelta(hours=1))
    answered = await conversation_factory(cn, external_id="ans", last_customer_at=NOW - timedelta(hours=40),
                                          last_staff_at=NOW - timedelta(hours=39))
    r = await call(t, make_ctx(t, sb), "list_dropped_leads", {})
    ids = [x["conversation_id"] for x in r.data["leads"]]
    assert ids == [str(conv.id)] and r.data["leads"][0]["silent_hours"] == 30
    assert str(fresh.id) not in ids and str(answered.id) not in ids
    r = await call(t, make_ctx(t, sb), "list_dropped_leads", {"silent_hours": 100})
    assert r.data["leads"] == [] and r.note
    assert (await call(t, make_ctx(t, sb), "list_dropped_leads", {"limit": 21})).error.code == \
        ErrorCode.INVALID_ARGS


async def test_draft_ok_is_proposed_without_touch_and_audits(world):
    t, sb, _, conv = world
    ctx = make_ctx(t, sb, conv)
    args = {"text": "Khóa IELTS giá 2,5 triệu ạ, chị cần tư vấn thêm không?", "reason_code": "soc_gia",
            "has_new_info": True, "claims": [{"value": 2_500_000, "source_id": "KH01"}]}
    r = await call(t, ctx, "draft_followup", args)
    assert r.status == "proposed" and r.action_id
    async with tenant_session(t.id) as s:
        d = (await s.execute(select(m.Draft))).scalar_one()
        assert d.status == "proposed" and d.conversation_id == conv.id
        assert (await s.get(m.Conversation, conv.id)).touches == 0  # R36
        log = (await s.execute(select(m.ActionLog))).scalar_one()
        assert log.tool == "draft_followup" and log.actor == "ai:customer_drafter@1"
        assert log.args_masked["text"] == "[REDACTED]" and log.status == "proposed"


async def test_invented_price_saves_blocked_draft(world):
    t, sb, _, conv = world
    r = await call(t, make_ctx(t, sb, conv), "draft_followup", {
        "text": "Chỉ 1.000.000đ thôi ạ", "reason_code": "soc_gia", "has_new_info": True,
        "claims": [{"value": 1_000_000, "source_id": "KH01"}]})
    assert r.status == "blocked"
    assert {v.code for v in r.violations} == {BlockedCode.UNVERIFIED_CLAIM}
    async with tenant_session(t.id) as s:
        assert (await s.execute(select(m.Draft.status))).scalars().all() == ["blocked"]
        assert (await s.get(m.Conversation, conv.id)).touches == 0


async def test_citing_a_row_vouches_only_for_that_rows_numbers(world, catalog_factory):
    t, sb, _, conv = world  # seen with a real model: right numbers, one claim of three forgotten
    await catalog_factory(t, code="KH03", name="IELTS 3 tháng", price=2_500_000,
                          attrs={"khai_giang": "24/10", "so_buoi_thi_thu": 2, "thoi_luong_thang": 3})
    ok = {"text": "Khoá IELTS 3 tháng 2.500.000đ, khai giảng 24/10, gồm 2 buổi thi thử ạ", "reason_code": "soc_gia",
          "has_new_info": True, "claims": [{"value": "24/10", "source_id": "KH03"}]}
    assert (await call(t, make_ctx(t, sb, conv), "draft_followup", ok)).status == "proposed"
    bad = {**ok, "text": "Khoá IELTS 4 tháng 2.900.000đ, khai giảng 25/10 ạ"}
    r = await call(t, make_ctx(t, sb, conv), "draft_followup", bad)
    assert r.status == "blocked" and {v.span for v in r.violations} >= {"25/10", "2.900.000đ"}


async def test_draft_blocked_by_touch_optout_phrase_and_no_info(world):
    t, sb, _, conv = world
    base = {"text": "Chào chị, em hỏi lại ạ", "reason_code": "khong_ro", "has_new_info": True}
    ctx = make_ctx(t, sb, conv)
    r = await call(t, ctx, "draft_followup", {**base, "never_say": ["hỏi lại"], "has_new_info": False})
    assert {v.code for v in r.violations} == {BlockedCode.FORBIDDEN_PHRASE, BlockedCode.NO_NEW_INFO}
    assert (await call(t, ctx, "draft_followup", base)).status == "proposed"
    async with tenant_session(t.id) as s:
        (await s.get(m.Conversation, conv.id)).touches = 1  # one message already went out
    r = await call(t, ctx, "draft_followup", {**base, "max_touches": 1})
    assert [v.code for v in r.violations] == [BlockedCode.TOUCH_LIMIT]
    async with tenant_session(t.id) as s:
        (await s.get(m.Contact, conv.contact_id)).opted_out = True
    r = await call(t, ctx, "draft_followup", base)
    assert BlockedCode.OPTED_OUT in {v.code for v in r.violations}


async def test_idempotency_key_replays(world):
    t, sb, _, conv = world
    ctx = make_ctx(t, sb, conv)
    args = {"text": "Chào chị", "reason_code": "khong_ro", "has_new_info": True}
    a = await call(t, ctx, "draft_followup", args, idempotency_key="k1")
    b = await call(t, ctx, "draft_followup", args, idempotency_key="k1")
    assert not a.replayed and b.replayed and a.action_id == b.action_id
    async with tenant_session(t.id) as s:
        assert len((await s.execute(select(m.Draft))).scalars().all()) == 1


async def test_draft_bad_reason_code_is_invalid_args(world):
    t, sb, _, conv = world
    r = await call(t, make_ctx(t, sb, conv), "draft_followup",
                   {"text": "x", "reason_code": "bịa", "has_new_info": True})
    assert r.error.fields == ["reason_code"]


async def test_staff_actor_in_audit(world):
    t, sb, _, conv = world
    ctx = make_ctx(t, sb, conv, principal=StaffPrincipal(staff_ref="s1"))
    await call(t, ctx, "draft_followup", {"text": "Chào", "reason_code": "khong_ro", "has_new_info": True})
    async with tenant_session(t.id) as s:
        assert (await s.execute(select(m.ActionLog.actor))).scalar_one() == "staff:s1"


async def test_read_tools_are_not_audited(world):
    t, sb, _, conv = world
    await call(t, make_ctx(t, sb, conv), "read_messages", {})
    async with tenant_session(t.id) as s:
        assert (await s.execute(select(m.ActionLog))).first() is None


# --- registry invariants (no DB) ---
class _A(BaseModel):
    pass


async def _h(ctx, s, a):
    return ToolResult(status="ok", data=1)


def test_only_send_message_may_have_customer_effect():
    reg = ToolRegistry()
    with pytest.raises(CortexError):
        reg.register(ToolSpec("push_sms", "Gửi tin.", _A, "customer", "v0", _h))
    reg.register(ToolSpec("send_message", "Gửi tin.", _A, "customer", "v0", _h))


def test_descriptions_at_most_two_sentences():
    r = default_registry()
    specs = r.specs_for(ALL)
    assert {s.name for s in specs} == set(ALL)
    for s in specs:
        assert len([x for x in s.description.replace("?", ".").split(".") if x.strip()]) <= 2
    with pytest.raises(CortexError):
        r.register(ToolSpec("wordy", "Một. Hai. Ba.", _A, "read", "v0", _h))
    assert {x["function"]["name"] for x in r.openai_schemas(["read_messages"])} == {"read_messages"}


def test_send_message_is_the_only_customer_tool_in_default_registry():
    reg = default_registry()
    assert [s.name for s in reg._tools.values() if s.effect == "customer"] == ["send_message"]


def test_refs_resolve():
    c = ["Alpha", "Alpha v2", "Beta"]
    assert resolve(c, "alpha").match == "Alpha"  # exact beats contains
    assert resolve(c, "alph").status == "ambiguous"
    assert resolve(c, "alpah").status == "not_found"  # no fuzzy
    assert resolve(c, "alpah").options == c
    assert resolve(c, "beta").match == "Beta"


async def test_list_dropped_leads_skips_offchannel_and_closed(world, conversation_factory):  # R32
    t, sb, cn, _ = world
    kw = {"last_customer_at": NOW - timedelta(hours=40)}
    off = await conversation_factory(cn, external_id="off", offchannel_contact=True, **kw)
    won = await conversation_factory(cn, external_id="won", state="won", **kw)
    r = await call(t, make_ctx(t, sb), "list_dropped_leads", {})
    ids = {x["conversation_id"] for x in r.data["leads"]}
    assert str(off.id) not in ids and str(won.id) not in ids


async def test_naming_a_course_cites_it(world, catalog_factory):
    t, sb, _, conv = world  # seen live: "giữ chỗ khoá IELTS 3 tháng ... đặt cọc 500.000đ" citing only TT-DANGKY
    await catalog_factory(t, code="IE-3T", name="IELTS 3 tháng (4.5 lên 5.5)", price=4_500_000,
                          attrs={"thoi_luong_thang": 3})
    await catalog_factory(t, code="TT-DANGKY", name="Cách đăng ký", attrs={"dat_coc": 500_000})
    args = {"text": "Dạ khoá IELTS 3 tháng mình đặt cọc 500.000đ ạ", "reason_code": "soc_gia", "has_new_info": True,
            "claims": [{"value": 500_000, "source_id": "TT-DANGKY"}]}
    assert (await call(t, make_ctx(t, sb, conv), "draft_followup", args)).status == "proposed"
    bad = {**args, "text": "Dạ khoá IELTS 3 tháng chỉ 4 tháng thôi ạ"}  # a number on no row still blocks
    assert (await call(t, make_ctx(t, sb, conv), "draft_followup", bad)).status == "blocked"
