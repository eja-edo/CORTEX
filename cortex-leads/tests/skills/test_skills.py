import copy
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.domain.pack import load_pack_file
from cortex_leads.skills.loader import SkillError, lint, parse_skill_md, parse_text, sync_dir
from cortex_leads.skills.manifest import SkillManifest
from cortex_leads.skills.profile import load_profile
from cortex_leads.skills.registry import live_skills_for, match, promote, rollback

SKILLS = Path(__file__).resolve().parents[2] / "sandboxes/customer_care/skills"
SILENT = SKILLS / "hoi-lai-khach-im" / "SKILL.md"
PACK = load_pack_file(SKILLS.parent / "domain.yaml")


def _base() -> dict:
    manifest, _ = parse_skill_md(SILENT)
    return manifest.model_dump(mode="json", exclude_unset=True)


def _errs(**changes) -> list[str]:
    data = copy.deepcopy(_base())
    for k, v in changes.items():
        if k == "match":
            data["trigger"]["match"] = v
        elif k == "on":
            data["trigger"]["on"] = v
        else:
            data[k] = v
    return lint(SkillManifest(**data), load_profile("customer_drafter@1"), PACK)


def test_profile_and_samples_lint_clean():
    profile = load_profile("customer_drafter@1")
    assert profile.effect_ceiling == "customer" and profile.max_tool_calls == 4
    for p in SKILLS.glob("*/SKILL.md"):
        manifest, body = parse_skill_md(p)
        assert lint(manifest, profile, PACK) == []
        assert len(re.findall(r"\*\*(?:Ví dụ )?\d", body)) >= (3 if manifest.version < 3 else 6)
        # only the dev-scenario skill may send; the shipped ones stay manual (DESIGN N4)
        assert (manifest.output_kind == "send_to_customer") == (manifest.name in ("thu-nhanh", "tra-loi-khach"))
        assert (manifest.send_policy is None) == (manifest.name in ("thu-nhanh", "tra-loi-khach"))


def test_lint_tool_outside_allowlist():
    assert any("allowlist" in e for e in _errs(requires_tools=["read_messages", "push_sms"]))


def test_lint_bad_duration_is_caught_at_sync_not_runtime():
    assert any("trigger.after" in e for e in _errs(trigger={**_base()["trigger"], "after": "1 day"}))
    assert any("limits.min_gap" in e for e in _errs(limits={"min_gap": "soon"}))


def test_lint_too_many_tools():
    assert any("max 8" in e for e in _errs(requires_tools=[f"t{i}" for i in range(9)]))


def test_lint_on_outside_vocabulary():
    assert any("vocabulary" in e for e in _errs(on="lead.bored"))


def test_lint_or_operator_rejected():
    assert any("equality" in e for e in _errs(match={"$or": [{"intent": "hoi_gia"}]}))
    assert any("equality" in e for e in _errs(match={"intent": "hoi_gia", "$gt": 1}))


def test_lint_match_field_not_allowed():
    assert any("not allowed" in e for e in _errs(match={"owner_staff_ref": "x"}))


def test_lint_output_kind_unknown():
    assert any("output_kind" in e for e in _errs(output_kind="send_to_customer"))


def test_lint_too_many_fields():
    extras = {f"x{i}": 1 for i in range(4)}  # 12 declared + 4 = 16
    assert any("fields" in e for e in _errs(**extras))


def test_parse_errors():
    with pytest.raises(SkillError):
        parse_text("no frontmatter")
    with pytest.raises(SkillError):
        parse_text("---\nname: x\n---\nbody")  # missing required fields


@pytest.fixture
async def env(tenant_factory, sandbox_factory):
    t = await tenant_factory()
    return t, await sandbox_factory(t)


async def _rows(t, sb):
    async with tenant_session(t.id) as s:
        return (await s.execute(select(m.SkillVersion).where(
            m.SkillVersion.sandbox_id == sb.id))).scalars().all()


async def test_sync_dir_idempotent(env):
    t, sb = env
    for _ in range(2):
        async with tenant_session(t.id) as s:
            out = await sync_dir(s, t.id, sb.id, SKILLS)
            assert {r.name for r in out} == {"hoi-lai-khach-im", "hoi-lai-dung-hen", "thu-nhanh", "tra-loi-khach"}
    rows = await _rows(t, sb)
    assert len(rows) == 4 and all(r.status == "draft" for r in rows)


