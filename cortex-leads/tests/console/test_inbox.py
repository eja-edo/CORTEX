"""WP27 Hộp thư: lists, one conversation, and the staff actions (all through the existing services)."""
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from support import URL, h, sign_in, sql
from wp5_support import rows

from cortex_leads.db import models as m


async def staff(app_client, world, api_key_factory, role="staff"):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    return await sign_in(app_client, key)


async def recent(owner_engine, hours=26):
    """The shared world is dated 2026-10-12; the API uses the real clock, so move its customer to `hours` ago."""
    await sql(owner_engine, "update conversation set last_customer_at = now() - make_interval(hours => :h)", h=hours)
    await sql(owner_engine, "update message set occurred_at = now() - make_interval(hours => :h)", h=hours)


async def make_draft(world, seed, *, needs_human=False, text="Dạ chị cần em gửi lịch không ạ?"):
    return await seed(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id, status="proposed",
                              text=text, claims=[{"value": 15, "source_id": "THCS"}], reason_code="so_sanh", needs_human=needs_human))


async def test_the_four_lists_and_their_counts(app_client, world, api_key_factory, seed, conversation_factory, message_factory):
    await staff(app_client, world, api_key_factory)
    now = datetime.now(UTC)
    # world.conv: customer wrote 26h ago, nobody answered -> silent
    fresh = await conversation_factory(world.cn, external_id="c2", display_name="Chị Lan", last_customer_at=now - timedelta(minutes=10))
    await message_factory(fresh, "Cho em hỏi lớp IELTS", occurred_at=now - timedelta(minutes=10))
    await seed(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=fresh.id, status="proposed", text="x",
                       claims=[], reason_code="khong_ro", needs_human=True))
    r = (await app_client.get("/api/v1/conversations?filter=need_human")).json()
    assert [i["name"] for i in r["items"]] == ["Chị Lan"] and r["items"][0]["badges"][0] == "need_human"
    assert r["counts"] == {"need_human": 1, "waiting": 1, "silent": 1, "all": 2}
    waiting = (await app_client.get("/api/v1/conversations?filter=waiting")).json()["items"]
    assert [i["name"] for i in waiting] == ["Chị Lan"]
    silent = (await app_client.get("/api/v1/conversations?filter=silent")).json()["items"]
    assert [i["id"] for i in silent] == [str(world.conv.id)] and silent[0]["snippet"].startswith("Chào shop")
    assert len((await app_client.get("/api/v1/conversations?filter=all")).json()["items"]) == 2
    assert (await app_client.get("/api/v1/conversations?filter=bogus")).status_code == 422
    assert (await app_client.get("/api/v1/session")).json()["needs_person"] == 1  # the sidebar badge


async def test_lists_never_cross_tenants_and_are_audited(app_client, world, api_key_factory, tenant_factory, sandbox_factory,
                                                         connector_factory, conversation_factory):
    other = await tenant_factory()
    cn = await connector_factory(await sandbox_factory(other))
    theirs = await conversation_factory(cn, external_id="x1", display_name="Của tenant khác",
                                        last_customer_at=datetime.now(UTC) - timedelta(hours=30))
    await staff(app_client, world, api_key_factory)
    ids = [i["id"] for i in (await app_client.get("/api/v1/conversations?filter=all")).json()["items"]]
    assert str(theirs.id) not in ids
    assert (await app_client.get(f"/api/v1/conversations/{theirs.id}")).status_code == 404
    assert [a.action for a in await rows(world, m.AuditEvent)] == ["login.ok"]  # a 404 on someone else's conversation leaves no "viewed" line


async def test_one_conversation_shows_what_the_ai_knows_and_did(app_client, world, api_key_factory, seed, owner_engine):
    await recent(owner_engine)
    await staff(app_client, world, api_key_factory)
    d = await make_draft(world, seed, needs_human=True)
    fact = await seed(m.ContactFact(tenant_id=world.t.id, contact_id=world.conv.contact_id, conversation_id=world.conv.id,
                                    kind="decision_maker", value={"role": "bo_me"}, status="candidate", source="ai:customer_drafter@1"))
    await seed(m.DecisionLog(tenant_id=world.t.id, conversation_id=world.conv.id, decision="draft_proposed", detail={"skill": "tra-loi-khach"}))
    c = (await app_client.get(f"/api/v1/conversations/{world.conv.id}")).json()
    assert c["name"] == "Nguyễn Văn An" and c["channel"] == "messenger" and c["intent"] == "Hỏi giá"
    assert c["messages"][0]["role"] == "customer" and "Khóa IELTS" in c["messages"][0]["text"]
    assert [(x["id"], x["needs_human"], x["reason"]) for x in c["drafts"]] == [(str(d.id), True, "Đang so sánh nơi khác")]
    assert c["facts"] == [{"id": str(fact.id), "kind": "decision_maker", "text": "bo_me", "status": "candidate", "evidence": 0, "by_ai": True}]
    assert c["log"][0] == {"at": c["log"][0]["at"], "label": "AI soạn nháp, đã qua bộ kiểm", "skill": "tra-loi-khach"}
    assert c["window"]["open"] is True and c["window"]["basis"] == "human_agent"  # 26h: only a person typing
    assert "conversation.viewed" in [a.action for a in await rows(world, m.AuditEvent)]


