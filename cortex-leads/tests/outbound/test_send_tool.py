"""WP8: send_message core checks (DESIGN A9, N1, N3) and the runner's auto / manual modes."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from ob_support import NOW, configure, run, send, sql
from wp5_support import rows

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session


async def drafted(w, owner_engine, **kw):
    """A proposed draft written in manual mode; tests then flip state and try to send."""
    await configure(w, owner_engine, **kw)
    await run(w)
    (d,) = await rows(w, m.Draft)
    assert d.status == "proposed"
    return d


def codes(res):
    return {f"{v.code.value}:{v.detail}" for v in res.violations}


async def logged(w, decision):
    return [d for d in await rows(w, m.DecisionLog) if d.decision == decision]


# --- the two modes --------------------------------------------------------------------------------
async def test_auto_queues_one_outbox_row_with_disclosure(world, owner_engine):
    await configure(world, owner_engine, mode="auto")
    run_ = await run(world)
    (ob,) = await rows(world, m.Outbox)
    (d,) = await rows(world, m.Draft)
    assert run_.status == "ok" and ob.status == "queued" and ob.actor == "ai:customer_drafter@1"
    assert ob.disclosure == "Trợ lý AI của Acme" and ob.text == d.text and d.status == "approved"
    assert ob.window["basis"] == "free" and ob.source["skill"] == "thu-nhanh@1"
    assert ob.not_before == NOW  # 10:00 in Asia/Ho_Chi_Minh: inside business hours
    assert [x.decision for x in await rows(world, m.DecisionLog) if x.decision == "send_queued"]
    log = [a for a in await rows(world, m.ActionLog) if a.tool == "send_message"]
    assert log[0].action_id == ob.action_id and "Chào" not in json.dumps(log[0].args_masked, ensure_ascii=False)


async def test_manual_never_writes_outbox_without_a_human(world, owner_engine):
    await configure(world, owner_engine, mode="manual")
    await run(world)
    assert await rows(world, m.Outbox) == []
    (d,) = await rows(world, m.Draft)
    assert d.status == "proposed"
    # and the tool itself refuses an ai:* caller in manual mode, whoever calls it
    res = await send(world, d)
    assert res.status == "blocked" and codes(res) == {"NOT_ALLOWED:manual_mode"}
    assert await rows(world, m.Outbox) == []


async def test_mode_skill_overrides_sandbox_and_needs_opt_in(world, owner_engine):
    await configure(world, owner_engine, mode="auto")
    # skill says manual -> manual even though the sandbox is auto
    await sql(owner_engine, "update skill_version set manifest = jsonb_set(manifest, '{send_policy}', "
              "'{\"mode\": \"manual\"}'::jsonb) where name = 'thu-nhanh'")
    await run(world)
    assert await rows(world, m.Outbox) == []
    # a skill that never opted in (output_kind draft_for_staff) stays manual under sandbox auto
    await sql(owner_engine, "update skill_version set manifest = manifest - 'send_policy' "
              "|| '{\"output_kind\": \"draft_for_staff\"}'::jsonb where name = 'thu-nhanh'")
    await sql(owner_engine, "truncate draft, followup_job, trigger_run cascade")
    await run(world)
    assert await rows(world, m.Outbox) == []


async def test_skill_auto_beats_sandbox_manual(world, owner_engine):
    await configure(world, owner_engine, mode="manual")
    await sql(owner_engine, "update skill_version set manifest = jsonb_set(manifest, '{send_policy}', "
              "'{\"mode\": \"auto\"}'::jsonb) where name = 'thu-nhanh'")
    await run(world)
    assert len(await rows(world, m.Outbox)) == 1


# --- fallbacks: nothing queued, draft stays proposed, decision logged ------------------------------
async def fell_back(w, expect: str):
    assert await rows(w, m.Outbox) == []
    (d,) = await rows(w, m.Draft)
    assert d.status == "proposed"
    (log,) = await logged(w, "fallback_manual")
    assert any(expect in c for c in log.detail["codes"])
    assert "Chào" not in json.dumps(log.detail, ensure_ascii=False)  # no customer text


async def test_human_agent_window_falls_back_to_manual(world, owner_engine):
    await configure(world, owner_engine, mode="auto", silent_h=26)  # past 24h free, inside 7d
    run_ = await run(world)
    assert run_.status == "ok"
    await fell_back(world, "WINDOW_CLOSED:human_only")


async def test_closed_window_blocks_ai_and_staff(world, owner_engine):
    d = await drafted(world, owner_engine)
    old = NOW - timedelta(days=8)  # time passes: the 7-day HUMAN_AGENT window is gone too
    await sql(owner_engine, "update conversation set last_customer_at = :t", t=old)
    await sql(owner_engine, "update sandbox set send_mode = 'auto'")
    for who in (None, "nv1"):
        res = await send(world, d, staff=who)
        assert res.status == "blocked" and codes(res) == {"WINDOW_CLOSED:closed"}
    assert await rows(world, m.Outbox) == []


async def test_staff_may_use_human_agent_window_but_ai_may_not(world, owner_engine):
    d = await drafted(world, owner_engine, silent_h=26)
    await sql(owner_engine, "update sandbox set send_mode = 'auto'")
    assert codes(await send(world, d)) == {"WINDOW_CLOSED:human_only"}
    res = await send(world, d, staff="nv1")
    assert res.status == "ok"
    (ob,) = await rows(world, m.Outbox)
    assert ob.actor == "staff:nv1" and ob.disclosure is None and ob.window["basis"] == "human_agent"


async def test_opted_out_blocks_even_staff(world, owner_engine):
    d = await drafted(world, owner_engine)
    await sql(owner_engine, "update contact set opted_out = true")
    assert {"OPTED_OUT:None"} == codes(await send(world, d, staff="nv1"))


async def test_validator_blocks_when_the_catalog_moved_on(world, owner_engine):
    d = await drafted(world, owner_engine)
    await sql(owner_engine, "update sandbox set send_mode = 'auto'")
    await sql(owner_engine, "update catalog_item set price = 3000000")
    res = await send(world, d)
    assert res.status == "blocked" and any(v.code == "UNVERIFIED_CLAIM" for v in res.violations)
    assert await rows(world, m.Outbox) == []
    # a human is accountable for what she sends: the floor applies, not the validator
    assert (await send(world, d, staff="nv1")).status == "ok"


async def test_must_handoff_phrase_in_last_customer_message(world, owner_engine):
    d = await drafted(world, owner_engine)
    await sql(owner_engine, "update sandbox set send_mode = 'auto'")
    await sql(owner_engine, "update message set text = 'Bên em giảm giá cho mình được không?'")
    assert codes(await send(world, d)) == {"NOT_ALLOWED:must_handoff"}


async def test_max_per_contact_per_day(world, owner_engine, seed):
    await configure(world, owner_engine, mode="auto")
    await sql(owner_engine, "update skill_version set manifest = jsonb_set(manifest, '{send_policy}', "
              "'{\"mode\": \"auto\", \"auto_when\": {\"max_per_contact_per_day\": 1}}'::jsonb) "
              "where name = 'thu-nhanh'")
    await seed(m.Outbox(tenant_id=world.t.id, action_id=world.conv.id, conversation_id=world.conv.id,
                        connector_id=world.cn.id, actor="ai:customer_drafter@1", text="x", status="sent",
                        created_at=NOW - timedelta(hours=3)))
    await run(world)
    assert len(await rows(world, m.Outbox)) == 1  # only the seeded one
    await fell_back_cap(world)


async def fell_back_cap(w):
    (log,) = await logged(w, "fallback_manual")
    assert "TOUCH_LIMIT:per_contact_per_day" in log.detail["codes"]


# --- business hours --------------------------------------------------------------------------------
async def test_outside_business_hours_waits_for_opening(world, owner_engine):
    late = datetime(2026, 10, 12, 16, 30, tzinfo=UTC)  # 23:30 in Ho Chi Minh
    await configure(world, owner_engine, mode="auto", now=late, silent_h=1)
    await run(world, now=late)
    (ob,) = await rows(world, m.Outbox)
    assert ob.status == "queued" and ob.not_before == datetime(2026, 10, 13, 1, 0, tzinfo=UTC)


async def test_window_closing_before_opening_falls_back(world, owner_engine):
    late = datetime(2026, 10, 12, 16, 30, tzinfo=UTC)
    await configure(world, owner_engine, mode="auto", now=late, silent_h=20)  # closes 20:30Z < 01:00Z
    await run(world, now=late)
    await fell_back(world, "WINDOW_CLOSED:closes_before_opening")


# --- kill switches and trust -----------------------------------------------------------------------
@pytest.mark.parametrize("stmt,expect", [
    ("update sandbox set status = 'paused'", "PAUSED:sandbox_or_tenant"),
    ("update tenant set status = 'paused'", "PAUSED:sandbox_or_tenant"),
    ("update connector set status = 'disabled'", "PAUSED:connector"),
    ("update connector set outbound = '{\"enabled\": false, \"url\": \"http://b\"}'::jsonb",
     "NOT_ALLOWED:outbound_off"),
    ("update connector set outbound = null", "NOT_ALLOWED:outbound_off"),
    ("update connector set trust = 'custom'", "NOT_ALLOWED:connector_trust"),
    ("update connector set trust = 'partner'", "NOT_ALLOWED:connector_trust"),  # no contract test yet
])
async def test_kill_switch_and_trust_block_ai_and_staff(world, owner_engine, stmt, expect):
    d = await drafted(world, owner_engine)
    await sql(owner_engine, stmt)
    await sql(owner_engine, "update sandbox set send_mode = 'auto'")
    for who in (None, "nv1"):
        res = await send(world, d, staff=who)
        assert res.status == "blocked" and expect in codes(res), (who, codes(res))
    assert await rows(world, m.Outbox) == []


# --- idempotency and scope -------------------------------------------------------------------------
async def test_one_draft_one_message(world, owner_engine):
    d = await drafted(world, owner_engine)
    first = await send(world, d, staff="nv1")
    again = await send(world, d, staff="nv1")
    assert first.status == again.status == "ok" and again.replayed and first.action_id == again.action_id
    assert len(await rows(world, m.Outbox)) == 1


async def test_tool_refuses_other_principals_and_foreign_drafts(world, owner_engine):
    from dataclasses import replace

    from ob_support import ctx_for

    from cortex_leads.core.context import SystemPrincipal
    from cortex_leads.tools.registry import default_registry

    d = await drafted(world, owner_engine)
    ctx = replace(ctx_for(world, d), principal=SystemPrincipal("cron"))
    async with tenant_session(world.t.id) as s:
        res = await default_registry().execute(ctx, s, "send_message", {"draft_id": str(d.id)},
                                               allowlist=["send_message"], effect_ceiling="customer")
        assert res.status == "blocked" and codes(res) == {"NOT_ALLOWED:principal"}
        res = await default_registry().execute(ctx_for(world, d), s, "send_message", {"draft_id": str(d.id)},
                                               allowlist=["send_message"], effect_ceiling="internal")
        assert res.status == "blocked" and res.violations[0].code == "EFFECT_CEILING"
        res = await default_registry().execute(ctx_for(world, d), s, "send_message", {"draft_id": str(d.id)},
                                               allowlist=["read_messages"], effect_ceiling="customer")
        assert res.violations[0].code == "NOT_ALLOWED"
    assert await rows(world, m.Outbox) == []
