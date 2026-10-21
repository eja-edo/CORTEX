"""WP18 through the runner: the seat is held before the reply that confirms it is written, and is
given back when that reply never becomes a proposal."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from test_turn import conv_of, go_auto, say, tw  # noqa: F401
from wp5_support import NOW, gateway, reply, rows

from cortex_leads.clock.sweeper import sweep_once
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.runner.customer_run import run_pending

START = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # 19:00 in Vietnam
CLAIMS = [{"value": "15/10", "source_id": "LH-A"}, {"value": "19:00", "source_id": "LH-A"}]
CONFIRM = {"act": "reply", "reason_code": "khong_ro", "book": "LH-A", "claims": CLAIMS,
           "text": "Em giữ cho mình chỗ học thử ngày 15/10 lúc 19:00 rồi ạ, hôm đó mình tới sớm chút nha."}


async def slots(catalog_factory, w, **caps) -> None:
    for code, (cap, days) in caps.items():
        start = START + timedelta(days=days)
        await catalog_factory(w.t, code=code, name=f"Buổi học thử {code}", price=None, category="lich_hoc_thu",
                              valid_until=start, attrs={"ngay": f"{start:%d/%m}", "gio": "19:00", "suc_chua": cap})


async def ask(w, gw, text="15/10 đi em") -> None:
    await say(w, "a", "customer", text, NOW)
    await sweep_once(NOW + timedelta(seconds=40))
    assert await run_pending(NOW + timedelta(seconds=40), gw) == 1


def live(bookings) -> list[str]:
    return [b.slot_code for b in bookings if b.status == "confirmed"]


async def test_chosen_slot_is_booked_and_confirmed_in_one_turn(tw, catalog_factory) -> None:
    await slots(catalog_factory, tw, **{"LH-A": (2, 0)})
    await ask(tw, gateway(reply(CONFIRM))[0])
    assert live(await rows(tw, m.Booking)) == ["LH-A"]
    (d,) = [x for x in await rows(tw, m.Draft) if not x.needs_human]
    assert d.status == "proposed" and "15/10 lúc 19:00" in d.text  # manual: staff sees the confirmation
    assert {n.kind for n in await rows(tw, m.Notification)} == {"booking"}
    assert str((await conv_of(tw)).promised_date) == "2026-10-15"


async def test_auto_mode_sends_the_confirmation_only_after_the_seat_is_held(tw, catalog_factory, owner_engine) -> None:
    await go_auto(tw, owner_engine)
    await slots(catalog_factory, tw, **{"LH-A": (2, 0)})
    await ask(tw, gateway(reply(CONFIRM))[0])
    (ob,) = await rows(tw, m.Outbox)
    assert "15/10 lúc 19:00" in ob.text and live(await rows(tw, m.Booking)) == ["LH-A"]


async def test_a_time_not_in_the_catalog_blocks_the_reply_and_returns_the_seat(tw, catalog_factory) -> None:
    await slots(catalog_factory, tw, **{"LH-A": (1, 0)})
    wrong = {**CONFIRM, "text": "Em giữ cho mình chỗ học thử ngày 15/10 lúc 20:00 rồi ạ."}
    await ask(tw, gateway(reply(wrong), reply({**wrong, "act": "reply"}))[0])  # the rewrite is wrong too
    (bk,) = await rows(tw, m.Booking)
    assert bk.status == "cancelled"  # the customer was told nothing, so no seat stays held
    assert any(d.needs_human for d in await rows(tw, m.Draft))  # a person picks it up
    async with tenant_session(tw.t.id) as s:  # and the seat can be sold again
        assert (await s.execute(select(m.Booking).where(m.Booking.status == "confirmed"))).first() is None


async def test_full_slot_triggers_one_rewrite_with_another_slot(tw, catalog_factory, conversation_factory) -> None:
    await slots(catalog_factory, tw, **{"LH-A": (1, 0), "LH-B": (3, 2)})
    other = await conversation_factory(tw.cn, external_id="conv-2", display_name="B")
    async with tenant_session(tw.t.id) as s:
        s.add(m.Booking(tenant_id=tw.t.id, sandbox_id=tw.sb.id, conversation_id=other.id, contact_id=other.contact_id,
                        slot_code="LH-A", starts_at=START, actor="staff:nv1"))
    b_claims = [{"value": "17/10", "source_id": "LH-B"}, {"value": "19:00", "source_id": "LH-B"}]
    second = {"act": "reply", "reason_code": "khong_ro", "book": "LH-B", "claims": b_claims,
              "text": "Lịch đó vừa hết chỗ rồi ạ, em giữ cho mình buổi 17/10 lúc 19:00 nha."}
    gw, prov = gateway(reply(CONFIRM), reply(second))
    await ask(tw, gw)
    assert len(prov.calls) == 2 and "Không giữ được chỗ (SLOT_FULL LH-A)" in str(prov.calls[1])
    mine = [b for b in await rows(tw, m.Booking) if b.conversation_id == (await conv_of(tw)).id]
    assert live(mine) == ["LH-B"]
    assert [d for d in await rows(tw, m.Draft) if "17/10" in d.text and not d.needs_human]


async def test_full_and_no_alternative_becomes_a_person_card(tw, catalog_factory, conversation_factory) -> None:
    await slots(catalog_factory, tw, **{"LH-A": (1, 0)})
    other = await conversation_factory(tw.cn, external_id="conv-2", display_name="B")
    async with tenant_session(tw.t.id) as s:
        s.add(m.Booking(tenant_id=tw.t.id, sandbox_id=tw.sb.id, conversation_id=other.id, contact_id=other.contact_id,
                        slot_code="LH-A", starts_at=START, actor="staff:nv1"))
    hand = {"act": "handoff", "text": "Khách muốn học thử 15/10 nhưng hết chỗ, nhờ anh/chị xếp lịch khác."}
    await ask(tw, gateway(reply(CONFIRM), reply(hand))[0])
    assert not [b for b in await rows(tw, m.Booking) if b.conversation_id == (await conv_of(tw)).id]
    card = [d for d in await rows(tw, m.Draft) if d.needs_human]
    assert len(card) == 1 and "hết chỗ" in card[0].text
    assert {n.kind for n in await rows(tw, m.Notification)} == {"handoff"}


async def test_a_reply_without_book_books_nothing(tw, catalog_factory) -> None:
    await slots(catalog_factory, tw, **{"LH-A": (2, 0)})
    plain = {"act": "reply", "reason_code": "khong_ro", "claims": [], "text": "Dạ mình cho em biết mình rảnh buổi nào ạ?"}
    await ask(tw, gateway(reply(plain))[0], text="cho em học thử với")
    assert not await rows(tw, m.Booking) and not await rows(tw, m.Notification)