async def test_staff_can_skip_a_draft_and_a_second_click_is_a_409(app_client, world, api_key_factory, seed):
    csrf = await staff(app_client, world, api_key_factory)
    d = await make_draft(world, seed)
    r = await app_client.post(f"/api/v1/drafts/{d.id}/action", json={"action": "skipped"}, headers=h(csrf))
    assert r.status_code == 200 and r.json() == {"id": str(d.id), "status": "skipped"}
    r = await app_client.post(f"/api/v1/drafts/{d.id}/action", json={"action": "skipped"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_PROPOSED"
    assert (await app_client.post(f"/api/v1/drafts/{d.id}/action", json={"action": "approved"})).status_code == 403  # no CSRF


async def test_approving_goes_through_send_message_and_is_refused_when_the_channel_cannot_send(app_client, world, api_key_factory, seed):
    csrf = await staff(app_client, world, api_key_factory)
    d = await make_draft(world, seed)
    r = await app_client.post(f"/api/v1/drafts/{d.id}/action", json={"action": "approved"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "OUTBOUND_OFF"  # connector.outbound is not enabled
    assert not await rows(world, m.Outbox) and [x.status for x in await rows(world, m.Draft)] == ["proposed"]


async def test_approving_queues_exactly_one_outbox_row_when_the_channel_is_on(app_client, world, api_key_factory, seed, owner_engine):
    await recent(owner_engine)
    await sql(owner_engine, "update connector set trust = 'official', outbound = cast(:o as jsonb) where id = :i",
              o=json.dumps({"enabled": True, "url": URL}), i=world.cn.id)
    csrf = await staff(app_client, world, api_key_factory)
    d = await make_draft(world, seed)
    r = await app_client.post(f"/api/v1/drafts/{d.id}/action", json={"action": "approved"}, headers=h(csrf))
    assert r.status_code == 200
    (ob,) = await rows(world, m.Outbox)
    assert ob.draft_id == d.id and ob.actor == "staff:nv1" and ob.text == d.text and ob.kind == "message"


async def test_a_typed_reply_is_a_draft_in_the_staffs_name_and_a_refusal_leaves_nothing_behind(
        app_client, world, api_key_factory, owner_engine):
    await recent(owner_engine)
    csrf = await staff(app_client, world, api_key_factory)
    r = await app_client.post(f"/api/v1/conversations/{world.conv.id}/reply", json={"text": "Dạ em chào chị"}, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "OUTBOUND_OFF"
    assert [x.status for x in await rows(world, m.Draft)] == ["skipped"] and not await rows(world, m.Outbox)  # no ghost draft
    await sql(owner_engine, "update connector set trust = 'official', outbound = cast(:o as jsonb) where id = :i",
              o=json.dumps({"enabled": True, "url": URL}), i=world.cn.id)
    r = await app_client.post(f"/api/v1/conversations/{world.conv.id}/reply", json={"text": "Dạ em chào chị"}, headers=h(csrf))
    assert r.status_code == 200
    (ob,) = await rows(world, m.Outbox)
    assert (ob.actor, ob.text, ob.status) == ("staff:nv1", "Dạ em chào chị", "queued")
    assert (await app_client.post(f"/api/v1/conversations/{world.conv.id}/reply", json={"text": ""}, headers=h(csrf))).status_code == 422


async def test_booking_a_seat_cancelling_it_and_marking_an_outcome(app_client, world, api_key_factory, catalog_factory):
    csrf = await staff(app_client, world, api_key_factory)
    start = datetime.now(UTC) + timedelta(days=3)
    await catalog_factory(world.t, code="LH-A", name="Học thử", price=None, category="lich_hoc_thu", valid_until=start,
                          attrs={"ngay": f"{start:%d/%m}", "gio": "19:00", "suc_chua": 1})
    c = (await app_client.get(f"/api/v1/conversations/{world.conv.id}")).json()
    assert [(s["code"], s["con_cho"]) for s in c["open_slots"]] == [("LH-A", 1)]
    r = await app_client.post(f"/api/v1/conversations/{world.conv.id}/booking", json={"slot_code": "LH-A"}, headers=h(csrf))
    assert r.status_code == 200
    (b,) = await rows(world, m.Booking)
    assert b.actor == "staff:nv1" and b.status == "confirmed"
    again = await app_client.post(f"/api/v1/conversations/{world.conv.id}/booking", json={"slot_code": "NOPE"}, headers=h(csrf))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "SLOT_GONE"
    c = (await app_client.get(f"/api/v1/conversations/{world.conv.id}")).json()
    assert [x["slot"] for x in c["bookings"]] == ["LH-A"] and c["open_slots"] == []
    assert (await app_client.post(f"/api/v1/bookings/{b.id}/cancel", headers=h(csrf))).status_code == 200
    assert (await app_client.post(f"/api/v1/bookings/{b.id}/cancel", headers=h(csrf))).status_code == 409
    r = await app_client.post(f"/api/v1/conversations/{world.conv.id}/outcome", json={"status": "won"}, headers=h(csrf))
    assert r.json() == {"state": "won"}
    assert (await app_client.post(f"/api/v1/conversations/{world.conv.id}/outcome", json={"status": "weird"}, headers=h(csrf))).status_code == 422


async def test_confirming_and_rejecting_what_the_ai_remembered(app_client, world, api_key_factory, seed):
    csrf = await staff(app_client, world, api_key_factory)
    f = await seed(m.ContactFact(tenant_id=world.t.id, contact_id=world.conv.contact_id, conversation_id=world.conv.id,
                                 kind="decision_maker", value={"role": "bo_me"}, status="candidate", source="rule"))
    assert (await app_client.post(f"/api/v1/facts/{f.id}/confirm", headers=h(csrf))).json() == {"status": "active"}
    assert (await app_client.post(f"/api/v1/facts/{f.id}/reject", headers=h(csrf))).json() == {"status": "rejected"}
    assert (await app_client.post(f"/api/v1/facts/{f.id}/maybe", headers=h(csrf))).status_code == 422
    assert (await app_client.post(f"/api/v1/facts/{uuid4()}/confirm", headers=h(csrf))).status_code == 409
