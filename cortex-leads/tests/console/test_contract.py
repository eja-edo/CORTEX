"""DESIGN §5.13 as a contract: whatever a console endpoint returns, an instant is `…Z` and a day is `YYYY-MM-DD`.
The walk is generic, so a new field cannot slip in with its own format."""
import re
from datetime import UTC, datetime, timedelta

from support import sign_in
from wp5_support import rows

from cortex_leads.db import models as m

INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def walk(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, node


def assert_contract(payload):
    seen = 0
    for path, v in walk(payload):
        key = path.rsplit(".", 1)[-1]
        if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", v):
            assert INSTANT.match(v), f"{path} = {v!r} is an instant but not UTC `Z` whole seconds"
            seen += 1
        elif isinstance(v, str) and key.endswith("_at"):
            raise AssertionError(f"{path} = {v!r}: a *_at field must be an instant")
        elif isinstance(v, str) and key in {"promised_date", "for_date"}:
            assert DAY.match(v), f"{path} = {v!r} is a day but not YYYY-MM-DD"
            seen += 1
    return seen


async def test_every_time_the_console_returns_is_utc_z_and_every_day_is_iso(app_client, world, api_key_factory, seed, owner_engine, catalog_factory):
    from sqlalchemy import text
    async with owner_engine.begin() as c:
        await c.execute(text("update conversation set last_customer_at = now() - interval '26 hours', promised_date = current_date + 2"))
        await c.execute(text("update message set occurred_at = now() - interval '26 hours'"))
    start = datetime.now(UTC) + timedelta(days=3)
    await catalog_factory(world.t, code="LH-A", name="Học thử", price=None, category="lich_hoc_thu", valid_until=start, attrs={"suc_chua": 3})
    await seed(m.Booking(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id, contact_id=world.conv.contact_id,
                         slot_code="LH-A", starts_at=start, actor="ai:customer_drafter@1"))
    await seed(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id, status="proposed", text="x",
                       claims=[], reason_code="khong_ro", needs_human=True))
    await seed(m.DecisionLog(tenant_id=world.t.id, conversation_id=world.conv.id, decision="draft_proposed", detail={"skill": "s"}))
    _, key = await api_key_factory(world.t, "owner", None)
    await sign_in(app_client, key)
    total = 0
    for url in ("/api/v1/conversations?filter=all", "/api/v1/conversations?filter=need_human", f"/api/v1/conversations/{world.conv.id}",
                "/api/v1/skills", "/api/v1/sandboxes", "/api/v1/session"):
        r = await app_client.get(url)
        assert r.status_code == 200, url
        total += assert_contract(r.json())
    assert total >= 8  # the walk really met instants and days


async def test_a_booking_is_the_same_instant_as_every_other_time_not_an_offset_in_the_businesss_zone(app_client, world, api_key_factory, seed, catalog_factory):
    start = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # 19:00 in Vietnam
    await seed(m.Booking(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id, contact_id=world.conv.contact_id,
                         slot_code="LH-A", starts_at=start, actor="staff:nv1"))
    _, key = await api_key_factory(world.t, "staff", "nv1")
    await sign_in(app_client, key)
    (b,) = (await app_client.get(f"/api/v1/conversations/{world.conv.id}")).json()["bookings"]
    assert b["at"] == "2026-10-15T12:00:00Z"
    assert [x.starts_at for x in await rows(world, m.Booking)] == [start]


async def test_the_session_tells_the_browser_which_zone_the_business_lives_in(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "staff", "nv1")
    await sign_in(app_client, key)
    assert (await app_client.get("/api/v1/session")).json()["timezone"] == "Asia/Ho_Chi_Minh"
