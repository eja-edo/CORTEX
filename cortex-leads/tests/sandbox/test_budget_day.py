"""DESIGN §5.13: a day's budget runs from the business's midnight, so "today" means what the owner means."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from wp5_support import NOW, world  # noqa: F401

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.sandbox.policy import check_budget


async def run_at(w, when):
    async with tenant_session(w.t.id) as s:
        s.add(m.TriggerRun(tenant_id=w.t.id, sandbox_id=w.sb.id, skill_name="x", skill_version=1, profile="customer_drafter",
                           profile_version=1, event_type="conversation.silent", status="ok", blocked_codes=[], started_at=when))


async def one_run_a_day(w):
    async with tenant_session(w.t.id) as s:
        await s.execute(update(m.Sandbox).values(budget={"runs_per_day": 1, "drafts_per_staff_per_day": 20, "tokens_per_day": 10**6}))


async def denied(w, now):
    async with tenant_session(w.t.id) as s:
        sb = (await s.execute(m.Sandbox.__table__.select())).first()
        return await check_budget(s, await s.get(m.Sandbox, sb.id), "runs", now)


async def test_a_run_after_the_business_midnight_counts_as_today(world):
    await one_run_a_day(world)
    # NOW is 10:00 on 12/10 in Vietnam. 18:00 UTC on 11/10 is 01:00 on 12/10 there: that is today, not yesterday.
    await run_at(world, NOW.replace(day=11, hour=18))
    v = await denied(world, NOW)
    assert v is not None and v.code.value == "BUDGET"


async def test_a_run_before_the_business_midnight_is_yesterdays(world):
    await one_run_a_day(world)
    await run_at(world, NOW.replace(day=11, hour=16))  # 23:00 on 11/10 in Vietnam
    assert await denied(world, NOW) is None


async def test_the_budget_resets_at_the_business_midnight_not_at_seven_in_the_morning(world):
    await one_run_a_day(world)
    await run_at(world, datetime(2026, 10, 12, 1, 0, tzinfo=UTC))  # 08:00 in Vietnam
    assert await denied(world, datetime(2026, 10, 12, 16, 0, tzinfo=UTC)) is not None  # 23:00 same day: still counted
    assert await denied(world, datetime(2026, 10, 12, 17, 30, tzinfo=UTC) + timedelta(0)) is None  # 00:30 next day: a new day
