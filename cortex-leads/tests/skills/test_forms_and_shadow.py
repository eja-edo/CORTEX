"""WP22: skills from a form, and the shadow stage they go through before they can reach a customer."""
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from wp5_support import GOOD_DRAFT, NOW, gateway, make_job, reply, rows, run_one

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.skills.forms import (
    MIN_SHADOW_RUNS,
    PREFIX,
    FormSpec,
    go_live,
    preview,
    save_draft,
    shadow_runs,
    start_trial,
)
from cortex_leads.skills.loader import SkillError
from cortex_leads.skills.registry import retire

SPEC = dict(template="khach_im", slug="nhac-gia", description="Hỏi lại khách đã hỏi giá rồi im lặng quá nửa ngày",
            instructions="Nhắc nhẹ, nêu đúng một lợi ích của khoá khách đang quan tâm, không thúc ép chốt.",
            after_hours=4, intent="hoi_gia", max_touches=1)


def spec(**kw) -> FormSpec:
    return FormSpec(**{**SPEC, **kw})


async def draft_skill(w, **kw) -> m.SkillVersion:
    async with tenant_session(w.t.id) as s:
        return await save_draft(s, w.t.id, w.sb.id, spec(**kw))


async def trial(w, **kw) -> m.SkillVersion:
    row = await draft_skill(w, **kw)
    async with tenant_session(w.t.id) as s:
        await start_trial(s, w.sb.id, row.name, row.version)
    return row


# --- the form ----------------------------------------------------------------------------------
def test_the_form_cannot_name_tools_a_send_policy_or_a_shipped_skill():
    for bad in ({"slug": "Hoi Lai"}, {"slug": "x"}, {"requires_tools": ["send_message"]}, {"send_policy": {"mode": "auto"}},
                {"output_kind": "send_to_customer"}, {"instructions": "ngắn"}, {"max_touches": 9}, {"after_hours": 1}):
        with pytest.raises(ValidationError):
            spec(**bad)
    assert spec().name == PREFIX + "nhac-gia"


async def test_a_saved_form_skill_is_a_safe_draft_and_extends_the_house_rules(world):
    row = await draft_skill(world, never_say=["giá sốc", "  "], must_handoff=["bảo hành"],
                            examples=[{"khach": "để em xem", "tra_loi": "Dạ vâng ạ, khi nào mình tiện em gửi lại lịch."}])
    man = row.manifest
    assert (row.name, row.version, row.status) == ("tuy-chinh-nhac-gia", 1, "draft")
    assert man["requires_tools"] == ["read_messages", "read_contact", "lookup_catalog", "draft_followup"]
    assert man["output_kind"] == "draft_for_staff" and man["send_policy"]["mode"] == "manual"
    assert man["trigger"] == {"kind": "relative", "on": "conversation.silent", "after": "4h", "match": {"intent": "hoi_gia"}}
    assert "giá sốc" in man["never_say"] and "kính gửi" in man["never_say"] and len(man["never_say"]) > 20  # added to, not replaced
    assert man["must_handoff"][-1] == "bảo hành" and "giảm giá" in man["must_handoff"]
    assert "Cách làm của doanh nghiệp" in row.body and "để em xem" in row.body and "customer_data" in row.body


async def test_each_save_is_a_new_immutable_version(world):
    a = await draft_skill(world)
    b = await draft_skill(world, instructions="Cách khác: hỏi khách còn phân vân điểm nào của khoá học.")
    assert (a.version, b.version) == (1, 2) and a.checksum != b.checksum
    assert [v.status for v in await rows(world, m.SkillVersion) if v.name == a.name] == ["draft", "draft"]


async def test_lint_errors_are_reported_and_nothing_is_saved(world):
    async with tenant_session(world.t.id) as s:
        errs = await preview(s, world.sb.id, spec(intent="khong-co-trong-goi"))
    assert any("not in the domain pack" in e for e in errs)
    with pytest.raises(SkillError):
        await draft_skill(world, intent="khong-co-trong-goi")
    assert not [v for v in await rows(world, m.SkillVersion) if v.name.startswith(PREFIX)]


async def test_dung_hen_template_has_no_after_and_fires_on_the_promised_date(world):
    row = await draft_skill(world, template="dung_hen", slug="nhac-hen", intent=None)
    assert row.manifest["trigger"] == {"kind": "relative", "on": "conversation.promised_date_reached",
                                       "after": None, "match": {}}


