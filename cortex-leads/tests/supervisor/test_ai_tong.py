"""WP21 AI tổng: metadata in (cl_supervisor), proposals out, a person decides. The LLM summary may only
repeat numbers it was given."""
import json
from datetime import UTC, datetime, timedelta

from wp5_support import NOW, gateway, reply, rows

from cortex_leads.core.ids import uuid7
from cortex_leads.cron.runner import cron_once
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.supervisor.proposals import decide
from cortex_leads.supervisor.signals import MIN_N, read_findings, record

REAL = datetime.now(UTC)  # trigger_run.started_at defaults to the DB clock, so the window is the real one



def weekly(digests):  # the monthly digest is a second row on the first run of a month
    return [d for d in digests if d.kind == "weekly"]


async def runs(w, seed, n, *, skill="s", ver=2, **kw):
    for _ in range(n):
        await seed(m.TriggerRun(**{**dict(
            tenant_id=w.t.id, sandbox_id=w.sb.id, skill_name=skill, skill_version=ver, profile="customer_drafter",
            profile_version=1, event_type="conversation.silent", status="ok", blocked_codes=[]), **kw}))


async def versions(w, seed, skill="s", live=2, older=(1,)):
    for v in older:
        await seed(m.SkillVersion(tenant_id=w.t.id, sandbox_id=w.sb.id, name=skill, version=v, status="retired",
                                  manifest={}, body="", checksum=f"c{v}"))
    await seed(m.SkillVersion(tenant_id=w.t.id, sandbox_id=w.sb.id, name=skill, version=live, status="live",
                              manifest={}, body="", checksum=f"c{live}"))


async def scan(w, now=REAL):
    found = await read_findings(w.t.id, now)
    async with tenant_session(w.t.id) as s:
        return found, await record(s, w.t.id, found, now)


async def test_blocked_spike_proposes_a_rollback_when_there_is_an_older_version(world, seed):
    await versions(world, seed)
    await runs(world, seed, 4, status="blocked", blocked_codes=["UNVERIFIED_CLAIM"])
    await runs(world, seed, 2, status="blocked", blocked_codes=["FORBIDDEN_PHRASE"])
    await runs(world, seed, 4)
    found, new = await scan(world)
    assert new == 1 and [f.signal for f in found] == ["blocked_spike"]
    (p,) = await rows(world, m.Proposal)
    assert (p.kind, p.signal, p.status, p.target) == ("rollback_skill", "blocked_spike", "pending", {"skill": "s", "version": 2})
    assert p.evidence == {"runs": 10, "blocked": 6, "top_code": "UNVERIFIED_CLAIM"}


async def test_without_an_older_version_the_proposal_is_only_a_review(world, seed):
    await versions(world, seed, older=())
    await runs(world, seed, 6, status="blocked", blocked_codes=["UNVERIFIED_CLAIM"])
    await scan(world)
    assert [p.kind for p in await rows(world, m.Proposal)] == ["review_skill"]


async def test_small_populations_never_fire(world, seed):
    await runs(world, seed, MIN_N - 1, status="blocked", blocked_codes=["UNVERIFIED_CLAIM"])
    assert await scan(world) == ([], 0)


async def test_error_streak_proposes_the_kill_switch_only_for_consecutive_errors(world, seed):
    await runs(world, seed, 3, status="error")
    found, _ = await scan(world)
    assert [(f.signal, f.kind) for f in found] == [("error_streak", "pause_sandbox")]


async def test_a_recovered_skill_has_no_streak(world, seed):
    await runs(world, seed, 2, status="error")
    await runs(world, seed, 1, status="ok")  # the newest run is fine
    assert await read_findings(world.t.id, REAL) == []


async def test_staff_dropping_most_drafts_proposes_a_review(world, seed):
    await runs(world, seed, 4, status="ok", act="draft", staff_outcome="skipped")
    await runs(world, seed, 1, status="ok", act="draft", staff_outcome="sent")
    await scan(world)
    (p,) = await rows(world, m.Proposal)
    assert (p.signal, p.kind, p.evidence) == ("skipped_high", "review_skill", {"decided": 5, "skipped": 4})