async def test_sync_dir_version_immutable(env, tmp_path):
    t, sb = env
    d = tmp_path / "hoi-lai-khach-im"
    d.mkdir()
    (d / "SKILL.md").write_text(SILENT.read_text(encoding="utf-8"), encoding="utf-8")
    async with tenant_session(t.id) as s:
        await sync_dir(s, t.id, sb.id, tmp_path)
    (d / "SKILL.md").write_text(SILENT.read_text(encoding="utf-8") + "\nsửa lén", encoding="utf-8")
    with pytest.raises(SkillError, match="bump the version"):
        async with tenant_session(t.id) as s:
            await sync_dir(s, t.id, sb.id, tmp_path)


async def test_sync_dir_rejects_lint_failure(env, tmp_path):
    t, sb = env
    d = tmp_path / "hoi-lai-khach-im"
    d.mkdir()
    (d / "SKILL.md").write_text(
        SILENT.read_text(encoding="utf-8").replace("output_kind: draft_for_staff", "output_kind: send"),
        encoding="utf-8")
    with pytest.raises(SkillError, match="output_kind"):
        async with tenant_session(t.id) as s:
            await sync_dir(s, t.id, sb.id, tmp_path)
    assert await _rows(t, sb) == []


async def test_promote_and_rollback_keep_one_live(env, seed):
    t, sb = env
    async with tenant_session(t.id) as s:
        await sync_dir(s, t.id, sb.id, SKILLS)
    # fabricate the next version from the synced row to exercise the lifecycle
    v1 = next(r for r in await _rows(t, sb) if r.name == "hoi-lai-khach-im")
    n0, n1 = v1.version, v1.version + 1
    await seed(m.SkillVersion(tenant_id=t.id, sandbox_id=sb.id, name=v1.name, version=n1,
                              manifest=v1.manifest, body=v1.body, checksum="c3"))
    async with tenant_session(t.id) as s:
        with pytest.raises(SkillError):  # draft cannot jump to live
            await promote(s, sb.id, v1.name, n0, "live")
    async with tenant_session(t.id) as s:
        await promote(s, sb.id, v1.name, n0, "shadow")
        assert await live_skills_for(s, sb.id, "conversation.silent") == []  # shadow is not live
        await promote(s, sb.id, v1.name, n0, "live")
        await promote(s, sb.id, v1.name, n1, "shadow")
        await promote(s, sb.id, v1.name, n1, "live")
    live = [r for r in await _rows(t, sb) if r.status == "live"]
    assert [r.version for r in live] == [n1]
    async with tenant_session(t.id) as s:
        await rollback(s, sb.id, v1.name)
    rows = {(r.version): r.status for r in await _rows(t, sb) if r.name == v1.name}
    assert rows == {n0: "live", n1: "retired"}
    async with tenant_session(t.id) as s:
        assert [x.version for x in await live_skills_for(s, sb.id, "conversation.silent")] == [n0]
        assert await live_skills_for(s, sb.id, "customer.message") == []


_V = {"hoi-lai-khach-im": 4, "hoi-lai-dung-hen": 3}  # live version of each follow-up skill

async def test_match_equality_only(env):
    t, sb = env
    async with tenant_session(t.id) as s:
        await sync_dir(s, t.id, sb.id, SKILLS)
        for n in ("hoi-lai-khach-im", "hoi-lai-dung-hen"):
            await promote(s, sb.id, n, _V[n], "shadow")
            await promote(s, sb.id, n, _V[n], "live")
        silent = (await live_skills_for(s, sb.id, "conversation.silent"))[0]
        promised = (await live_skills_for(s, sb.id, "conversation.promised_date_reached"))[0]
    assert match(silent, SimpleNamespace(intent="hoi_gia", channel_kind="web", state="open"))
    assert not match(silent, SimpleNamespace(intent="khac", channel_kind="web", state="open"))
    assert match(promised, SimpleNamespace(intent=None, channel_kind="web", state="open"))
