"""WP32: a sandbox kind is one registry entry; every place that used to keep its own table reads it."""
import argparse
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from cortex_leads import cli
from cortex_leads.console.sandboxes import PURPOSE_LABELS, TEMPLATES
from cortex_leads.cron.runner import cron_once
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.sandbox.bringup import create_sandbox
from cortex_leads.sandbox.kinds import KINDS, SandboxKind
from cortex_leads.skills.profile import SANDBOXES_DIR, load_profile, template_dir


@pytest.mark.parametrize("kind", [k for k in KINDS.values() if k.profile], ids=lambda k: k.purpose)
def test_every_real_kind_has_its_profile_and_folder(kind):
    assert load_profile(kind.profile).id == kind.profile.split("@")[0]
    assert (SANDBOXES_DIR / kind.directory).is_dir()
    assert isinstance(kind.jobs(), list)


def test_the_console_cards_and_labels_come_from_the_registry():
    assert [t["id"] for t in TEMPLATES] == [k.purpose for k in KINDS.values() if k.listed]
    assert "lesson_recap" not in {t["id"] for t in TEMPLATES}  # needs a folder connected: command line for now
    assert PURPOSE_LABELS["lesson_recap"] == "Tổng kết buổi học"
    student = next(t for t in TEMPLATES if t["id"] == "student_care")
    assert student["available"] is False and "chờ trung tâm" in student["reason"]


def test_the_skill_folder_of_a_sandbox_follows_its_purpose_not_its_name():
    assert template_dir(m.Sandbox(name="Cơ sở 2", purpose="lesson_recap")) == "lesson_recap"
    assert template_dir(m.Sandbox(name="khác", purpose="khong_co")) == "khác"  # unknown purpose: the old fallback


async def test_a_kind_added_to_the_registry_gets_its_cron_job_with_no_other_edit(tenant_factory, seed, monkeypatch):
    ran = []

    async def job(session, sandbox, tz, now, slot):
        ran.append(sandbox.purpose)

    toy = SandboxKind("toy", "Đồ chơi", "", "digest_template@1", "owner_digest", jobs=lambda: [(lambda now, tz: now.date(), job)])
    monkeypatch.setitem(KINDS, "toy", toy)
    t = await tenant_factory()
    await seed(m.Sandbox(tenant_id=t.id, name="toy", purpose="toy", profile_ref="digest_template@1"))
    await cron_once(datetime(2026, 10, 12, 3, 0, tzinfo=UTC))
    assert ran == ["toy"]


async def test_the_command_line_brings_a_lesson_sandbox_up_with_its_skill_live(tenant_factory):
    t = await tenant_factory()
    await cli.cmd_create_sandbox(argparse.Namespace(tenant=t.id, purpose="lesson_recap", name=None))
    async with tenant_session(t.id) as s:
        sb = (await s.execute(select(m.Sandbox))).scalar_one()
        skills = (await s.execute(select(m.SkillVersion))).scalars().all()
    assert (sb.purpose, sb.profile_ref) == ("lesson_recap", "lesson_recapper@1")
    assert [(k.name, k.status) for k in skills] == [("tom-tat-buoi-hoc", "live")]


async def test_a_new_tenant_comes_up_with_its_customer_care_skills_live_and_the_trial_one_left_off(tenant_factory):
    """`create-tenant` once made an empty sandbox: the Skills page was empty and the AI had nothing to do."""
    from cortex_leads.core.ids import uuid7
    from cortex_leads.db.session import system_session
    tid = uuid7()
    async with system_session() as s:
        s.add(m.Tenant(id=tid, name="Mới"))
    from sqlalchemy import select as sel
    async with tenant_session(tid) as s:
        await create_sandbox(s, tid, KINDS["customer_care"], name="customer_care")
    async with tenant_session(tid) as s:
        got = {(v.name, v.status) for v in (await s.execute(sel(m.SkillVersion))).scalars()}
    live = {n for n, st in got if st == "live"}
    assert {"tra-loi-khach", "hoi-lai-khach-im", "hoi-lai-dung-hen"} <= live
    assert ("thu-nhanh", "draft") in got and "thu-nhanh" not in live


async def _purposes(tid) -> list[str]:
    async with tenant_session(tid) as s:
        return sorted((await s.execute(select(m.Sandbox.purpose))).scalars())


READY = ["classroom_grader", "customer_care", "lesson_recap", "owner_digest"]


async def test_a_new_tenant_has_every_kind_that_can_run_with_its_skills_live(capsys):
    await cli.cmd_create_tenant(argparse.Namespace(name="Mới", timezone="Asia/Ho_Chi_Minh"))
    tid = UUID(capsys.readouterr().out.split("tenant_id=")[1].split()[0])
    assert await _purposes(tid) == READY  # student_care is not open yet
    async with tenant_session(tid) as s:
        live = set((await s.execute(select(m.SkillVersion.name).where(m.SkillVersion.status == "live"))).scalars())
    assert {"tra-loi-khach", "tom-tat-buoi-hoc", "cham-bai", "soan-bai-tap"} <= live


async def test_ensure_sandboxes_fills_in_an_old_tenant_and_changes_nothing_the_second_time(capsys, tenant_factory):
    t = await tenant_factory()
    async with tenant_session(t.id) as s:
        care = await create_sandbox(s, t.id, KINDS["customer_care"], name="cham-soc", title="Tên của chủ")
    await cli.cmd_ensure_sandboxes(argparse.Namespace(tenant=t.id))
    assert await _purposes(t.id) == READY
    capsys.readouterr()
    await cli.cmd_ensure_sandboxes(argparse.Namespace(tenant=t.id))
    assert "created=none" in capsys.readouterr().out
    async with tenant_session(t.id) as s:
        assert (await s.get(m.Sandbox, care.id)).title == "Tên của chủ"


async def test_create_sandbox_answers_with_the_one_already_there_instead_of_a_twin(capsys):
    await cli.cmd_create_tenant(argparse.Namespace(name="Mới", timezone="Asia/Ho_Chi_Minh"))
    tid = UUID(capsys.readouterr().out.split("tenant_id=")[1].split()[0])
    await cli.cmd_create_sandbox(argparse.Namespace(tenant=tid, purpose="lesson_recap", name=None))
    assert await _purposes(tid) == READY
