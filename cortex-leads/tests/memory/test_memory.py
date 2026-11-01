from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from wp5_support import GOOD_DRAFT, NOW, REG, gateway, make_job, reply, rows, run_one, set_conv

from cortex_leads.core.context import CustomerPrincipal, RunContext, Scope
from cortex_leads.db import models as m
from cortex_leads.db.session import supervisor_session, tenant_session
from cortex_leads.guard.facts import extract_date_candidates
from cortex_leads.ingest.format import Event
from cortex_leads.ingest.normalize import apply_event
from cortex_leads.memory import service as mem
from cortex_leads.triggers.engine import on_conversation_event

TZ = "Asia/Ho_Chi_Minh"  # NOW is Monday 2026-10-12 10:00 local


async def add_msg(w, message_factory, text_, role="customer", conv=None):
    msg = await message_factory(conv or w.conv, text_, sender_role=role, occurred_at=NOW)
    return msg.id


async def conv_of(w):
    async with tenant_session(w.t.id) as s:
        return await s.get(m.Conversation, w.conv.id)


async def fact(w, **kw):
    kw.setdefault("evidence_msg_ids", [])
    kw.setdefault("source", "staff:s1")
    async with tenant_session(w.t.id) as s:
        return await mem.record_fact(s, conversation_id=w.conv.id, now=NOW, **kw)


def test_date_phrases():
    f = lambda t: extract_date_candidates(t, NOW, TZ)
    assert f("mình rảnh 15/10 nhé") == {date(2026, 10, 15)}
    assert f("ngày 20 mình qua") == {date(2026, 10, 20)}
    assert f("ngày mai") == {date(2026, 10, 13)} and f("ngày kia") == {date(2026, 10, 14)}
    assert f("thứ 6 tuần sau") == {date(2026, 10, 23)} and f("thứ sáu") == {date(2026, 10, 16)}
    assert f("cuối tuần") == {date(2026, 10, 17), date(2026, 10, 18)}
    assert len(f("tuần sau")) == 7 and min(f("tháng sau")) == date(2026, 11, 1)
    assert f("chị Mai bảo giá") == set() and f("sau Tết") == set()


async def test_sau_tet_candidate_then_staff_confirm_arms_clock(world, message_factory):
    mid = await add_msg(world, message_factory, "Để sau Tết mình bàn với chồng đã")
    dm = await fact(world, kind="decision_maker", value={"role": "vo_chong"},
                    evidence_msg_ids=[mid], source="ai:customer_drafter@1")
    pd = await fact(world, kind="promised_date", value={"date": "2027-02-10"},
                    evidence_msg_ids=[mid], source="ai:customer_drafter@1")
    assert (dm.status, pd.status) == ("active", "candidate")
    c = await conv_of(world)
    assert c.promised_date is None
    async with tenant_session(world.t.id) as s:
        assert [f.id for f in await mem.pending_confirmations(s, sandbox_id=world.sb.id)] == [pd.id]
        assert (await s.get(m.Contact, c.contact_id)).decision_maker == "vo_chong"
        await mem.confirm_fact(s, pd.id, staff_ref="s1", now=NOW)
    c = await conv_of(world)
    assert c.promised_date == date(2027, 2, 10) and c.next_check_at.date() == date(2027, 2, 10)


async def test_tuan_sau_is_verified_and_active(world, message_factory):
    mid = await add_msg(world, message_factory, "Tuần sau mình báo lại nhé")
    f = await fact(world, kind="promised_date", value={"date": "2026-10-19"},
                   evidence_msg_ids=[mid], source="ai:customer_drafter@1")
    assert f.status == "active" and (await conv_of(world)).promised_date == date(2026, 10, 19)


async def test_invented_date_rejected(world, message_factory):
    mid = await add_msg(world, message_factory, "Tuần sau mình báo lại nhé")
    with pytest.raises(mem.MemoryError) as e:
        await fact(world, kind="promised_date", value={"date": "2026-11-30"},
                   evidence_msg_ids=[mid], source="ai:x@1")
    assert e.value.code == "DATE_NOT_IN_EVIDENCE"
    with pytest.raises(mem.MemoryError) as e:
        await fact(world, kind="promised_date", value={"date": "2026-10-01"}, source="staff:s1")
    assert e.value.code == "DATE_OUT_OF_RANGE"


