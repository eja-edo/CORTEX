"""WP8: outbox worker against a signing mock bridge (no network)."""
from datetime import UTC, datetime, timedelta

from ob_support import NOW, Bridge, configure, run, send, sql
from sqlalchemy import update
from wp5_support import rows

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.outbound.worker import deliver_once
from cortex_leads.triggers.engine import on_conversation_event


async def queued(world, owner_engine, **kw):
    await configure(world, owner_engine, mode="auto", **kw)
    await run(world)
    (ob,) = await rows(world, m.Outbox)
    return ob


async def one(world):
    (ob,) = await rows(world, m.Outbox)
    return ob


async def drafts(world, status):
    return [d for d in await rows(world, m.Draft) if d.status == status]


async def test_auto_delivery_is_signed_and_in_action_format(world, owner_engine):
    ob = await queued(world, owner_engine)
    bridge = Bridge()
    assert await deliver_once(NOW, client=bridge.client) == 1
    (call,) = bridge.calls  # signature verified inside Bridge.__call__
    assert call["format"] == "cortex.action/1" and call["type"] == "send_message"
    assert call["action_id"] == str(ob.action_id) and call["actor"] == "ai:customer_drafter@1"
    assert call["disclosure"] == "Trợ lý AI của Acme" and call["text"] == ob.text
    assert call["window"]["open"] is True and call["window"]["basis"] == "free" and call["window"]["expires_at"]
    assert call["conversation"]["external_id"] == world.conv.external_id
    assert call["channel"]["kind"] == "messenger" and call["source"]["skill"] == "thu-nhanh@1"
    row = await one(world)
    assert (row.status, row.external_message_id, row.sent_at) == ("sent", "mid.1", NOW)
    assert (await drafts(world, "sent")) and not await drafts(world, "proposed")
    # the sent message comes back through ingest (echo): the worker writes no message, no extra touch
    assert await rows(world, m.Message) and len(await rows(world, m.Message)) == 1
    assert await deliver_once(NOW, client=bridge.client) == 0 and len(bridge.calls) == 1  # no double send
    assert (await rows(world, m.Conversation))[0].touches == 1  # R36: counted once, when it went out


async def test_staff_action_has_no_disclosure_and_human_agent_window(world, owner_engine):
    await configure(world, owner_engine, silent_h=26)
    await run(world)
    (d,) = await rows(world, m.Draft)
    assert (await send(world, d, staff="nv1")).status == "ok"
    bridge = Bridge()
    await deliver_once(NOW, client=bridge.client)
    (call,) = bridge.calls
    assert call["actor"] == "staff:nv1" and "disclosure" not in call and call["window"]["basis"] == "human_agent"


async def test_not_before_is_respected_then_delivered(world, owner_engine):
    late = datetime(2026, 10, 12, 16, 30, tzinfo=UTC)
    await configure(world, owner_engine, mode="auto", now=late, silent_h=1)
    await run(world, now=late)
    bridge = Bridge(now=late)
    assert await deliver_once(late, client=bridge.client) == 0 and bridge.calls == []
    morning = datetime(2026, 10, 13, 1, 0, tzinfo=UTC)
    bridge.now = morning
    assert await deliver_once(morning, client=bridge.client) == 1 and len(bridge.calls) == 1


async def test_refused_is_final_and_falls_back_to_a_staff_draft(world, owner_engine):
    await queued(world, owner_engine)
    bridge = Bridge({"status": "refused", "reason": "PLATFORM_POLICY"})
    await deliver_once(NOW, client=bridge.client)
    await deliver_once(NOW + timedelta(hours=1), client=bridge.client)
    assert len(bridge.calls) == 1  # refused is a normal answer: no retry
    ob = await one(world)
    assert (ob.status, ob.reason) == ("refused", "PLATFORM_POLICY")
    (old,) = await drafts(world, "failed")
    (new,) = await drafts(world, "proposed")
    assert new.text == old.text and new.run_id == old.run_id and new.id != old.id
    decisions = {d.decision for d in await rows(world, m.DecisionLog)}
    assert {"send_refused", "fallback_manual"} <= decisions


async def test_unknown_refusal_text_never_reaches_the_reason_column(world, owner_engine):
    await queued(world, owner_engine)
    await deliver_once(NOW, client=Bridge({"status": "refused", "reason": "Khách 0901 chặn"}).client)
    assert (await one(world)).reason == "REFUSED_OTHER"


async def test_refused_staff_message_is_not_looped_back(world, owner_engine):
    await configure(world, owner_engine)
    await run(world)
    (d,) = await rows(world, m.Draft)
    await send(world, d, staff="nv1")
    await deliver_once(NOW, client=Bridge({"status": "refused", "reason": "RATE_LIMIT"}).client)
    assert [x.status for x in await rows(world, m.Draft)] == ["failed"]  # she hears it; no new draft


