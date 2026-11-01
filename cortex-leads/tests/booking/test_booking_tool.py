"""WP18: trial-class seats. A slot is a catalog row; seats never exceed `suc_chua`; A3 holds."""
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from wp5_support import NOW, REG, rows

from cortex_leads.core.context import CustomerPrincipal, RunContext, Scope
from cortex_leads.core.envelope import BlockedCode, ErrorCode
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.tools.booking import cancel_booking

START = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # 19:00 in Vietnam, three days out
ALLOW = ["list_open_slots", "book_slot", "draft_followup"]


def ctx_for(w, conv=None) -> RunContext:
    c = conv or w.conv
    return RunContext(run_id=uuid4(), tenant_id=w.t.id, sandbox_id=w.sb.id, profile="customer_drafter",
                      profile_version=1, principal=CustomerPrincipal(contact_id=c.contact_id),
                      scope=Scope(conversation_id=c.id))


async def call(w, name, args, conv=None):
    async with tenant_session(w.t.id) as s:
        return await REG.execute(ctx_for(w, conv), s, name, args, allowlist=ALLOW, effect_ceiling="internal")


async def slot(catalog_factory, w, code="LH-15-10", cap=2, start=START, **kw):
    return await catalog_factory(w.t, code=code, name=f"Buổi học thử {code}", price=None, category="lich_hoc_thu",
                                 valid_until=start, attrs={"ngay": f"{start:%d/%m}", "gio": "19:00", "suc_chua": cap}, **kw)


async def test_list_shows_only_open_future_slots(world, catalog_factory):
    await slot(catalog_factory, world, "LH-A", cap=1)
    await slot(catalog_factory, world, "LH-GONE", start=NOW - timedelta(days=1))
    await slot(catalog_factory, world, "LH-OFF", active=False)
    await slot(catalog_factory, world, "LH-FULL", cap=1)
    assert (await call(world, "book_slot", {"slot_code": "LH-FULL"})).status == "ok"
    r = await call(world, "list_open_slots", {})
    assert [x["code"] for x in r.data["slots"]] == ["LH-A"]
    assert r.data["slots"][0] | {"con_cho": 1} == {"code": "LH-A", "name": "Buổi học thử LH-A", "ngay": "15/10",
                                                   "gio": "19:00", "con_cho": 1, "source_id": "LH-A"}


async def test_no_slots_says_do_not_promise_a_date(world):
    r = await call(world, "list_open_slots", {})
    assert r.status == "ok" and r.data["slots"] == [] and "đừng hứa ngày" in r.note


async def test_book_holds_the_seat_sets_the_promise_and_pushes_staff(world, catalog_factory):
    await slot(catalog_factory, world)
    r = await call(world, "book_slot", {"slot_code": "LH-15-10"})
    assert r.status == "ok" and r.data["slot"]["con_cho"] == 1
    (b,) = await rows(world, m.Booking)
    assert (b.slot_code, b.status, b.starts_at, b.conversation_id) == ("LH-15-10", "confirmed", START, world.conv.id)
    assert b.actor.startswith("ai:customer_drafter")
    async with tenant_session(world.t.id) as s:
        conv = await s.get(m.Conversation, world.conv.id)
    assert str(conv.promised_date) == "2026-10-15"  # the "đúng hẹn" skill fires that morning
    assert [(n.kind, n.ref_id) for n in await rows(world, m.Notification)] == [("booking", b.id)]
    assert "booking_made" in [d.decision for d in await rows(world, m.DecisionLog)]
    assert all("Nguyễn" not in str(d.detail) for d in await rows(world, m.DecisionLog))


async def test_full_slot_is_refused_and_other_slot_untouched(world, catalog_factory, conversation_factory):
    await slot(catalog_factory, world, cap=1)
    other = await conversation_factory(world.cn, external_id="conv-2", display_name="B")
    assert (await call(world, "book_slot", {"slot_code": "LH-15-10"})).status == "ok"
    r = await call(world, "book_slot", {"slot_code": "LH-15-10"}, conv=other)
    assert r.status == "blocked" and r.violations[0].code == BlockedCode.SLOT_FULL
    assert len(await rows(world, m.Booking)) == 1


async def test_last_seat_goes_to_exactly_one_of_two_concurrent_customers(world, catalog_factory, conversation_factory):
    await slot(catalog_factory, world, cap=1)
    other = await conversation_factory(world.cn, external_id="conv-2", display_name="B")
    a, b = await asyncio.gather(call(world, "book_slot", {"slot_code": "LH-15-10"}),
                                call(world, "book_slot", {"slot_code": "LH-15-10"}, conv=other))
    assert sorted([a.status, b.status]) == ["blocked", "ok"]
    assert len([x for x in await rows(world, m.Booking) if x.status == "confirmed"]) == 1


async def test_unknown_expired_or_seatless_slot_is_gone(world, catalog_factory):
    await slot(catalog_factory, world, "LH-OLD", start=NOW - timedelta(hours=1))
    await catalog_factory(world.t, code="LH-NOCAP", name="x", price=None, category="lich_hoc_thu",
                          valid_until=START, attrs={"ngay": "15/10"})  # no suc_chua: unknown seats = none
    await catalog_factory(world.t, code="KH-OTHER", name="x", category="ielts")  # a course is not a slot
    for code in ("LH-OLD", "LH-NOCAP", "KH-OTHER", "NOPE"):
        r = await call(world, "book_slot", {"slot_code": code})
        assert r.status == "blocked" and r.violations[0].code == BlockedCode.SLOT_GONE, code
    assert not await rows(world, m.Booking)


