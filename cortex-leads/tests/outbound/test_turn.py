"""WP16 (DESIGN §5.7 `turn`): a customer who finished talking and got no answer is answered once."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from ob_support import URL, Bridge, sql
from sqlalchemy import select, update
from wp5_support import NOW, gateway, reply, rows

from cortex_leads.cli import worker_once
from cortex_leads.clock.sweeper import sweep_once
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.ingest.format import Event
from cortex_leads.ingest.normalize import apply_event
from cortex_leads.outbound.worker import deliver_once
from cortex_leads.runner.customer_run import run_pending
from cortex_leads.skills.manifest import parse_duration
from cortex_leads.skills.registry import promote
from cortex_leads.triggers.engine import STAFF_ACTIVE, on_conversation_event

HELLO = {"act": "reply", "reason_code": "khong_ro", "claims": [],
         "text": "Dạ em chào anh/chị ạ, mình đang quan tâm khoá nào bên em ạ?"}
OFF_HOURS = NOW + timedelta(hours=18)  # 04:00 in Vietnam: outside business_hours


@pytest.fixture
async def tw(world):
    async with tenant_session(world.t.id) as s:
        for st in ("shadow", "live"):
            await promote(s, world.sb.id, "tra-loi-khach", 16, st)
        await s.execute(update(m.Conversation).values(next_check_at=None))  # the fixture's old silent lead
    return world


async def say(w, ext: str, role: str, text: str, at: datetime) -> None:
    ev = Event(type="message.created", external_id=ext, occurred_at=at, text=text, sender={"role": role},
               channel={"kind": "messenger", "account_ref": "p1"}, conversation={"external_id": "ct1"},
               contact={"external_id": "psid1"}, staff={"external_id": "nv1"})
    async with tenant_session(w.t.id) as s:
        assert await apply_event(s, await s.get(m.Connector, w.cn.id), ev, at) == "accepted"


async def conv_of(w) -> m.Conversation:
    async with tenant_session(w.t.id) as s:
        return (await s.execute(select(m.Conversation).where(m.Conversation.external_id == "ct1"))).scalar_one()


async def turn_jobs(w) -> list[m.FollowupJob]:
    return [j for j in await rows(w, m.FollowupJob) if j.event_type == "conversation.awaiting_reply"]


async def log_reasons(w) -> list[str | None]:
    return [d.reason_code for d in await rows(w, m.DecisionLog)]


async def go_auto(w, owner_engine) -> Bridge:
    await sql(owner_engine, "update sandbox set send_mode = 'auto' where id = :i", i=w.sb.id)
    await sql(owner_engine, "update connector set trust = 'official', outbound = cast(:o as jsonb) where id = :i",
              o=json.dumps({"enabled": True, "url": URL}), i=w.cn.id)
    return Bridge()


def test_parse_duration_seconds() -> None:
    assert parse_duration("30s") == timedelta(seconds=30)


async def test_turn_mark_slides_and_fires_once(tw) -> None:
    await say(tw, "a", "customer", "xin chào", NOW)
    await say(tw, "b", "customer", "cho em hỏi", NOW + timedelta(seconds=10))
    await say(tw, "c", "customer", "khoá ielts", NOW + timedelta(seconds=20))
    assert (await conv_of(tw)).reply_check_at == NOW + timedelta(seconds=50)
    assert await sweep_once(NOW + timedelta(seconds=40)) == 0  # still typing
    assert await sweep_once(NOW + timedelta(seconds=60)) == 1
    assert await sweep_once(NOW + timedelta(seconds=90)) == 0 and (await conv_of(tw)).reply_check_at is None
    (job,) = await turn_jobs(tw)
    assert job.skill_name == "tra-loi-khach" and job.dedupe_key.endswith(":c:0")
    async with tenant_session(tw.t.id) as s:  # asked again for the same turn: no second job
        assert await on_conversation_event(s, await s.get(m.Conversation, (await conv_of(tw)).id),
                                           "conversation.awaiting_reply", NOW + timedelta(seconds=95)) == []


async def test_staff_answering_clears_the_mark_and_activity_blocks_the_turn(tw) -> None:
    await say(tw, "a", "customer", "xin chào", NOW)
    await say(tw, "s", "staff", "Dạ chào anh", NOW + timedelta(seconds=10))
    assert (await conv_of(tw)).reply_check_at is None
    assert await sweep_once(NOW + timedelta(minutes=5)) == 0 and not await turn_jobs(tw)
    # the customer writes again 3 minutes after staff spoke: staff is still "on" this conversation
    await say(tw, "b", "customer", "giá bao nhiêu vậy", NOW + timedelta(minutes=3))
    gw, prov = gateway()
    assert await sweep_once(NOW + timedelta(minutes=4)) == 1
    assert not await turn_jobs(tw) and "staff_active" in await log_reasons(tw)
    assert await run_pending(NOW + timedelta(minutes=4), gw) == 0 and prov.calls == []  # 0 token
    # R44: staff greeted then walked away -> the turn is looked at again when their 10 minutes are up
    assert (await conv_of(tw)).reply_check_at == NOW + timedelta(seconds=10) + STAFF_ACTIVE
    assert await sweep_once(NOW + timedelta(minutes=11)) == 1 and len(await turn_jobs(tw)) == 1


async def test_auto_reply_goes_out_off_hours_with_disclosure_and_costs_no_touch(tw, owner_engine) -> None:
    await go_auto(tw, owner_engine)
    calls = []
    for i in range(3):  # three turns in a row: none of them may spend the follow-up cap of 3
        t0 = OFF_HOURS + timedelta(minutes=10 * i)
        await say(tw, f"a{i}", "customer", "xin chào" if i < 2 else "giá khoá ielts bao nhiêu", t0)
        await sweep_once(t0 + timedelta(seconds=40))
        assert await run_pending(t0 + timedelta(seconds=40), gateway(reply(HELLO))[0]) == 1
        (ob,) = [o for o in await rows(tw, m.Outbox) if o.status == "queued"]
        assert ob.actor.startswith("ai:") and ob.disclosure and ob.not_before == t0 + timedelta(seconds=40)
        assert ob.source["turn"] is True
        bridge = Bridge(now=t0 + timedelta(seconds=41))
        assert await deliver_once(t0 + timedelta(seconds=41), client=bridge.client) == 1
        calls += bridge.calls
    assert len(calls) == 3 and (await conv_of(tw)).touches == 0
    # 25h later the follow-up skill still has its whole cap
    later = OFF_HOURS + timedelta(hours=26)
    async with tenant_session(tw.t.id) as s:
        (job,) = await on_conversation_event(s, await s.get(m.Conversation, (await conv_of(tw)).id),
                                             "conversation.silent", later)
    from wp5_support import GOOD_DRAFT, run_one
    run = await run_one(tw, gateway(reply(GOOD_DRAFT))[0], job, later)
    assert run.status == "ok" and "TOUCH_LIMIT" not in run.blocked_codes


async def test_manual_reply_is_only_a_draft(tw) -> None:
    await say(tw, "a", "customer", "xin chào", OFF_HOURS)
    await sweep_once(OFF_HOURS + timedelta(seconds=40))
    await run_pending(OFF_HOURS + timedelta(seconds=40), gateway(reply(HELLO))[0])
    (d,) = await rows(tw, m.Draft)
    assert d.status == "proposed" and not d.needs_human and not await rows(tw, m.Outbox)


async def test_handoff_is_never_sent_even_in_auto(tw, owner_engine) -> None:
    await go_auto(tw, owner_engine)
    await say(tw, "a", "customer", "giảm cho mình chút được không", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    hand = {"act": "handoff", "text": "Khách xin giảm giá khoá IELTS, nhờ anh/chị trả lời, em chưa hứa gì."}
    await run_pending(NOW + timedelta(seconds=40), gateway(reply(hand))[0])
    d, hold = sorted(await rows(tw, m.Draft), key=lambda x: not x.needs_human)
    assert d.status == "proposed" and d.needs_human
    (note,) = await rows(tw, m.Notification)  # R58: a person is pushed, once, for the card only
    assert (note.kind, note.ref_id, note.status) == ("handoff", d.id, "queued")
    (ob,) = await rows(tw, m.Outbox)  # only the holding line went out, never the note for staff
    assert ob.draft_id == hold.id and not hold.needs_human
    # defence in depth: the send tool itself refuses an ai caller on a handoff draft
    from ob_support import send
    res = await send(SimpleNamespace(t=tw.t, sb=tw.sb, conv=await conv_of(tw)), d, now=NOW + timedelta(seconds=41))
    assert res.status == "blocked" and res.violations[0].detail == "handoff_draft"


async def test_wait_moves_the_mark_once_then_must_decide(tw) -> None:
    await say(tw, "a", "customer", "cho em hỏi", NOW)
    t1 = NOW + timedelta(seconds=40)
    await sweep_once(t1)
    await run_pending(t1, gateway(reply({"act": "wait"}))[0])
    c = await conv_of(tw)
    assert (c.reply_waits, c.reply_check_at) == (1, t1 + timedelta(minutes=2)) and not await rows(tw, m.Draft)
    t2 = t1 + timedelta(minutes=2, seconds=1)
    assert await sweep_once(t2) == 1 and len(await turn_jobs(tw)) == 2  # the key changed: it may fire again
    await run_pending(t2, gateway(reply({"act": "wait"}))[0])
    c = await conv_of(tw)
    assert c.reply_waits == 1 and c.reply_check_at is None and not await rows(tw, m.Draft)
    assert "turn_wait_spent" in [d.decision for d in await rows(tw, m.DecisionLog)]


async def test_invented_price_in_a_reply_is_blocked(tw, owner_engine) -> None:
    await go_auto(tw, owner_engine)
    await say(tw, "a", "customer", "ib giá", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    bad = {**HELLO, "text": "Dạ khoá này giá chỉ 1.900.000đ thôi ạ"}
    await run_pending(NOW + timedelta(seconds=40), gateway(reply(bad), reply(bad))[0])  # rewrite fails too
    drafts = await rows(tw, m.Draft)  # R50: the attempts stay blocked, the waiting customer lands on a person
    (d,) = [x for x in drafts if x.needs_human]
    assert d.status == "proposed" and "1.900.000" in d.text
    (ob,) = await rows(tw, m.Outbox)
    (hold,) = [x for x in drafts if x.id == ob.draft_id]
    assert "1.900.000" not in hold.text and [x.status for x in drafts].count("blocked") == 1
    assert "turn_handoff_blocked" in [x.decision for x in await rows(tw, m.DecisionLog)]


async def test_handoff_note_quoting_the_customer_number_still_reaches_staff(tw, owner_engine) -> None:
    await go_auto(tw, owner_engine)  # seen with a real model: the note repeats "20%", which no catalog row has
    await say(tw, "a", "customer", "shop giảm giá cho em 20% được không", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    hand = {"act": "handoff", "text": "Khách xin giảm 20% cho khoá học. Anh/chị xem rồi trả lời khách, em chưa hứa gì."}
    await run_pending(NOW + timedelta(seconds=40), gateway(reply(hand))[0])
    card, hold = sorted(await rows(tw, m.Draft), key=lambda d: not d.needs_human)
    assert (card.status, card.needs_human) == ("proposed", True)
    # the waiting customer still hears back at once: the skill's fixed, fact-free holding line
    (ob,) = await rows(tw, m.Outbox)
    assert ob.draft_id == hold.id and ob.actor.startswith("ai:") and "tư vấn phụ trách" in hold.text


async def test_staff_answering_expires_the_turn_draft_and_stale_outbox(tw, owner_engine) -> None:
    await say(tw, "a", "customer", "xin chào", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    await run_pending(NOW + timedelta(seconds=40), gateway(reply(HELLO))[0])
    await say(tw, "s", "staff", "Dạ chào anh", NOW + timedelta(minutes=1))
    assert [d.status for d in await rows(tw, m.Draft)] == ["expired"]
    # auto: the message is queued but staff speaks before delivery -> cancelled, not sent
    bridge = await go_auto(tw, owner_engine)
    await say(tw, "b", "customer", "giá bao nhiêu", NOW + timedelta(minutes=30))
    await sweep_once(NOW + timedelta(minutes=31))
    await run_pending(NOW + timedelta(minutes=31), gateway(reply(HELLO))[0])
    await say(tw, "s2", "staff", "Dạ em báo giá ạ", NOW + timedelta(minutes=31, seconds=1))
    await deliver_once(NOW + timedelta(minutes=32), client=bridge.client)
    assert bridge.calls == [] and [o.reason for o in await rows(tw, m.Outbox)] == ["STALE"]


async def test_worker_pass_runs_everything_once(tw) -> None:
    now = datetime.now(NOW.tzinfo)
    await say(tw, "a", "customer", "xin chào", now - timedelta(minutes=1))
    gw, _ = gateway(reply(HELLO))
    assert await worker_once(gw) == (1, 1, 0)
    assert await worker_once(gw) == (0, 0, 0)
    assert len(await rows(tw, m.Draft)) == 1


async def test_turn_does_not_eat_the_staff_draft_cap(tw) -> None:
    await sql_cap(tw)
    await say(tw, "a", "customer", "xin chào", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    assert await run_pending(NOW + timedelta(seconds=40), gateway(reply(HELLO))[0]) == 1  # cap 0 does not stop it
    assert len(await rows(tw, m.Draft)) == 1


async def sql_cap(w) -> None:
    async with tenant_session(w.t.id) as s:
        await s.execute(update(m.Sandbox).values(budget={"runs_per_day": 100, "drafts_per_staff_per_day": 0,
                                                         "tokens_per_day": 100000}))


async def test_a_blocked_reply_gets_one_rewrite_told_why(tw, owner_engine) -> None:
    await go_auto(tw, owner_engine)  # seen with a real model: it echoed the customer's "3-4 tháng"
    await say(tw, "a", "customer", "khoảng 3-4 tháng nữa em thi, học phí sao shop", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    echo = {**HELLO, "text": "Dạ chị thi trong 3-4 tháng nữa thì vừa khớp ạ"}
    gw, prov = gateway(reply(echo), reply(HELLO))
    await run_pending(NOW + timedelta(seconds=40), gw)
    assert "UNVERIFIED_CLAIM" in prov.calls[1]["messages"][-1]["content"]  # the model is told why
    drafts = {d.id: d for d in await rows(tw, m.Draft)}
    (ob,) = await rows(tw, m.Outbox)
    assert drafts[ob.draft_id].text == HELLO["text"] and not any(d.needs_human for d in drafts.values())


async def test_a_card_for_a_person_survives_the_customer_writing_again(tw, owner_engine) -> None:
    await go_auto(tw, owner_engine)  # seen live: "có lớp tối không" -> card; next message expired it
    await say(tw, "a", "customer", "có lớp buổi tối không shop", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    hand = {"act": "handoff", "text": "Khách hỏi lớp buổi tối, catalog không ghi. Nhờ anh/chị trả lời."}
    await run_pending(NOW + timedelta(seconds=40), gateway(reply(hand))[0])
    await say(tw, "b", "customer", "à mà học phí bao nhiêu vậy", NOW + timedelta(minutes=2))
    (card,) = [d for d in await rows(tw, m.Draft) if d.needs_human]
    assert card.status == "proposed"
    await say(tw, "s", "staff", "Dạ bên em có lớp tối thứ 2-4-6 ạ", NOW + timedelta(minutes=3))
    assert (await tenant_get(tw, card)).status == "expired"  # a person answered: the card is done


async def tenant_get(w, row):
    async with tenant_session(w.t.id) as s:
        return await s.get(type(row), row.id)


async def test_handoff_tells_the_customer_in_the_models_words_else_the_fixed_line(tw, owner_engine) -> None:
    await go_auto(tw, owner_engine)
    await say(tw, "a", "customer", "sao lâu vậy, nãy giờ chưa thấy ai báo", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    own = "Dạ em xin lỗi để mình chờ lâu ạ, em đã nhắc lại bạn tư vấn rồi."
    hand = {"act": "handoff", "text": "Khách sốt ruột.", "customer_text": own}
    await run_pending(NOW + timedelta(seconds=40), gateway(reply(hand))[0])
    (ob,) = await rows(tw, m.Outbox)
    assert {d.id: d for d in await rows(tw, m.Draft)}[ob.draft_id].text == own
    # a promise slipped into the model's line is caught: the fixed, honest line goes instead
    await say(tw, "b", "customer", "alo shop", NOW + timedelta(minutes=2))
    await sweep_once(NOW + timedelta(minutes=3))
    bad = {**hand, "customer_text": "Dạ em xếp lớp cho mình rồi ạ."}
    await run_pending(NOW + timedelta(minutes=3), gateway(reply(bad))[0])
    texts = {d.id: d.text for d in await rows(tw, m.Draft)}
    last = max(await rows(tw, m.Outbox), key=lambda o: o.created_at)
    assert "tư vấn phụ trách" in texts[last.draft_id]


async def test_a_reply_refused_at_the_send_floor_still_answers_the_customer(tw, owner_engine) -> None:
    await go_auto(tw, owner_engine)  # must_handoff ("giảm giá") refuses the AI send after the draft was fine
    await say(tw, "a", "customer", "bên mình có giảm giá không ạ", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    await run_pending(NOW + timedelta(seconds=40), gateway(reply(HELLO))[0])
    drafts = {d.id: d for d in await rows(tw, m.Draft)}
    (ob,) = await rows(tw, m.Outbox)
    assert "tư vấn phụ trách" in drafts[ob.draft_id].text
    assert [d.text for d in drafts.values() if d.needs_human] == [HELLO["text"]]


async def test_a_model_failure_on_a_turn_still_answers_the_customer(tw, owner_engine) -> None:
    await go_auto(tw, owner_engine)  # seen live: ShapeError on "cam kết đầu ra không shop" -> silence
    await say(tw, "a", "customer", "cam kết đầu ra không shop", NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    await run_pending(NOW + timedelta(seconds=40), gateway(reply("tôi không biết"))[0])
    drafts = {d.id: d for d in await rows(tw, m.Draft)}
    (ob,) = await rows(tw, m.Outbox)
    assert "tư vấn phụ trách" in drafts[ob.draft_id].text and any(d.needs_human for d in drafts.values())