async def test_retryable_error_backs_off_and_stops_after_three(world, owner_engine):
    await queued(world, owner_engine)
    bridge = Bridge({"status": "error", "retryable": True})
    assert await deliver_once(NOW, client=bridge.client) == 1
    ob = await one(world)
    assert (ob.status, ob.attempts) == ("queued", 1) and ob.not_before == NOW + timedelta(seconds=30)
    assert await deliver_once(NOW + timedelta(seconds=10), client=bridge.client) == 0  # still backing off
    t2 = NOW + timedelta(seconds=31)
    bridge.now = t2
    await deliver_once(t2, client=bridge.client)
    ob = await one(world)
    assert (ob.status, ob.attempts) == ("queued", 2) and ob.not_before == t2 + timedelta(seconds=120)
    t3 = t2 + timedelta(seconds=121)
    bridge.now = t3
    await deliver_once(t3, client=bridge.client)
    ob = await one(world)
    assert (ob.status, ob.attempts, ob.reason) == ("error", 3, "RETRIES_EXHAUSTED")
    assert len(bridge.calls) == 3
    await deliver_once(t3 + timedelta(days=1), client=bridge.client)
    assert len(bridge.calls) == 3
    assert len(await drafts(world, "proposed")) == 1  # fell back to manual
    assert "send_error" in {d.decision for d in await rows(world, m.DecisionLog)}


async def test_http_5xx_is_retryable_but_4xx_is_not(world, owner_engine):
    await queued(world, owner_engine)
    await deliver_once(NOW, client=Bridge({}, status=503).client)
    assert (await one(world)).status == "queued"
    t = NOW + timedelta(minutes=5)
    await deliver_once(t, client=Bridge({}, status=400, now=t).client)
    ob = await one(world)
    assert (ob.status, ob.reason) == ("error", "BRIDGE_ERROR")


async def test_transport_failure_is_retryable(world, owner_engine):
    import httpx
    await queued(world, owner_engine)

    def boom(request):
        raise httpx.ConnectError("down")

    await deliver_once(NOW, client=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    ob = await one(world)
    assert (ob.status, ob.attempts) == ("queued", 1)


async def test_kill_switch_is_checked_again_at_send_time(world, owner_engine):
    for stmt in ("update sandbox set status = 'paused'", "update connector set status = 'disabled'",
                 "update connector set outbound = null"):
        await sql(owner_engine, "truncate outbox, draft, followup_job, trigger_run, decision_log cascade")
        await sql(owner_engine, "update sandbox set status = 'active'")
        await sql(owner_engine, "update connector set status = 'active'")
        await queued(world, owner_engine)
        await sql(owner_engine, stmt)
        bridge = Bridge()
        await deliver_once(NOW, client=bridge.client)
        assert bridge.calls == [], stmt
        assert (await one(world)).status == "cancelled"


async def test_customer_spoke_after_queueing_cancels_ai_message(world, owner_engine, message_factory):
    await queued(world, owner_engine)
    await message_factory(world.conv, "À mà cho em hỏi thêm", occurred_at=NOW + timedelta(minutes=1))
    bridge = Bridge()
    await deliver_once(NOW + timedelta(minutes=2), client=bridge.client)
    ob = await one(world)
    assert bridge.calls == [] and (ob.status, ob.reason) == ("cancelled", "STALE")
    assert await drafts(world, "proposed") == []  # nothing for staff: the customer moved on


async def test_window_that_closed_while_queued_is_not_sent(world, owner_engine):
    await queued(world, owner_engine, silent_h=23)  # free window ends at NOW + 1h
    bridge = Bridge()
    t = NOW + timedelta(hours=2)
    bridge.now = t
    await deliver_once(t, client=bridge.client)
    assert bridge.calls == [] and (await one(world)).reason == "WINDOW_CLOSED"
    assert len(await drafts(world, "proposed")) == 1


async def test_outbox_is_tenant_scoped(world, owner_engine, tenant_factory):
    await queued(world, owner_engine)
    other = await tenant_factory("Other")
    async with tenant_session(other.id) as s:
        assert (await s.execute(m.Outbox.__table__.select())).all() == []


async def test_failed_or_refused_send_spends_no_touch(world, owner_engine):  # R36
    await queued(world, owner_engine)
    bridge = Bridge({"status": "refused", "reason": "PLATFORM_POLICY"}, status=409)
    await deliver_once(NOW, client=bridge.client)
    assert (await one(world)).status != "sent"
    assert (await rows(world, m.Conversation))[0].touches == 0


async def test_auto_send_lands_in_free_window_with_20h_after(world, owner_engine):  # R15
    await configure(world, owner_engine, mode="auto")
    await sql(owner_engine, "update skill_version set manifest = jsonb_set(manifest, '{trigger,after}', '\"20h\"')"
              " where name = 'thu-nhanh'")
    customer, staff = NOW - timedelta(hours=20, minutes=10), NOW - timedelta(hours=20)
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Message).values(occurred_at=customer))
        await s.execute(update(m.Conversation).values(last_customer_at=customer, last_staff_at=staff))
    async with tenant_session(world.t.id) as s:  # one hour early: nothing yet
        assert await on_conversation_event(
            s, await s.get(m.Conversation, world.conv.id), "conversation.silent", NOW - timedelta(hours=1)) == []
    await run(world)  # fires at activity + 20h, still inside Messenger's 24h free window
    await deliver_once(NOW, client=(bridge := Bridge()).client)
    (ob,) = await rows(world, m.Outbox)
    assert ob.status == "sent" and ob.window["basis"] == "free" and len(bridge.calls) == 1
    assert not await drafts(world, "proposed")  # did not fall back to manual