async def test_failing_sends_target_the_care_sandbox(world, seed):
    for st in ("refused", "refused", "error", "sent", "sent"):
        await seed(m.Outbox(tenant_id=world.t.id, action_id=uuid7(), conversation_id=world.conv.id,
                            connector_id=world.cn.id, actor="ai:x", text="x", status=st))
    await scan(world)
    (p,) = await rows(world, m.Proposal)
    assert (p.signal, p.kind, p.sandbox_id, p.evidence) == ("outbox_failing", "pause_sandbox", world.sb.id,
                                                            {"sends": 5, "failed": 3})


async def test_open_once_and_stale_when_the_condition_clears(world, seed, owner_engine):
    await runs(world, seed, 3, status="error")
    await scan(world)
    _, new = await scan(world)
    assert new == 0 and len(await rows(world, m.Proposal)) == 1  # not opened twice
    await runs(world, seed, 1, status="ok")
    await scan(world)
    (p,) = await rows(world, m.Proposal)
    assert (p.status, p.decided_by) == ("stale", "system:supervisor")


async def test_evidence_holds_numbers_and_codes_never_customer_words(world, seed, message_factory):
    await message_factory(world.conv, "Bí mật của khách 0901234567")
    await versions(world, seed)
    await runs(world, seed, 6, status="blocked", blocked_codes=["UNVERIFIED_CLAIM"])
    await scan(world)
    blob = json.dumps([(p.target, p.evidence) for p in await rows(world, m.Proposal)], ensure_ascii=False)
    assert "Bí mật" not in blob and "0901" not in blob


# --- a person decides ---------------------------------------------------------------------------
async def open_proposal(w, seed, kind, **kw):
    return await seed(m.Proposal(tenant_id=w.t.id, sandbox_id=w.sb.id, kind=kind, signal="blocked_spike",
                                 target=kw.get("target", {}), evidence={}))


async def test_accepting_a_pause_flips_the_kill_switch_and_leaves_an_audit_row(world, seed):
    p = await open_proposal(world, seed, "pause_sandbox")
    async with tenant_session(world.t.id) as s:
        assert await decide(s, p.id, accept=True, by="staff:chu", now=NOW) == "accepted"
    assert (await rows(world, m.Sandbox))[0].status == "paused"
    (log,) = [a for a in await rows(world, m.ActionLog) if a.tool == "proposal.pause_sandbox"]
    assert log.actor == "staff:chu" and log.status == "accepted"


async def test_accepting_a_rollback_moves_the_live_pointer(world, seed):
    await versions(world, seed)
    p = await open_proposal(world, seed, "rollback_skill", target={"skill": "s", "version": 2})
    async with tenant_session(world.t.id) as s:
        assert await decide(s, p.id, accept=True, by="staff:chu", now=NOW) == "accepted"
    live = [v.version for v in await rows(world, m.SkillVersion) if v.status == "live" and v.name == "s"]
    assert live == [1]


async def test_a_rollback_with_nothing_to_go_back_to_is_stale_and_dismiss_changes_nothing(world, seed):
    await versions(world, seed, older=())
    p = await open_proposal(world, seed, "rollback_skill", target={"skill": "s", "version": 2})
    async with tenant_session(world.t.id) as s:
        assert await decide(s, p.id, accept=True, by="staff:chu", now=NOW) == "stale"
    q = await open_proposal(world, seed, "pause_sandbox")
    async with tenant_session(world.t.id) as s:
        assert await decide(s, q.id, accept=False, by="staff:chu", now=NOW) == "dismissed"
        assert await decide(s, q.id, accept=True, by="staff:chu", now=NOW) == "dismissed"  # decided once
    assert (await rows(world, m.Sandbox))[0].status == "active"


# --- through cron -------------------------------------------------------------------------------
async def owner_sandbox(w, sandbox_factory):
    return await sandbox_factory(w.t, name="owner_digest", purpose="owner_digest", profile_ref="digest_template@1")