async def test_evidence_rules(world, message_factory, conversation_factory):
    staff_msg = await add_msg(world, message_factory, "Em gửi chị bảng giá", role="staff")
    other = await conversation_factory(world.cn, external_id="conv-2")
    foreign = await add_msg(world, message_factory, "tuần sau", conv=other)
    ok = await add_msg(world, message_factory, "mình cần học IELTS")
    for ev, code in (([], "NO_EVIDENCE"), ([staff_msg], "EVIDENCE_NOT_CUSTOMER"),
                     ([foreign], "EVIDENCE_OTHER_CONVERSATION")):
        with pytest.raises(mem.MemoryError) as e:
            await fact(world, kind="need", value={"x": 1}, evidence_msg_ids=ev, source="ai:x@1")
        assert e.value.code == code
    with pytest.raises(mem.MemoryError) as e:
        await fact(world, kind="bogus", value={"x": 1}, evidence_msg_ids=[ok], source="ai:x@1")
    assert e.value.code == "UNKNOWN_KIND"
    assert (await fact(world, kind="need", value={"x": 1}, evidence_msg_ids=[ok],
                       source="ai:x@1")).status == "active"


async def test_new_fact_supersedes_old_same_kind(world):
    a = await fact(world, kind="budget", value={"max": 1})
    b = await fact(world, kind="budget", value={"max": 2})
    async with tenant_session(world.t.id) as s:
        facts = await mem.list_facts(s, contact_id=(await conv_of(world)).contact_id, include_inactive=True)
    st = {f.id: f.status for f in facts}
    assert st[a.id] == "superseded" and st[b.id] == "active"


async def test_more_than_five_facts_blocked(world):
    ctx = RunContext(run_id=NOW and __import__("uuid").uuid4(), tenant_id=world.t.id, sandbox_id=world.sb.id,
                     profile="customer_drafter", profile_version=1,
                     principal=CustomerPrincipal(world.conv.contact_id),
                     scope=Scope(conversation_id=world.conv.id))
    async with tenant_session(world.t.id) as s:
        r = await REG.execute(ctx, s, "record_facts",
                              {"facts": [{"kind": "need", "value": {"n": i}} for i in range(6)]},
                              allowlist=["record_facts"], effect_ceiling="internal")
    assert r.status == "error" and r.note == "TOO_MANY_FACTS" and not await rows(world, m.ContactFact)


async def event(world, cid_ext="contact-conv-1", *, status="won", ext="e1", deal="d1", at=NOW):
    return Event.model_validate({
        "type": "deal.updated", "external_id": ext, "occurred_at": at.isoformat(),
        "contact": {"ref": {"connector_id": world.cn.id, "external_id": cid_ext}},
        "deal": {"external_id": deal, "status": status, "value": 5000000}})


async def test_deal_won_closes_promise_jobs_and_drafts(world, message_factory):
    mid = await add_msg(world, message_factory, "Tuần sau mình báo lại nhé")
    await fact(world, kind="promised_date", value={"date": "2026-10-19"}, evidence_msg_ids=[mid],
               source="ai:x@1")
    job = await make_job(world)
    async with tenant_session(world.t.id) as s:
        s.add(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id,
                      text="nháp", reason_code="khong_ro"))
    async with tenant_session(world.t.id) as s:
        assert await apply_event(s, world.cn, await event(world), NOW + timedelta(days=1)) == "accepted"
    c = await conv_of(world)
    assert c.state == "won" and c.next_check_at is None and c.promised_date is None
    assert [f.status for f in await rows(world, m.ContactFact) if f.kind == "promised_date"] == ["fulfilled"]
    assert {j.status for j in await rows(world, m.FollowupJob)} == {"skipped"} and job
    assert [d.status for d in await rows(world, m.Draft)] == ["expired"]
    assert any(d.decision == "promise_closed_by_outcome" for d in await rows(world, m.DecisionLog))


async def test_same_deal_won_lost_won_is_one_row(world):
    for i, st in enumerate(("won", "lost", "won")):
        async with tenant_session(world.t.id) as s:
            await apply_event(s, world.cn, await event(world, status=st, ext=f"e{i}"), NOW)
        assert (await conv_of(world)).state == st
    (d,) = await rows(world, m.Deal)
    assert d.status == "won" and d.linked and d.conversation_id == world.conv.id


