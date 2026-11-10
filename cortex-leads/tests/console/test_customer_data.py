"""WP43: exporting and erasing one customer's data."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from support import h, sign_in
from wp5_support import rows

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)


@pytest.fixture
async def owner(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t, "owner", None)
    return app_client, h(await sign_in(app_client, key))


@pytest.fixture
async def full(world, message_factory):
    """The customer of `world` with everything that can hold their words: a reply, drafts, an edit, a queued send, a fact, a raw event."""
    w = world
    await message_factory(w.conv, "Em muốn học thử, gọi em số 0912 345 678 nhé", occurred_at=NOW - timedelta(hours=25))
    async with tenant_session(w.t.id) as s:
        c = await s.get(m.Conversation, w.conv.id)
        contact = await s.get(m.Contact, c.contact_id)
        contact.phone, contact.decision_maker = "0912345678", "mẹ"
        d1 = m.Draft(tenant_id=w.t.id, sandbox_id=w.sb.id, conversation_id=w.conv.id, status="proposed", text="Chào An, khóa IELTS giá 2.500.000đ", claims=[{"value": 2500000}])
        d2 = m.Draft(tenant_id=w.t.id, sandbox_id=w.sb.id, conversation_id=w.conv.id, status="sent", text="Chào anh An")
        s.add_all([d1, d2])
        await s.flush()
        s.add(m.StaffAction(tenant_id=w.t.id, draft_id=d2.id, action="edited", edited_text="Chào An ạ, em gọi lại sau", staff_ref="nv1"))
        s.add(m.Outbox(tenant_id=w.t.id, action_id=d1.id, conversation_id=w.conv.id, connector_id=w.cn.id, draft_id=d1.id, actor="ai:x",
                       text="Chào An, khóa IELTS giá 2.500.000đ", status="queued", source={"codes": ["KH01"]}, disclosure="Trợ lý AI của Acme"))
        s.add(m.ContactFact(tenant_id=w.t.id, contact_id=contact.id, conversation_id=w.conv.id, kind="phone", value={"phone": "0912345678"}, status="active"))
        s.add(m.FollowupJob(tenant_id=w.t.id, sandbox_id=w.sb.id, conversation_id=w.conv.id, skill_name="hoi-lai-khach-im", skill_version=4,
                            event_type="conversation.silent", dedupe_key="k1"))
        s.add(m.IngestEvent(tenant_id=w.t.id, connector_id=w.cn.id, external_id="ev1", type="message.created", status="processed",
                            payload={"conversation": {"external_id": "conv-1"}, "contact": {"external_id": "contact-conv-1", "display_name": "Nguyễn Văn An"}, "text": "0912 345 678"}))
        s.add(m.IngestEvent(tenant_id=w.t.id, connector_id=w.cn.id, external_id="ev2", type="message.created", status="processed",
                            payload={"conversation": {"external_id": "someone-else"}, "contact": {"external_id": "other"}, "text": "xin chào"}))
    return w


async def test_the_export_holds_what_the_system_knows_and_is_logged_without_a_name(owner, full):
    client, _ = owner
    r = await client.get(f"/api/v1/customers/{full.conv.id}/export")
    assert r.status_code == 200
    data = r.json()
    assert data["contact"]["name"] == "Nguyễn Văn An" and data["contact"]["phone"] == "0912345678"
    assert any("0912 345 678" in x["text"] for x in data["messages"]) and {d["status"] for d in data["drafts"]} == {"proposed", "sent"}
    assert data["facts"][0]["kind"] == "phone"
    ev = [e for e in await rows(full, m.AuditEvent) if e.action == "customer.exported"]
    assert len(ev) == 1 and "Nguyễn" not in ev[0].summary + str(ev[0].metadata_) + str(ev[0].object_label)


async def test_erasing_removes_the_words_the_name_and_the_number_everywhere_they_were_kept(owner, full):
    client, hd = owner
    r = await client.post(f"/api/v1/customers/{full.conv.id}/erase", json={"confirm": True}, headers=hd)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["erased"]["messages"] == 2 and body["erased"]["drafts"] == 2 and body["erased"]["raw_events"] == 1 and body["not_reached"]
    async with tenant_session(full.t.id) as s:
        everything = ""
        for model in (m.Message, m.Draft, m.Outbox, m.ContactFact, m.IngestEvent, m.StaffAction, m.Contact, m.Conversation):
            for row in (await s.execute(select(model))).scalars():
                everything += " ".join(str(v) for k, v in vars(row).items() if not k.startswith("_")) + "\n"
        contact = await s.get(m.Contact, (await s.get(m.Conversation, full.conv.id)).contact_id)
        ev2 = (await s.execute(select(m.IngestEvent).where(m.IngestEvent.external_id == "ev2"))).scalar_one()
    for gone in ("0912", "Nguyễn Văn An", "IELTS giá", "gọi lại sau", "mẹ", "contact-conv-1"):
        assert gone not in everything, gone
    assert contact.display_name is None and contact.phone is None and contact.opted_out is True and contact.external_id.startswith("erased:")
    assert ev2.payload["text"] == "xin chào"  # someone else's event is left alone


async def test_nothing_more_can_reach_the_customer_after_erasure(owner, full):
    client, hd = owner
    await client.post(f"/api/v1/customers/{full.conv.id}/erase", json={"confirm": True}, headers=hd)
    async with tenant_session(full.t.id) as s:
        assert (await s.execute(select(m.Outbox.status))).scalar_one() == "cancelled"
        assert {d.status for d in (await s.execute(select(m.Draft))).scalars()} == {"expired", "sent"}
        assert (await s.execute(select(m.FollowupJob.status))).scalar_one() == "skipped"
        conv = await s.get(m.Conversation, full.conv.id)
        assert conv.next_check_at is None and conv.reply_check_at is None


async def test_a_customer_who_writes_again_is_a_new_contact_that_starts_from_nothing(owner, full):
    import json
    import time

    from cortex_leads.ingest.signing import sign
    client, hd = owner
    await client.post(f"/api/v1/customers/{full.conv.id}/erase", json={"confirm": True}, headers=hd)
    body = json.dumps({"format": "cortex.event/1", "events": [{
        "type": "message.created", "external_id": "after-1", "occurred_at": datetime.now(UTC).isoformat(), "channel": {"kind": "messenger", "account_ref": "p1"},
        "conversation": {"external_id": "conv-1"}, "contact": {"external_id": "contact-conv-1", "display_name": "An"}, "sender": {"role": "customer"},
        "text": "Chào shop"}]}).encode()
    ts = int(time.time())
    r = await client.post("/ingest/v1/events", content=body, headers={"X-Connector-Id": full.cn.id, "X-Timestamp": str(ts),
                                                                       "X-Signature": sign(b"test-connector-secret", ts, body), "Content-Type": "application/json"})
    assert r.status_code == 202, r.text
    async with tenant_session(full.t.id) as s:
        contacts = (await s.execute(select(m.Contact).order_by(m.Contact.created_at))).scalars().all()
        convs = (await s.execute(select(m.Conversation))).scalars().all()
    assert len(contacts) == 2 and len(convs) == 2
    fresh = next(c for c in contacts if not c.external_id.startswith("erased:"))
    assert fresh.opted_out is False and fresh.display_name == "An"  # nothing carried over from the erased one


async def test_erasing_is_all_or_nothing(owner, full, monkeypatch):
    client, hd = owner
    from cortex_leads.privacy import erase
    real, calls = erase.update, []

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 6:
            raise RuntimeError("the database went away half way")
        return real(*a, **kw)

    monkeypatch.setattr(erase, "update", flaky)
    with pytest.raises(RuntimeError):
        await client.post(f"/api/v1/customers/{full.conv.id}/erase", json={"confirm": True}, headers=hd)
    async with tenant_session(full.t.id) as s:
        assert "0912 345 678" in "".join(x.text for x in (await s.execute(select(m.Message))).scalars())  # the first steps were rolled back too
        assert (await s.execute(select(m.Outbox.status))).scalar_one() == "queued"
    assert not [e for e in await rows(full, m.AuditEvent) if e.action == "customer.erased"]


async def test_it_waits_while_a_message_to_this_customer_is_being_sent(owner, full, owner_engine):
    client, hd = owner
    async with owner_engine.begin() as c:
        await c.execute(text("update outbox set status = 'sending'"))
    r = await client.post(f"/api/v1/customers/{full.conv.id}/erase", json={"confirm": True}, headers=hd)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PENDING_WORK"
    async with tenant_session(full.t.id) as s:
        assert "0912" in "".join(x.text for x in (await s.execute(select(m.Message))).scalars())  # nothing was touched


@pytest.mark.parametrize("body", [{}, {"confirm": False}, {"confirm": "yes"}])
async def test_the_server_wants_the_confirmation_said_not_assumed(owner, full, body):
    client, hd = owner
    assert (await client.post(f"/api/v1/customers/{full.conv.id}/erase", json=body, headers=hd)).status_code == 422
    async with tenant_session(full.t.id) as s:
        assert "0912" in "".join(x.text for x in (await s.execute(select(m.Message))).scalars())


async def test_the_log_line_names_no_one_and_counts_what_changed(owner, full):
    client, hd = owner
    await client.post(f"/api/v1/customers/{full.conv.id}/erase", json={"confirm": True}, headers=hd)
    (ev,) = [e for e in await rows(full, m.AuditEvent) if e.action == "customer.erased"]
    blob = ev.summary + str(ev.metadata_) + str(ev.object_label) + ev.actor
    assert ev.metadata_["messages"] == 2 and "Nguyễn" not in blob and "0912" not in blob and ev.object_id == str(full.conv.id)


async def test_staff_cannot_export_or_erase(app_client, full, api_key_factory):
    _, key = await api_key_factory(full.t, "staff", "nv1")
    hd = h(await sign_in(app_client, key))
    assert (await app_client.get(f"/api/v1/customers/{full.conv.id}/export")).status_code == 403
    assert (await app_client.post(f"/api/v1/customers/{full.conv.id}/erase", json={"confirm": True}, headers=hd)).status_code == 403


async def test_another_business_cannot_reach_this_customer(owner, full, tenant_factory, sandbox_factory, connector_factory, conversation_factory, api_key_factory):
    client, _ = owner
    other = await tenant_factory("Khác")
    cn = await connector_factory(await sandbox_factory(other))
    theirs = await conversation_factory(cn, external_id="theirs")
    _, key = await api_key_factory(other, "owner", None)
    client.cookies.clear()
    hd = h(await sign_in(client, key))
    assert (await client.get(f"/api/v1/customers/{full.conv.id}/export")).status_code == 404
    assert (await client.post(f"/api/v1/customers/{full.conv.id}/erase", json={"confirm": True}, headers=hd)).status_code == 404
    assert (await client.get(f"/api/v1/customers/{theirs.id}/export")).status_code == 200  # their own is theirs
    async with tenant_session(full.t.id) as s:
        assert "0912" in "".join(x.text for x in (await s.execute(select(m.Message))).scalars())


async def test_an_unknown_conversation_is_not_found(owner):
    client, hd = owner
    zero = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/v1/customers/{zero}/export")).status_code == 404
    assert (await client.post(f"/api/v1/customers/{zero}/erase", json={"confirm": True}, headers=hd)).status_code == 404
