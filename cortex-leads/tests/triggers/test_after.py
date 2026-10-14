"""R35: the silence clock follows the live skills' `trigger.after` and `limits.min_gap`."""
import copy
from datetime import timedelta

import pytest
from wp5_support import NOW, rows, set_conv

from cortex_leads.clock.sweeper import sweep_once
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.skills.manifest import parse_duration
from cortex_leads.skills.registry import silent_after_for
from cortex_leads.triggers.engine import on_conversation_event


async def fire(w, at=NOW):
    async with tenant_session(w.t.id) as s:
        conv = await s.get(m.Conversation, w.conv.id)
        return await on_conversation_event(s, conv, "conversation.silent", at)


async def next_check(w):
    return (await rows(w, m.Conversation))[0].next_check_at


def test_parse_duration():
    assert parse_duration("5m") == timedelta(minutes=5) and parse_duration("2d") == timedelta(days=2)
    for bad in ("1 day", "20", "h", "0h", "-3h", "1.5h"):
        with pytest.raises(ValueError):
            parse_duration(bad)


async def test_silent_after_is_min_of_live_skills_default_24h(world, sandbox_factory):
    async with tenant_session(world.t.id) as s:
        assert await silent_after_for(s, world.sb.id) == timedelta(hours=20)
        assert await silent_after_for(s, (await sandbox_factory(world.t)).id) == timedelta(hours=24)


async def test_not_due_yet_sets_next_check_to_due_time(world):
    await set_conv(world, last_customer_at=NOW - timedelta(hours=10), last_staff_at=NOW - timedelta(hours=8))
    assert await fire(world) == []
    assert await next_check(world) == NOW + timedelta(hours=12)  # last activity (staff) + 20h
    assert [d.decision for d in await rows(world, m.DecisionLog)] == ["not_due_yet"]


async def test_two_skills_fire_the_due_one_and_reschedule_the_other(world, seed):
    v = next(r for r in await rows(world, m.SkillVersion) if r.name == "hoi-lai-khach-im")
    man = copy.deepcopy(v.manifest)
    man["name"], man["trigger"]["after"] = "z-48h", "48h"
    await seed(m.SkillVersion(tenant_id=world.t.id, sandbox_id=world.sb.id, name="z-48h", version=1,
                              status="live", manifest=man, body=v.body, checksum="z"))
    (job,) = await fire(world)  # 26h of silence: the 20h skill is due, the 48h one is not
    assert job.skill_name == "hoi-lai-khach-im"
    assert await next_check(world) == world.conv.last_customer_at + timedelta(hours=48)
    (job2,) = await fire(world, NOW + timedelta(hours=23))  # 49h: the sibling goes, no second 20h job
    assert job2.skill_name == "z-48h" and len(await rows(world, m.FollowupJob)) == 2


async def test_min_gap_blocks_and_reschedules(world):
    await set_conv(world, last_customer_at=NOW - timedelta(hours=30))
    async with tenant_session(world.t.id) as s:
        s.add(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id,
                      status="sent", text="x", claims=[], reason_code="khong_ro",
                      decided_at=NOW - timedelta(hours=5)))
    assert await fire(world) == []
    assert await next_check(world) == NOW + timedelta(hours=19)  # touch + min_gap 24h
    assert [d.decision for d in await rows(world, m.DecisionLog)] == ["min_gap"]
    assert len(await fire(world, NOW + timedelta(hours=19))) == 1


async def test_sweeper_keeps_the_time_the_engine_set(world):
    await set_conv(world, last_customer_at=NOW - timedelta(hours=10), next_check_at=NOW - timedelta(minutes=1))
    assert await sweep_once(NOW) == 1
    assert await next_check(world) == NOW + timedelta(hours=10)