async def test_unmatched_deal_is_stored_unlinked(world):
    async with tenant_session(world.t.id) as s:
        await apply_event(s, world.cn, await event(world, cid_ext="nobody"), NOW)
        await apply_event(s, world.cn, Event.model_validate({
            "type": "deal.updated", "external_id": "e9", "occurred_at": NOW.isoformat(),
            "contact": {"phone": "0999999999"}, "deal": {"external_id": "d2", "status": "won"}}), NOW)
    assert [d.linked for d in await rows(world, m.Deal)] == [False, False]
    assert (await conv_of(world)).state == "open"


async def test_rule_suggests_but_changes_nothing(world):
    async with tenant_session(world.t.id) as s:
        await apply_event(s, world.cn, Event.model_validate({
            "type": "message.created", "external_id": "x1", "occurred_at": NOW.isoformat(),
            "channel": {"kind": "messenger"}, "conversation": {"external_id": "conv-1"},
            "contact": {"external_id": "contact-conv-1"}, "sender": {"role": "customer"},
            "text": "Mình đã chuyển khoản rồi, tuần sau gặp"}), NOW)
    fs = {f.kind: f for f in await rows(world, m.ContactFact)}
    assert {k: f.status for k, f in fs.items()} == {"promised_date": "candidate", "outcome": "candidate"}
    assert fs["outcome"].source == "rule"
    c = await conv_of(world)
    assert c.state == "open" and c.promised_date is None


async def test_ai_outcome_candidate_stops_tracking_until_staff_decides(world, message_factory):
    mid = await add_msg(world, message_factory, "mình thôi nhé, không đăng ký")
    async with tenant_session(world.t.id) as s:
        c = await mem.record_outcome(s, conversation_id=world.conv.id, status="lost",
                                     source="ai:x@1", evidence_msg_ids=[mid], now=NOW)
        assert c.state == "open" and c.next_check_at is None
        (f,) = await mem.pending_confirmations(s, sandbox_id=world.sb.id)
    gw, prov = gateway()
    run = await run_one(world, gw, await make_job(world))
    assert run.status == "blocked" and prov.calls == []  # double stop: no LLM
    async with tenant_session(world.t.id) as s:
        await mem.reject_fact(s, f.id, staff_ref="s1", now=NOW)
    assert (await conv_of(world)).next_check_at is not None


async def test_staff_confirm_outcome_closes(world, message_factory):
    mid = await add_msg(world, message_factory, "mình đăng ký rồi")
    async with tenant_session(world.t.id) as s:
        await mem.record_outcome(s, conversation_id=world.conv.id, status="won",
                                 source="ai:x@1", evidence_msg_ids=[mid], now=NOW)
        (f,) = await mem.pending_confirmations(s, sandbox_id=world.sb.id)
        await mem.confirm_fact(s, f.id, staff_ref="s1", now=NOW)
    assert (await conv_of(world)).state == "won"


async def test_offchannel_leaves_the_dropped_list(world, message_factory):
    async with tenant_session(world.t.id) as s:
        f = await mem.mark_offchannel(s, conversation_id=world.conv.id, channel="phone",
                                      staff_ref="s1", now=NOW)
    c = await conv_of(world)
    assert f.status == "active" and c.offchannel_contact and c.next_check_at is None
    async with tenant_session(world.t.id) as s:  # a new customer message must not re-arm it
        await apply_event(s, world.cn, Event.model_validate({
            "type": "message.created", "external_id": "x2", "occurred_at": NOW.isoformat(),
            "channel": {"kind": "messenger"}, "conversation": {"external_id": "conv-1"},
            "contact": {"external_id": "contact-conv-1"}, "sender": {"role": "customer"},
            "text": "alo"}), NOW)
        assert (await s.get(m.Conversation, world.conv.id)).next_check_at is None
        assert await on_conversation_event(s, await s.get(m.Conversation, world.conv.id),
                                           "conversation.silent", NOW) == []