def monday_now():
    today = datetime.now(UTC).date()
    return datetime.combine(today + timedelta(days=7 - today.weekday()), datetime.min.time(), tzinfo=UTC) + timedelta(hours=3)


async def test_cron_scans_for_the_owner_sandbox_and_pushes_the_owner(world, seed, sandbox_factory):
    await owner_sandbox(world, sandbox_factory)
    await runs(world, seed, 3, status="error")
    await cron_once(NOW + timedelta(days=0))
    # the cron's own clock is NOW (2026-10-12) but the runs are stamped by the DB clock: scan with the real one
    await cron_once(REAL + timedelta(hours=1))
    assert [p.signal for p in await rows(world, m.Proposal)] == ["error_streak"]
    assert "proposal" in {n.kind for n in await rows(world, m.Notification)}


async def test_no_owner_sandbox_means_no_supervisor(world, seed):
    await runs(world, seed, 3, status="error")
    await cron_once(REAL + timedelta(hours=1))
    assert not await rows(world, m.Proposal)


async def test_weekly_summary_keeps_only_numbers_it_was_given(world, seed, sandbox_factory):
    now = monday_now()
    await owner_sandbox(world, sandbox_factory)
    gw, prov = gateway(reply({"summary": "Tuần này có 1 khách mới và 1 khách đang bị bỏ rơi, nên xem danh sách sáng nay."}))
    await cron_once(now, gw)
    (d,) = weekly(await rows(world, m.Digest))
    assert d.payload["narrative"].startswith("Tuần này có 1 khách mới")
    sent = json.dumps(prov.calls[0]["messages"], ensure_ascii=False)
    assert "Nguyễn" not in sent and "0901" not in sent and "tuan_nay" in sent  # numbers only went out
    (run,) = [r for r in await rows(world, m.TriggerRun) if r.skill_name == "tom-tat-tuan"]
    assert (run.status, run.event_type) == ("ok", "cron.weekly") and run.tokens_in > 0


async def test_a_summary_with_a_number_of_its_own_is_dropped_and_the_digest_survives(world, sandbox_factory):
    await owner_sandbox(world, sandbox_factory)
    gw, _ = gateway(reply({"summary": "Khách mới tăng 250% so với tuần trước, rất tốt, chủ nên ăn mừng thôi."}))
    await cron_once(monday_now(), gw)
    (d,) = weekly(await rows(world, m.Digest))
    assert "narrative" not in d.payload
    (run,) = [r for r in await rows(world, m.TriggerRun) if r.skill_name == "tom-tat-tuan"]
    assert (run.status, run.blocked_codes) == ("blocked", ["UNVERIFIED_CLAIM"])


async def test_llm_failure_or_exhausted_budget_never_loses_the_digest(world, sandbox_factory):
    await owner_sandbox(world, sandbox_factory)
    gw, _ = gateway(reply("not json at all"))
    await cron_once(monday_now(), gw)
    assert len(weekly(await rows(world, m.Digest))) == 1
    assert [r.status for r in await rows(world, m.TriggerRun) if r.skill_name == "tom-tat-tuan"] == ["error"]


# --- strategy cards (thẻ chiến lược): a structured change, tried before it is believed ---------------
async def live_skill(w, seed, name="hoi-lai-khach-im"):
    """The shipped follow-up skill the world already has live (max_touches 3, after 20h)."""
    return next(v for v in await rows(w, m.SkillVersion) if v.name == name and v.status == "live")


async def skip_most_drafts(w, seed, skill="hoi-lai-khach-im", ver=4):
    await runs(w, seed, 4, skill=skill, ver=ver, status="ok", act="draft", staff_outcome="skipped")
    await runs(w, seed, 1, skill=skill, ver=ver, status="ok", act="draft", staff_outcome="sent")


