"""QA (Agent B): (1) R136, the AI's chosen name against what a customer is sent; (2) erasing a customer after a real run of the runner,
then looking for what is left anywhere in the database."""
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "console"))
from ob_support import configure, run, sql
from support import h, sign_in
from wp5_support import rows

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

NEEDLES = ["0901 234 567", "0901234567", "901234567", "Nguyễn Văn An", "em là An", "giá bao nhiêu", "contact-conv-1", "conv-1"]


async def scan(owner_engine, tables_skip=(), *needles):
    out = {}
    async with owner_engine.connect() as c:
        tables = [r[0] for r in await c.execute(text("select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE' and table_name<>'alembic_version'"))]
        for t in tables:
            if t in tables_skip:
                continue
            for n in needles:
                k = (await c.execute(text(f'select count(*) from "{t}" where "{t}"::text ilike :n'), {"n": f"%{n}%"})).scalar_one()
                if k:
                    out[f"{t}:{n}"] = k
    return out


@pytest.fixture
async def owner(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "owner", None)
    return app_client, h(await sign_in(app_client, key))


async def test_the_name_the_owner_gave_the_ai_is_the_name_the_customer_is_told(world, owner_engine, owner):
    client, hd = owner
    r = await client.put("/api/v1/settings/business", json={"name": "Trung tâm Minh Khai", "timezone": "Asia/Ho_Chi_Minh",
                                                              "hours": {"start": "00:00", "end": "23:59"}, "ai_name": "Mai"}, headers=hd)
    assert r.status_code == 200 and r.json()["disclosure"] == "Trợ lý AI Mai của Trung tâm Minh Khai"
    await configure(world, owner_engine, mode="auto")
    await run(world)
    (ob,) = await rows(world, m.Outbox)
    assert ob.disclosure == "Trợ lý AI Mai của Trung tâm Minh Khai"


async def test_what_a_customer_is_sent_today_is_still_a_true_ai_line(world, owner_engine, owner):
    """The consequence of R136 is a mismatch with the screen, not a missing disclosure: the line is still there and still says AI."""
    client, hd = owner
    await client.put("/api/v1/settings/business", json={"name": "Trung tâm Minh Khai", "timezone": "Asia/Ho_Chi_Minh",
                                                         "hours": {"start": "00:00", "end": "23:59"}, "ai_name": "Mai"}, headers=hd)
    await configure(world, owner_engine, mode="auto")
    await run(world)
    (ob,) = await rows(world, m.Outbox)
    assert ob.disclosure == "Trợ lý AI Mai của Trung tâm Minh Khai"  # R136 fixed: the configured name reaches the customer


async def _populate(world, owner_engine):
    await configure(world, owner_engine, mode="auto")  # a real run: draft, outbox, action_log, decision_log, trigger_run ...
    await run(world)
    async with tenant_session(world.t.id) as s:
        conv = await s.get(m.Conversation, world.conv.id)
        contact = await s.get(m.Contact, conv.contact_id)
        contact.phone = "0901234567"
        s.add(m.IngestEvent(tenant_id=world.t.id, connector_id=world.cn.id, external_id="ev1", type="message.created", status="processed",
                            payload={"conversation": {"external_id": "conv-1"}, "contact": {"external_id": contact.external_id, "display_name": "Nguyễn Văn An"},
                                     "text": "em là An, sđt 0901 234 567. giá bao nhiêu"}))
    await sql(owner_engine, "update contact set external_id = 'contact-conv-1' where id = (select contact_id from conversation limit 1)")


async def test_after_an_erase_no_table_holds_the_customers_words_name_number_or_platform_id(world, owner_engine, owner):
    client, hd = owner
    await _populate(world, owner_engine)
    before = await scan(owner_engine, (), *NEEDLES)
    assert before, "the world holds the personal data to begin with"
    r = await client.post(f"/api/v1/customers/{world.conv.id}/erase", json={"confirm": True}, headers=hd)
    assert r.status_code == 200, r.text
    left = await scan(owner_engine, (), *NEEDLES)
    print("\nBEFORE erase:", sorted(before))
    print("AFTER erase :", sorted(left))
    assert left == {}, left


async def test_the_erase_line_in_the_trail_and_the_answer_hold_no_personal_data(world, owner_engine, owner):
    client, hd = owner
    await _populate(world, owner_engine)
    r = await client.post(f"/api/v1/customers/{world.conv.id}/erase", json={"confirm": True}, headers=hd)
    blob = r.text + "".join(f"{e.summary}{e.metadata_}{e.object_label}" for e in await rows(world, m.AuditEvent))
    for n in NEEDLES:
        assert n not in blob
    ev = [e for e in await rows(world, m.AuditEvent) if e.action == "customer.erased"]
    assert len(ev) == 1


async def test_nothing_goes_out_to_the_customer_after_an_erase(world, owner_engine, owner):
    client, hd = owner
    await _populate(world, owner_engine)
    await client.post(f"/api/v1/customers/{world.conv.id}/erase", json={"confirm": True}, headers=hd)
    ob = await rows(world, m.Outbox)
    assert ob and all(o.status in ("cancelled", "sent", "failed") for o in ob), [o.status for o in ob]
    async with tenant_session(world.t.id) as s:
        c = await s.get(m.Contact, (await s.get(m.Conversation, world.conv.id)).contact_id)
        assert c.opted_out is True and c.phone is None and c.display_name is None


async def test_an_erase_is_refused_while_a_message_is_being_sent_and_changes_nothing(world, owner_engine, owner):
    client, hd = owner
    await _populate(world, owner_engine)
    await sql(owner_engine, "update outbox set status='sending'")
    r = await client.post(f"/api/v1/customers/{world.conv.id}/erase", json={"confirm": True}, headers=hd)
    assert r.status_code == 409
    assert (await scan(owner_engine, (), "0901234567")) != {}
    assert [e for e in await rows(world, m.AuditEvent) if e.action == "customer.erased"] == []


async def test_the_erase_needs_an_explicit_yes_and_the_export_is_logged(world, owner_engine, owner):
    client, hd = owner
    await _populate(world, owner_engine)
    assert (await client.post(f"/api/v1/customers/{world.conv.id}/erase", json={}, headers=hd)).status_code == 422
    assert (await client.post(f"/api/v1/customers/{world.conv.id}/erase", json={"confirm": False}, headers=hd)).status_code == 422
    r = await client.get(f"/api/v1/customers/{world.conv.id}/export")
    assert r.status_code == 200 and "0901234567" in r.text
    ev = [e for e in await rows(world, m.AuditEvent) if e.action == "customer.exported"]
    assert len(ev) == 1 and "0901" not in f"{ev[0].summary}{ev[0].metadata_}"