async def test_runner_records_facts_and_drops_draft_when_promise_is_future(world, message_factory):
    await add_msg(world, message_factory, "Tuần sau mình báo lại nhé")
    out = {**GOOD_DRAFT, "facts": [{"kind": "promised_date", "value": {"date": "2026-10-19"},
                                    "evidence": ["m2"]}]}
    gw, prov = gateway(reply(out))
    run = await run_one(world, gw)
    assert run.status == "none" and not await rows(world, m.Draft)
    assert "[m2 customer" in prov.calls[0]["messages"][1]["content"]
    assert (await conv_of(world)).promised_date == date(2026, 10, 19)
    d = [d for d in await rows(world, m.DecisionLog) if d.decision == "run_none"]
    assert d[0].detail["reason"] == "promised_future"
    await set_conv(world, last_customer_msg_id="m2")  # a new silence, new dedupe key
    gw2, prov2 = gateway()  # a later silence with a future promise never reaches the LLM
    run2 = await run_one(world, gw2, await make_job(world, "conversation.silent"))
    assert prov2.calls == [] and run2.status == "none"


async def test_runner_bad_evidence_label_is_rejected_not_fatal(world):
    gw, _ = gateway(reply({"act": "none", "facts": [
        {"kind": "need", "value": {"x": 1}, "evidence": ["m99"]}]}))
    run = await run_one(world, gw)
    assert run.status == "none" and not await rows(world, m.ContactFact)


async def test_rls_and_supervisor_view_hides_value(world, tenant_factory):
    await fact(world, kind="need", value={"secret": "0901234567"})
    other = await tenant_factory("Other")
    async with tenant_session(other.id) as s:
        assert (await s.execute(select(m.ContactFact))).first() is None
    async with supervisor_session(world.t.id) as s:
        r = (await s.execute(text("select * from supervisor_fact_view"))).mappings().all()
        assert r and "value" not in r[0] and "0901" not in str(r)
    with pytest.raises(DBAPIError):
        async with supervisor_session(world.t.id) as s:
            await s.execute(text("select value from contact_fact"))


async def test_staff_api_roundtrip(app_client, world, api_key_factory, message_factory):
    _, key = await api_key_factory(world.t, "staff", "s1")
    h = {"X-Api-Key": key}
    base = f"/review/conversations/{world.conv.id}"
    r = await app_client.post(f"{base}/facts", json={"kind": "need", "value": {"x": "ielts"}}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert len((await app_client.get(f"{base}/facts", headers=h)).json()["facts"]) == 1
    bad = await app_client.post(f"{base}/facts", json={"kind": "zzz", "value": {"a": 1}}, headers=h)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "UNKNOWN_KIND"
    assert (await app_client.post(f"{base}/offchannel", json={"channel": "phone"}, headers=h)).status_code == 200
    r = await app_client.post(f"{base}/outcome", json={"status": "won"}, headers=h)
    assert r.json() == {"state": "won"}
    assert (await app_client.get("/review/confirmations", headers=h)).json() == {"facts": []}
    _, sup = await api_key_factory(world.t, "supervisor", None)
    assert (await app_client.get(f"{base}/facts", headers={"X-Api-Key": sup})).status_code == 403


async def test_rule_outcome_candidate_never_blocks_the_runner(world, message_factory):  # R31
    mid = await add_msg(world, message_factory, "chị chưa chốt đâu")
    async with tenant_session(world.t.id) as s:
        await mem.record_outcome(s, conversation_id=world.conv.id, status="won",
                                 source="rule", evidence_msg_ids=[mid], now=NOW)
        assert not await mem.has_pending_outcome(s, world.conv.id)
    gw, prov = gateway(reply({"act": "none"}))
    await run_one(world, gw, await make_job(world))
    assert len(prov.calls) == 1


async def test_only_a_person_can_lift_an_opt_out(world):
    async with tenant_session(world.t.id) as s:
        await mem.opt_out(s, await s.get(m.Conversation, world.conv.id), source="rule", now=NOW)
    for who in ("ai:x@1", "rule"):
        async with tenant_session(world.t.id) as s:
            with pytest.raises(mem.MemoryError):
                await mem.opt_in(s, world.conv.id, source=who, now=NOW)
    async with tenant_session(world.t.id) as s:
        await mem.opt_in(s, world.conv.id, source="staff:s1", now=NOW)
    c = await conv_of(world)
    assert c.state == "open" and c.next_check_at is not None
