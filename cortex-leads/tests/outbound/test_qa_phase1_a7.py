"""QA (Agent B), phase 1: importing a new price (a new catalog version) must not let a draft written with the old price reach a customer
through the AI's own send path (A7), and the old version stays as history."""
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "console"))
from ob_support import configure, send, sql
from ob_support import run as _run
from wp5_support import rows

from cortex_leads.catalog.importer import import_catalog
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session


async def test_a_price_imported_after_the_draft_blocks_the_ai_send_and_the_old_version_stays(world, owner_engine):
    await configure(world, owner_engine, mode="manual")
    await _run(world)
    (d,) = await rows(world, m.Draft)
    await sql(owner_engine, "update sandbox set send_mode = 'auto'")
    async with tenant_session(world.t.id) as s:
        (item,) = (await s.execute(text("select code, name, category, price, unit from catalog_item where active")  )).all()[:1]
        code, name, cat, price, unit = item
        r = await import_catalog(s, world.t.id, f"code,name,category,price,unit,valid_until\n{code},{name},{cat or ''},{int(price) + 1000},{unit or ''},\n")
    assert r.changed == 1
    res = await send(world, d)
    assert res.status == "blocked" and any(v.code == "UNVERIFIED_CLAIM" for v in res.violations)
    assert await rows(world, m.Outbox) == []
    async with owner_engine.connect() as c:
        got = (await c.execute(text("select version, active, price from catalog_item where code = :c order by version"), {"c": code})).all()
    assert [(v, a) for v, a, _ in got] == [(1, False), (2, True)] and float(got[0][2]) == float(price)