async def test_same_slot_twice_is_idempotent_and_moving_frees_the_first(world, catalog_factory):
    await slot(catalog_factory, world, "LH-A", cap=1)
    await slot(catalog_factory, world, "LH-B", cap=1, start=START + timedelta(days=2))
    first = await call(world, "book_slot", {"slot_code": "LH-A"})
    again = await call(world, "book_slot", {"slot_code": "LH-A"})
    assert again.status == "ok" and again.data["unchanged"] and len(await rows(world, m.Booking)) == 1
    assert first.data["booking_id"] == again.data["booking_id"]
    assert (await call(world, "book_slot", {"slot_code": "LH-B"})).status == "ok"
    live = [b.slot_code for b in await rows(world, m.Booking) if b.status == "confirmed"]
    assert live == ["LH-B"]
    async with tenant_session(world.t.id) as s:
        assert str((await s.get(m.Conversation, world.conv.id)).promised_date) == "2026-10-17"
    assert [x["code"] for x in (await call(world, "list_open_slots", {})).data["slots"]] == ["LH-A"]


async def test_cancel_returns_the_seat_and_the_promise(world, catalog_factory):
    await slot(catalog_factory, world, cap=1)
    await call(world, "book_slot", {"slot_code": "LH-15-10"})
    (b,) = await rows(world, m.Booking)
    async with tenant_session(world.t.id) as s:
        assert await cancel_booking(s, b.id, by="staff:nv1", now=NOW)
        assert not await cancel_booking(s, b.id, by="staff:nv1", now=NOW)  # already cancelled
    async with tenant_session(world.t.id) as s:
        conv = await s.get(m.Conversation, world.conv.id)
        bk = await s.get(m.Booking, b.id)
    assert conv.promised_date is None and (bk.status, bk.cancelled_by) == ("cancelled", "staff:nv1")
    assert len((await call(world, "list_open_slots", {})).data["slots"]) == 1


async def test_args_cannot_carry_scope_a3(world, catalog_factory):
    await slot(catalog_factory, world)
    r = await call(world, "book_slot", {"slot_code": "LH-15-10", "conversation_id": str(uuid4())})
    assert r.status == "error" and r.error.code == ErrorCode.INVALID_ARGS and not await rows(world, m.Booking)


async def test_another_tenants_slot_is_invisible(world, catalog_factory, tenant_factory):
    other = await tenant_factory()
    await catalog_factory(other, code="LH-X", name="x", price=None, category="lich_hoc_thu", valid_until=START,
                          attrs={"suc_chua": 5})
    assert (await call(world, "book_slot", {"slot_code": "LH-X"})).violations[0].code == BlockedCode.SLOT_GONE


async def test_closed_conversation_cannot_book(world, catalog_factory):
    await slot(catalog_factory, world)
    async with tenant_session(world.t.id) as s:
        (await s.get(m.Conversation, world.conv.id)).state = "lost"
    r = await call(world, "book_slot", {"slot_code": "LH-15-10"})
    assert r.status == "blocked" and r.violations[0].code == BlockedCode.OPTED_OUT


async def test_the_model_is_not_offered_book_slot(world):
    names = {s["function"]["name"] for s in REG.openai_schemas(
        [x.name for x in REG.specs_for(ALLOW) if x.effect == "read"])}
    assert names == {"list_open_slots"}


async def test_the_slot_a_customer_is_offered_is_read_off_its_real_start_not_its_typed_text(world, catalog_factory):
    await catalog_factory(world.t, code="LH-LIE", name="Học thử", price=None, category="lich_hoc_thu", valid_until=START,
                          attrs={"ngay": "16/10", "gio": "20:00", "suc_chua": 2})  # typed text disagrees with START (19:00, 15/10 in VN)
    (slot_,) = (await call(world, "list_open_slots", {})).data["slots"]
    assert (slot_["ngay"], slot_["gio"]) == ("15/10", "19:00")
    booked = await call(world, "book_slot", {"slot_code": "LH-LIE"})
    assert booked.data["slot"]["ngay"] == "15/10" and booked.data["slot"]["gio"] == "19:00"


async def test_a_draft_that_repeats_the_typed_text_instead_of_the_real_start_is_blocked(world, catalog_factory):
    await catalog_factory(world.t, code="LH-LIE", name="Học thử", price=None, category="lich_hoc_thu", valid_until=START,
                          attrs={"ngay": "16/10", "gio": "20:00", "suc_chua": 2})
    def draft(text, d, t):
        return call(world, "draft_followup", {"text": text, "reason_code": "khong_ro", "has_new_info": True,
                                              "claims": [{"value": d, "source_id": "LH-LIE"}, {"value": t, "source_id": "LH-LIE"}]})
    ok = await draft("Em giữ chỗ học thử ngày 15/10 lúc 19:00 cho mình ạ", "15/10", "19:00")
    assert ok.status == "proposed"
    wrong = await draft("Em giữ chỗ học thử ngày 16/10 lúc 20:00 cho mình ạ", "16/10", "20:00")
    assert wrong.status == "blocked" and {v.span for v in wrong.violations} == {"16/10", "20:00"}
