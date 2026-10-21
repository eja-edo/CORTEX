"""WP24: tags and notes on the platform (T2 chiều ngược). Not a message: no window, no disclosure, no touch."""
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from ob_support import URL, Bridge, sql
from sqlalchemy import update
from wp5_support import NOW, REG, rows

from cortex_leads.core.context import CustomerPrincipal, RunContext, Scope
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.memory.service import record_outcome
from cortex_leads.outbound.annotate import annotate
from cortex_leads.outbound.worker import deliver_once

OUT = {"enabled": True, "url": URL, "capabilities": ["send_message", "add_tag", "add_note"],
       "tags": {"handoff": "AI: cần người", "won": "AI: đã chốt"}, "notes": {"booking": "AI đã giữ chỗ học thử"}}


async def configure(w, owner_engine, outbound=OUT, **kw):
    await sql(owner_engine, "update connector set trust = 'official', outbound = cast(:o as jsonb) where id = :i",
              o=json.dumps(outbound), i=w.cn.id)


async def conv(w) -> m.Conversation:
    async with tenant_session(w.t.id) as s:
        return await s.get(m.Conversation, w.conv.id)


async def queue(w, event, ref=None, now=NOW) -> int:
    async with tenant_session(w.t.id) as s:
        return await annotate(s, await s.get(m.Conversation, w.conv.id), event, ref or uuid4(), now)


async def test_only_what_the_business_mapped_and_allowed_is_queued(world, owner_engine):
    await configure(world, owner_engine)
    assert await queue(world, "handoff") == 1 and await queue(world, "booking") == 1 and await queue(world, "lost") == 0
    kinds = sorted((o.kind, o.text, o.actor) for o in await rows(world, m.Outbox))
    assert kinds == [("add_note", "AI đã giữ chỗ học thử", "system:annotate"), ("add_tag", "AI: cần người", "system:annotate")]
    await configure(world, owner_engine, {**OUT, "capabilities": ["send_message"]})  # the bridge cannot tag
    assert await queue(world, "won") == 0
    await configure(world, owner_engine, {**OUT, "enabled": False})
    assert await queue(world, "won") == 0
    await configure(world, owner_engine, None)
    assert await queue(world, "won") == 0
    with pytest.raises(ValueError):
        await queue(world, "anything")


async def test_the_same_event_is_marked_once(world, owner_engine):
    await configure(world, owner_engine)
    ref = uuid4()
    assert await queue(world, "handoff", ref) == 1 and await queue(world, "handoff", ref) == 0
    assert await queue(world, "handoff", uuid4()) == 1  # another handoff is another mark
    assert len(await rows(world, m.Outbox)) == 2


async def test_delivery_sends_a_mark_not_a_message_even_when_the_window_is_closed(world, owner_engine):
    await configure(world, owner_engine)
    await queue(world, "handoff")
    bridge = Bridge(now=NOW)
    assert await deliver_once(NOW, client=bridge.client) == 1  # the world's last customer message is 26h old: window shut
    (call,) = bridge.calls
    assert call["type"] == "add_tag" and call["tag"] == "AI: cần người" and call["actor"] == "system:annotate"
    assert not {"text", "window", "disclosure"} & set(call)  # nothing a customer could read
    (o,) = await rows(world, m.Outbox)
    assert o.status == "sent" and (await conv(world)).touches == 0


async def test_a_bridge_without_tags_refuses_and_that_is_final(world, owner_engine):
    await configure(world, owner_engine)
    await queue(world, "booking")
    bridge = Bridge({"status": "refused", "reason": "NOT_SUPPORTED"}, now=NOW)
    await deliver_once(NOW, client=bridge.client)
    await deliver_once(NOW + timedelta(hours=1), client=bridge.client)
    (o,) = await rows(world, m.Outbox)
    assert (o.status, o.reason) == ("refused", "NOT_SUPPORTED") and len(bridge.calls) == 1
    assert not [d for d in await rows(world, m.Draft)]  # no fallback draft for a mark


async def test_retries_then_gives_up_and_the_kill_switch_stops_it(world, owner_engine):
    await configure(world, owner_engine)
    await queue(world, "handoff")
    bridge = Bridge(status=503, now=NOW)
    await deliver_once(NOW, client=bridge.client)
    (o,) = await rows(world, m.Outbox)
    assert (o.status, o.attempts) == ("queued", 1)
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).values(status="paused"))
    await deliver_once(NOW + timedelta(hours=1), client=bridge.client)
    (o,) = await rows(world, m.Outbox)
    assert (o.status, o.reason) == ("cancelled", "PAUSED")


async def test_the_real_events_mark_the_conversation(world, owner_engine, catalog_factory):
    await configure(world, owner_engine)
    async with tenant_session(world.t.id) as s:  # an owner/staff outcome "won"
        await record_outcome(s, conversation_id=world.conv.id, status="won", source="staff:nv1", evidence_msg_ids=[], now=NOW)
    assert [(o.kind, o.text) for o in await rows(world, m.Outbox)] == [("add_tag", "AI: đã chốt")]
    await sql(owner_engine, "update conversation set state = 'open'")  # booking -> note
    start = NOW + timedelta(days=3)
    await catalog_factory(world.t, code="LH-A", name="Học thử", price=None, category="lich_hoc_thu", valid_until=start,
                          attrs={"ngay": f"{start:%d/%m}", "gio": "19:00", "suc_chua": 2})
    ctx = RunContext(run_id=uuid4(), tenant_id=world.t.id, sandbox_id=world.sb.id, profile="customer_drafter",
                     profile_version=1, principal=CustomerPrincipal(contact_id=world.conv.contact_id),
                     scope=Scope(conversation_id=world.conv.id))
    async with tenant_session(world.t.id) as s:
        res = await REG.execute(ctx, s, "book_slot", {"slot_code": "LH-A"}, allowlist=["book_slot"], effect_ceiling="internal")
    assert res.status == "ok"
    assert sorted(o.kind for o in await rows(world, m.Outbox)) == ["add_note", "add_tag"]
