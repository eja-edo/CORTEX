from datetime import date, timedelta

from sqlalchemy import update
from wp5_support import NOW, World, live_skills, rows, set_conv

from cortex_leads.clock.sweeper import sweep_once
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.triggers.engine import on_conversation_event
from cortex_leads.triggers.select import select_jobs


async def fire(w, event="conversation.silent", **kw):
    async with tenant_session(w.t.id) as s:
        conv = await s.get(m.Conversation, w.conv.id)
        return await on_conversation_event(s, conv, event, NOW, **kw)


async def decisions(w, name):
    return [d for d in await rows(w, m.DecisionLog) if d.decision == name]


async def test_silent_creates_one_job_with_dedupe_key(world):
    (job,) = await fire(world)
    assert job.skill_name == "hoi-lai-khach-im" and job.status == "pending"
    assert job.dedupe_key == f"silent:{world.conv.id}:m1"
    assert await fire(world) == []  # same silence: ON CONFLICT DO NOTHING
    assert len(await rows(world, m.FollowupJob)) == 1
    assert len(await decisions(world, "job_created")) == 1


async def test_engine_sourced_event_never_matches(world):  # loop guard
    assert await fire(world, source="engine") == []
    assert not await rows(world, m.FollowupJob) and await decisions(world, "event_ignored")


async def test_paused_sandbox_makes_no_job(world):
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).values(status="paused"))
    assert await fire(world) == [] and (await decisions(world, "event_ignored"))[0].reason_code == "paused"


async def test_no_matching_skill_is_logged(world):
    await set_conv(world, intent=None)  # hoi-lai-khach-im needs intent == hoi_gia
    assert await fire(world) == [] and await decisions(world, "no_matching_skill")


async def test_second_skill_runs_with_zero_engine_change(world):  # A6
    await set_conv(world, promised_date=date(2026, 10, 12))
    (job,) = await fire(world, "conversation.promised_date_reached")
    assert job.skill_name == "hoi-lai-dung-hen" and job.dedupe_key.startswith("promised:")


async def test_sweep_fires_once_and_rearms_only_by_new_message(world):
    assert await sweep_once(NOW) == 1
    (conv,) = await rows(world, m.Conversation)
    assert conv.next_check_at is None and len(await rows(world, m.FollowupJob)) == 1
    await set_conv(world, next_check_at=NOW - timedelta(hours=1))  # forced re-fire, same silence
    assert await sweep_once(NOW) == 1
    assert len(await rows(world, m.FollowupJob)) == 1  # sweep twice does not multiply jobs


async def test_sweep_ignores_future_and_picks_promised_event(world):
    await set_conv(world, next_check_at=NOW + timedelta(hours=1))
    assert await sweep_once(NOW) == 0
    await set_conv(world, next_check_at=NOW - timedelta(minutes=1), promised_date=date(2026, 10, 12))
    assert await sweep_once(NOW) == 1
    assert (await rows(world, m.FollowupJob))[0].event_type == "conversation.promised_date_reached"


async def test_sweep_is_fair_across_tenants(world, tenant_factory, sandbox_factory,
                                            connector_factory, conversation_factory):
    async def extra(w_or_none, name):
        t = await tenant_factory(name)
        sb = await sandbox_factory(t)
        cn = await connector_factory(sb)
        convs = [await conversation_factory(cn, external_id=f"{name}{i}", intent="hoi_gia",
                                            last_customer_at=NOW - timedelta(hours=30),
                                            last_customer_msg_id=f"x{i}",
                                            next_check_at=NOW - timedelta(hours=1))
                 for i in range(3)]
        await live_skills(t, sb)
        return World(t, sb, cn, convs[0])

    b = await extra(None, "B")
    assert await sweep_once(NOW, limit=2) == 2
    # 1 due conversation of tenant A + 3 of B, limit 2 -> each tenant gets a share of one
    assert len(await rows(world, m.FollowupJob)) == 1 and len(await rows(b, m.FollowupJob)) == 1