async def test_staff_binning_drafts_becomes_a_card_with_one_named_change(world, seed):
    live = await live_skill(world, seed)
    await skip_most_drafts(world, seed)
    await scan(world)
    (p,) = await rows(world, m.Proposal)
    assert p.kind == "tune_skill" and p.signal == "skipped_high"
    assert p.target == {"skill": "hoi-lai-khach-im", "version": live.version,
                        "change": {"field": "limits.max_touches", "from": 3, "to": 2}}
    assert p.evidence == {"decided": 5, "skipped": 4}


async def test_accepting_a_card_puts_a_new_version_on_trial_and_leaves_the_live_one_alone(world, seed):
    live = await live_skill(world, seed)
    await skip_most_drafts(world, seed)
    await scan(world)
    (p,) = await rows(world, m.Proposal)
    async with tenant_session(world.t.id) as s:
        assert await decide(s, p.id, accept=True, by="staff:chu", now=NOW) == "accepted"
    skills = {(v.name, v.version): v for v in await rows(world, m.SkillVersion) if v.name == live.name}
    new = skills[(live.name, live.version + 1)]
    assert new.status == "shadow" and skills[(live.name, live.version)].status == "live"
    assert new.manifest["limits"]["max_touches"] == 2 and new.manifest["version"] == live.version + 1
    assert {**new.manifest["limits"], "max_touches": 3} == live.manifest["limits"]  # exactly one field differs
    assert new.body == live.body


async def test_when_touches_are_already_one_the_card_moves_the_wait_instead(world, seed, owner_engine):
    live = await live_skill(world, seed)
    async with owner_engine.begin() as c:
        from sqlalchemy import text
        await c.execute(text("update skill_version set manifest = jsonb_set(manifest, '{limits,max_touches}', '1') where id = :i"), {"i": live.id})
    await skip_most_drafts(world, seed)
    await scan(world)
    (p,) = await rows(world, m.Proposal)
    assert p.target["change"] == {"field": "trigger.after", "from": "20h", "to": "24h"}


async def test_a_card_for_a_skill_that_moved_on_is_stale_not_applied(world, seed):
    live = await live_skill(world, seed)
    await skip_most_drafts(world, seed)
    await scan(world)
    (p,) = await rows(world, m.Proposal)
    async with tenant_session(world.t.id) as s:
        from cortex_leads.skills.registry import retire
        await retire(s, world.sb.id, live.name, live.version)  # someone switched it off meanwhile
        assert await decide(s, p.id, accept=True, by="staff:chu", now=NOW) == "stale"
    assert not [v for v in await rows(world, m.SkillVersion) if v.name == live.name and v.status == "shadow"]


async def test_a_forged_card_cannot_change_a_field_outside_the_list_or_outside_the_range(world, seed):
    live = await live_skill(world, seed)
    for change in ({"field": "requires_tools", "from": [], "to": ["send_message"]},
                   {"field": "limits.max_touches", "from": 3, "to": 9},
                   {"field": "trigger.after", "from": "20h", "to": "200h"},
                   {"field": "send_policy.mode", "from": "manual", "to": "auto"}):
        p = await seed(m.Proposal(tenant_id=world.t.id, sandbox_id=world.sb.id, kind="tune_skill", signal="x" + change["field"],
                                  target={"skill": live.name, "version": live.version, "change": change}, evidence={}))
        async with tenant_session(world.t.id) as s:
            assert await decide(s, p.id, accept=True, by="staff:chu", now=NOW) == "stale", change
    assert not [v for v in await rows(world, m.SkillVersion) if v.status == "shadow"]


async def test_at_most_three_cards_are_open(world, seed):
    from cortex_leads.skills.registry import promote  # noqa: F401
    for i in range(3):
        await seed(m.Proposal(tenant_id=world.t.id, sandbox_id=world.sb.id, kind="tune_skill", signal=f"other{i}",
                              target={"skill": f"sk{i}"}, evidence={}))
    await skip_most_drafts(world, seed)
    await scan(world)
    mine = [p for p in await rows(world, m.Proposal) if p.signal == "skipped_high"]
    assert [p.kind for p in mine] == ["review_skill"]  # the fourth idea is only a note