# --- the lifecycle ------------------------------------------------------------------------------
async def test_a_draft_cannot_jump_to_live_and_going_live_needs_enough_trial_runs(world):
    row = await draft_skill(world)
    async with tenant_session(world.t.id) as s:
        with pytest.raises(SkillError):
            await go_live(s, world.sb.id, row.name, row.version)  # not even on trial yet
        await start_trial(s, world.sb.id, row.name, row.version)
        with pytest.raises(SkillError, match="needs 10 trial runs"):
            await go_live(s, world.sb.id, row.name, row.version)
        for _ in range(MIN_SHADOW_RUNS):
            s.add(m.TriggerRun(tenant_id=world.t.id, sandbox_id=world.sb.id, skill_name=row.name, skill_version=1,
                               profile="customer_drafter", profile_version=1, event_type="conversation.silent",
                               status="ok", blocked_codes=[]))
        await s.flush()
        assert await shadow_runs(s, world.sb.id, row.name, 1) == MIN_SHADOW_RUNS
        assert (await go_live(s, world.sb.id, row.name, 1)).status == "live"
        assert (await retire(s, world.sb.id, row.name, 1)).status == "retired"


# --- the trial ----------------------------------------------------------------------------------
async def shadow_job(w, name):
    return next(j for j in await rows(w, m.FollowupJob) if j.skill_name == name)


async def test_a_trial_runs_beside_the_live_skill_and_writes_a_draft_nobody_is_shown(world):
    skill = await trial(world)
    live_job = await make_job(world)
    assert live_job.skill_name == "hoi-lai-khach-im"  # the live skill keeps its job
    job = await shadow_job(world, skill.name)
    assert job.dedupe_key.startswith("shadow:") and job.skill_version == 1
    gw, _ = gateway(reply({**GOOD_DRAFT, "facts": [{"kind": "need", "value": {"text": "x"}, "evidence": ["m1"]}]}))
    run = await run_one(world, gw, job)
    assert (run.status, run.act, run.skill_name) == ("ok", "draft", skill.name)
    (d,) = [x for x in await rows(world, m.Draft) if x.run_id == run.id]
    assert d.status == "shadow" and d.text == GOOD_DRAFT["text"]
    assert not await rows(world, m.Outbox) and not await rows(world, m.Notification)
    assert not await rows(world, m.ContactFact)  # a trial does not write the customer's memory
    assert "shadow_draft" in [x.decision for x in await rows(world, m.DecisionLog)]
    async with tenant_session(world.t.id) as s:
        assert (await s.get(m.Conversation, world.conv.id)).touches == 0
        assert not (await s.execute(select(m.Draft).where(m.Draft.status == "proposed"))).first()  # not in the queue


async def test_a_trial_draft_goes_through_the_same_validator(world):
    skill = await trial(world)
    await make_job(world)
    bad = {**GOOD_DRAFT, "text": "Khoá IELTS giá 1.000.000đ thôi chị ơi, đăng ký liền nha"}
    run = await run_one(world, gateway(reply(bad))[0], await shadow_job(world, skill.name))
    assert run.status == "blocked" and "UNVERIFIED_CLAIM" in run.blocked_codes
    assert [d.status for d in await rows(world, m.Draft) if d.run_id == run.id] == ["blocked"]


async def test_a_retired_or_draft_skill_gets_no_job_and_trials_do_not_count_against_the_staff_cap(world):
    draft = await draft_skill(world)
    await make_job(world)
    assert not [j for j in await rows(world, m.FollowupJob) if j.skill_name == draft.name]  # a draft hears nothing
    from cortex_leads.triggers.select import select_jobs
    async with tenant_session(world.t.id) as s:
        s.add(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id, status="shadow",
                      text="x", claims=[], reason_code="khong_ro"))
        await s.execute(update(m.Sandbox).values(budget={"runs_per_day": 100, "drafts_per_staff_per_day": 1, "tokens_per_day": 10**6}))
        sb = (await s.execute(select(m.Sandbox))).scalar_one()
        chosen = await select_jobs(s, sb, NOW + timedelta(minutes=1))
    assert len(chosen) == 1  # the shadow draft did not use up the cap of 1