async def pending(w, conv, event="conversation.silent", key=None):
    async with tenant_session(w.t.id) as s:
        s.add(m.FollowupJob(id=uuid7(), tenant_id=w.t.id, sandbox_id=w.sb.id, conversation_id=conv.id,
                            skill_name="hoi-lai-khach-im", skill_version=1, event_type=event,
                            dedupe_key=key or str(uuid7()), not_before=NOW))


async def test_select_caps_per_staff_not_per_sandbox(world, conversation_factory):  # R5
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).values(budget={
            "runs_per_day": 100, "drafts_per_staff_per_day": 1, "tokens_per_day": 10**6}))
    await set_conv(world, owner_staff_ref="s1")
    c2 = await conversation_factory(world.cn, external_id="c2", owner_staff_ref="s1",
                                    last_customer_at=NOW - timedelta(hours=40))
    c3 = await conversation_factory(world.cn, external_id="c3", owner_staff_ref="s2")
    c4 = await conversation_factory(world.cn, external_id="c4")  # unassigned
    for c in (world.conv, c2, c3, c4):
        await pending(world, c)
    async with tenant_session(world.t.id) as s:
        chosen = await select_jobs(s, await s.get(m.Sandbox, world.sb.id), NOW)
    assert len(chosen) == 3  # one per owner: s1, s2, unassigned
    jobs = await rows(world, m.FollowupJob)
    assert sorted(j.status for j in jobs) == ["pending", "pending", "pending", "skipped"]
    skipped = [d for d in await rows(world, m.DecisionLog) if d.decision == "job_skipped_budget"]
    assert len(skipped) == 1 and skipped[0].detail["owner"] == "s1"


async def test_select_ranks_promised_then_price_then_older(world, conversation_factory):
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).values(budget={
            "runs_per_day": 100, "drafts_per_staff_per_day": 1, "tokens_per_day": 10**6}))
    await set_conv(world, owner_staff_ref="s1")
    other = await conversation_factory(world.cn, external_id="o", owner_staff_ref="s1", intent=None)
    await pending(world, world.conv)  # hoi_gia
    await pending(world, other, "conversation.promised_date_reached", "p")  # promised wins
    async with tenant_session(world.t.id) as s:
        (job,) = await select_jobs(s, await s.get(m.Sandbox, world.sb.id), NOW)
    assert job.event_type == "conversation.promised_date_reached"


async def test_select_counts_drafts_already_written_today(world):
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).values(budget={
            "runs_per_day": 100, "drafts_per_staff_per_day": 1, "tokens_per_day": 10**6}))
        s.add(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id,
                      text="x", created_at=NOW))
    await pending(world, world.conv)
    async with tenant_session(world.t.id) as s:
        assert await select_jobs(s, await s.get(m.Sandbox, world.sb.id), NOW) == []


async def test_select_priority_follows_the_pack(world, conversation_factory):  # R21
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).values(budget={
            "runs_per_day": 100, "drafts_per_staff_per_day": 1, "tokens_per_day": 10**6}))

    async def pick(priority):
        async with tenant_session(world.t.id) as s:
            await s.execute(update(m.Sandbox).values(domain_pack={"priority_intents": priority}))
            await s.execute(update(m.FollowupJob).values(status="pending"))
        async with tenant_session(world.t.id) as s:
            (job,) = await select_jobs(s, await s.get(m.Sandbox, world.sb.id), NOW)
            return job.conversation_id

    await set_conv(world, owner_staff_ref="s1", intent="hoi_gia")
    other = await conversation_factory(world.cn, external_id="o", owner_staff_ref="s1", intent="hoi_lich")
    await pending(world, world.conv)
    await pending(world, other)
    assert await pick(["hoi_gia"]) == world.conv.id
    assert await pick(["hoi_lich"]) == other.id
