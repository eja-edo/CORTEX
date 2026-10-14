import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from wp5_support import World

from cortex_leads.db import models as m
from cortex_leads.db.session import supervisor_session


async def runs(w, seed, n, **kw):
    for _ in range(n):
        base = dict(tenant_id=w.t.id, sandbox_id=w.sb.id, skill_name="s", skill_version=1,
                    profile="customer_drafter", profile_version=1, event_type="conversation.silent",
                    status="ok", blocked_codes=[])
        base.update(kw)
        await seed(m.TriggerRun(**base))


async def test_summary_counts_and_hides_small_groups(app_client, world, api_key_factory, seed):
    await runs(world, seed, 6, status="none", act="none")
    await runs(world, seed, 5, status="ok", act="draft", staff_outcome="sent")
    await runs(world, seed, 2, status="blocked", act="draft", blocked_codes=["UNVERIFIED_CLAIM"])
    _, key = await api_key_factory(world.t, "supervisor", None)
    r = await app_client.get("/supervisor/summary?since=2020-01-01T00:00:00", headers={"X-Api-Key": key})
    assert r.status_code == 200
    j = r.json()
    assert j["runs"] == 13 and j["status"] == {"none": 6, "ok": 5, "blocked": None}
    assert j["act"] == {"none": 6, "draft": 7} and j["blocked_codes"] == {"UNVERIFIED_CLAIM": None}
    assert j["staff_outcome"] == {"sent": 5} and j["outcome_rates"] == {"sent": 1.0}
    assert j["silent_rate"] == pytest.approx(6 / 13, abs=1e-3)


async def test_tiny_population_is_fully_hidden(app_client, world, api_key_factory, seed):
    await runs(world, seed, 3, status="none", act="none")
    _, key = await api_key_factory(world.t, "supervisor", None)
    j = (await app_client.get("/supervisor/summary?since=2020-01-01T00:00:00",
                              headers={"X-Api-Key": key})).json()
    assert j["runs"] is None and j["silent_rate"] is None and j["status"] == {"none": None}


async def test_no_free_text_in_response_and_roles(app_client, world, api_key_factory, seed, message_factory):
    await message_factory(world.conv, "Bí mật của khách 0901234567")
    await runs(world, seed, 6, status="none", act="none")
    _, key = await api_key_factory(world.t, "supervisor", None)
    r = await app_client.get("/supervisor/summary?since=2020-01-01T00:00:00", headers={"X-Api-Key": key})
    assert "Bí mật" not in r.text and "0901" not in json.dumps(r.json())
    _, staff = await api_key_factory(world.t, "staff")
    assert (await app_client.get("/supervisor/summary", headers={"X-Api-Key": staff})).status_code == 403
    assert (await app_client.get("/supervisor/summary")).status_code == 401


async def test_supervisor_role_cannot_read_text_tables(world):
    async with supervisor_session(world.t.id) as s:
        for q in ("select text from draft", "select text from message", "select job_id from trigger_run"):
            with pytest.raises(DBAPIError):
                async with s.begin_nested():
                    await s.execute(text(q))


async def test_other_tenant_runs_not_counted(app_client, world, api_key_factory, seed, tenant_factory,
                                             sandbox_factory):
    other = await tenant_factory("B")
    osb = await sandbox_factory(other)
    await runs(World(other, osb, None, None), seed, 7, status="none", act="none")
    await runs(world, seed, 5, status="none", act="none")
    _, key = await api_key_factory(world.t, "supervisor", None)
    j = (await app_client.get("/supervisor/summary?since=2020-01-01T00:00:00",
                              headers={"X-Api-Key": key})).json()
    assert j["runs"] == 5
