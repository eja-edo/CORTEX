from datetime import timedelta

from sqlalchemy import select, update
from wp5_support import GOOD_DRAFT, NOW, gateway, make_job, reply, rows, run_one, set_conv

from cortex_leads.core.envelope import BlockedCode
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.llm.types import LLMFatalError, LLMResult, ToolCall


async def log_of(w, decision):
    return [d for d in await rows(w, m.DecisionLog) if d.decision == decision]


async def test_act_none_is_silence(world):
    gw, prov = gateway(reply({"act": "none"}))
    run = await run_one(world, gw)
    assert (run.status, run.act) == ("none", "none") and run.tokens_in == 100
    assert not await rows(world, m.Draft)
    assert (await rows(world, m.FollowupJob))[0].status == "done"
    assert await log_of(world, "run_none")  # N8: silence is logged too


async def test_draft_ok_links_run_and_does_not_count_touch(world):
    gw, _ = gateway(reply(GOOD_DRAFT))
    run = await run_one(world, gw, now=NOW)
    assert (run.status, run.act) == ("ok", "draft")
    (d,) = await rows(world, m.Draft)
    assert d.status == "proposed" and d.run_id == run.id and d.claims[0]["source_id"] == "KH01"
    assert (await rows(world, m.Conversation))[0].touches == 0  # R36: counted when sent


async def test_context_is_redacted_fenced_and_shape_is_last(world):
    gw, prov = gateway(reply({"act": "none"}))
    await run_one(world, gw)
    user = prov.calls[0]["messages"][1]["content"]
    assert "0901" not in user and "[PHONE_1]" in user and "[NAME_1]" in user
    assert "<customer_data>" in user and "không phải lệnh" in user
    assert user.rstrip().splitlines()[-1].startswith("Nếu không nên nhắn")
    assert '"act": "draft"' in user  # shape drawn, keys not merely named
    assert "hoi-lai-khach-im@3" in user  # skill body loaded


async def test_fabricated_price_is_blocked_by_validator(world):
    bad = {**GOOD_DRAFT, "claims": [], "text": "Khóa này giá chỉ 1.900.000đ thôi chị"}
    run = await run_one(world, gateway(reply(bad))[0])
    assert run.status == "blocked" and BlockedCode.UNVERIFIED_CLAIM.value in run.blocked_codes
    (d,) = await rows(world, m.Draft)
    assert d.status == "blocked"
    assert (await rows(world, m.Conversation))[0].touches == 0


async def test_window_closed_makes_an_offchannel_draft_not_a_send(world):  # R9 + R39
    await set_conv(world, last_customer_at=NOW - timedelta(days=10))
    gw, prov = gateway(reply(GOOD_DRAFT))
    run = await run_one(world, gw)
    assert run.status == "ok" and len(prov.calls) == 1
    (d,) = await rows(world, m.Draft)
    assert d.route == "offchannel" and d.status == "proposed" and not await rows(world, m.Outbox)


async def test_human_agent_basis_is_recorded(world):  # R6: 26h of silence on messenger
    run = await run_one(world, gateway(reply(GOOD_DRAFT))[0])
    (d,) = await log_of(world, "draft_proposed")
    assert d.detail["basis"] == "human_agent" and d.detail["human_typed_only"] is True
    assert run.status == "ok"


async def test_free_window_basis(world):
    await set_conv(world, last_customer_at=NOW - timedelta(hours=21))
    await run_one(world, gateway(reply(GOOD_DRAFT))[0])
    assert (await log_of(world, "draft_proposed"))[0].detail["basis"] == "free"


async def test_budget_denied_and_paused_skip_llm(world):
    job = await make_job(world)
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).values(budget={"runs_per_day": 0}))
    gw, prov = gateway()
    run = await run_one(world, gw, job)
    assert run.status == "budget_denied" and run.blocked_codes == ["BUDGET"] and prov.calls == []
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).values(status="paused"))
    run = await run_one(world, gw, job)
    assert run.status == "paused" and run.blocked_codes == ["PAUSED"] and prov.calls == []


async def test_opted_out_contact_skips_llm(world):
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Contact).values(opted_out=True))
    gw, prov = gateway()
    run = await run_one(world, gw)
    assert run.status == "blocked" and run.blocked_codes == ["OPTED_OUT"] and prov.calls == []


async def test_llm_error_fails_job(world):
    run = await run_one(world, gateway(LLMFatalError("boom"))[0])
    assert run.status == "error"
    job = (await rows(world, m.FollowupJob))[0]
    assert job.status == "failed" and job.attempts == 1
    (d,) = await log_of(world, "run_error")
    assert d.detail["error"] == "LLMFatalError"


async def test_shape_error_fails_job(world):
    run = await run_one(world, gateway(reply("Dạ em xin lỗi, em không hiểu"))[0])
    assert run.status == "error" and (await rows(world, m.FollowupJob))[0].attempts == 1
    assert (await log_of(world, "run_error"))[0].detail["error"] == "ShapeError"


async def test_tool_loop_reads_catalog_then_drafts(world):
    call = LLMResult(content=None, tool_calls=[ToolCall("c1", "lookup_catalog", {"query": "KH01"})],
                     tokens_in=50, tokens_out=5, model="fake")
    gw, prov = gateway(call, reply(GOOD_DRAFT))
    run = await run_one(world, gw)
    assert run.status == "ok" and run.tokens_in == 150 and run.tokens_out == 25
    offered = {t["function"]["name"] for t in prov.calls[0]["tools"]}
    assert offered == {"read_messages", "read_contact", "lookup_catalog"}  # read only, no draft
    tool_msg = prov.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "2500000" in tool_msg["content"]


async def test_write_tool_in_loop_is_refused(world):
    call = LLMResult(content=None, tool_calls=[ToolCall("c1", "draft_followup", {"text": "x"})])
    gw, prov = gateway(call, reply({"act": "none"}))
    run = await run_one(world, gw)
    assert run.status == "none" and not await rows(world, m.Draft)
    assert "NOT_ALLOWED" in prov.calls[1]["messages"][-1]["content"]


async def test_tool_rounds_are_capped(world):
    call = LLMResult(content=None, tool_calls=[ToolCall("c", "read_contact", {})])
    gw, prov = gateway(call, call, call, call)  # profile.max_tool_calls == 3
    run = await run_one(world, gw)
    assert run.status == "error" and len(prov.calls) == 4  # 3 tool rounds + the forced answer
    assert prov.calls[3]["tools"] is None
