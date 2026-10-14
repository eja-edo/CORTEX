from datetime import UTC, datetime, timedelta

from cortex_leads.core.envelope import BlockedCode
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.sandbox.policy import check_budget, is_paused, requires_sandbox

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)


def test_requires_sandbox():
    assert not requires_sandbox({})
    assert not requires_sandbox({"touches_customer_data": False})
    for k in ("touches_customer_data", "untrusted_input", "customer_channel", "external_mcp"):
        assert requires_sandbox({k: True})


async def _run(seed, t, sb, started, tokens=0):
    await seed(m.TriggerRun(tenant_id=t.id, sandbox_id=sb.id, skill_name="s", skill_version=1,
                            profile="p", profile_version=1, event_type="conversation.silent", status="ok",
                            started_at=started, tokens_in=tokens))


async def test_budget_runs_exhausted(tenant_factory, sandbox_factory, seed):
    t = await tenant_factory()
    sb = await sandbox_factory(t, budget={"runs_per_day": 2, "drafts_per_staff_per_day": 5,
                                          "tokens_per_day": 100})
    async with tenant_session(t.id) as s:
        assert await check_budget(s, sb, "runs", NOW) is None
    await _run(seed, t, sb, NOW - timedelta(hours=1), tokens=60)
    await _run(seed, t, sb, NOW - timedelta(hours=2), tokens=60)
    await _run(seed, t, sb, NOW - timedelta(days=2))  # yesterday does not count
    async with tenant_session(t.id) as s:
        v = await check_budget(s, sb, "runs", NOW)
        assert v is not None and v.code == BlockedCode.BUDGET
        v = await check_budget(s, sb, "tokens", NOW)
        assert v is not None and v.code == BlockedCode.BUDGET
        assert await check_budget(s, sb, "drafts", NOW) is None


async def test_missing_cap_denies(tenant_factory, sandbox_factory):
    t = await tenant_factory()
    sb = await sandbox_factory(t, budget={})
    async with tenant_session(t.id) as s:
        v = await check_budget(s, sb, "runs", NOW)
        assert v is not None and v.code == BlockedCode.BUDGET


async def test_paused_sandbox(tenant_factory, sandbox_factory):
    t = await tenant_factory()
    sb = await sandbox_factory(t, status="paused")
    assert is_paused(sb)
    async with tenant_session(t.id) as s:
        v = await check_budget(s, sb, "runs", NOW)
        assert v is not None and v.code == BlockedCode.PAUSED
