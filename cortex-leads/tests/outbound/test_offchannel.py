"""R39: window closed -> a draft on the `offchannel` route for staff to phone / Zalo; never the outbox."""
import re
from datetime import timedelta

from ob_support import configure, run, send
from sqlalchemy import update
from wp5_support import (
    GOOD_DRAFT,
    NOW,
    gateway,
    make_job,
    reply,
    rows,
    run_one,
    set_conv,
)

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

PROMISE_DRAFT = {**GOOD_DRAFT, "reason_code": "chua_san_sang",
                 "text": "Dạ chị, hôm nay đúng ngày chị hẹn, chị xếp được lịch học chưa ạ?", "claims": []}
BUTTONS = ("Cửa sổ Messenger đã đóng — hãy gọi điện hoặc nhắn Zalo", "Đã liên hệ", "Đã chuyển Zalo")


async def promised_far(world):  # promised 10 days ago on Messenger: the 7-day window is long gone
    await set_conv(world, last_customer_at=NOW - timedelta(days=10), promised_date=(NOW - timedelta(days=1)).date())
    return await make_job(world, "conversation.promised_date_reached")


async def test_far_promise_on_messenger_yields_offchannel_draft(world):
    gw, prov = gateway(reply(PROMISE_DRAFT))
    run_ = await run_one(world, gw, await promised_far(world))
    assert run_.status == "ok" and len(prov.calls) == 1
    (d,) = await rows(world, m.Draft)
    assert d.route == "offchannel" and d.status == "proposed"
    (log,) = [x for x in await rows(world, m.DecisionLog) if x.decision.startswith("draft_")]
    assert log.decision == "draft_offchannel"
    assert "cửa sổ nhắn của kênh đã đóng" in prov.calls[0]["messages"][1]["content"]
    assert await rows(world, m.Outbox) == []


async def test_opted_out_creates_nothing(world):
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Contact).values(opted_out=True))
    gw, prov = gateway()
    run_ = await run_one(world, gw, await promised_far(world))
    assert run_.status == "blocked" and prov.calls == [] and not await rows(world, m.Draft)


async def test_offchannel_draft_never_reaches_the_outbox(world, owner_engine):
    await configure(world, owner_engine, silent_h=240, mode="auto")  # auto skill, window long closed
    assert (await run(world)).status == "ok"
    (d,) = await rows(world, m.Draft)
    assert d.route == "offchannel" and await rows(world, m.Outbox) == []
    for staff in (None, "nv1"):  # the runner's path and the approve button's path
        res = await send(world, d, staff=staff)
        assert res.status == "blocked" and res.violations[0].detail == "offchannel_draft"
    assert await rows(world, m.Outbox) == [] and (await rows(world, m.Draft))[0].status == "proposed"


async def _offchannel_draft(world, seed):
    return await seed(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id,
                              status="proposed", route="offchannel", text="Gợi ý lời gọi", claims=[],
                              reason_code="chua_san_sang"))


async def _login(client, key):
    form = await client.get("/staff/login")
    tok = re.search(r'name="csrf" value="([^"]+)"', form.text).group(1)
    await client.post("/staff/login", data={"api_key": key, "csrf": tok})
    return re.search(r'name="csrf" value="([^"]+)"', (await client.get("/staff")).text).group(1)


async def test_staff_page_labels_it_and_contact_counts_a_touch(app_client, world, api_key_factory, seed):
    d = await _offchannel_draft(world, seed)
    _, key = await api_key_factory(world.t, staff_ref="nv1")
    tok = await _login(app_client, key)
    html = (await app_client.get("/staff")).text
    assert all(b in html for b in BUTTONS) and "Duyệt &amp; gửi" not in html and "Sửa rồi gửi" not in html
    r = await app_client.post(f"/staff/draft/{d.id}", data={"action": "sent", "csrf": tok})
    assert "msg=ok" in r.headers["location"]
    (conv,) = await rows(world, m.Conversation)
    assert conv.touches == 1 and not conv.offchannel_contact  # contacted once, not moved off-channel for good
    assert (await rows(world, m.StaffAction))[0].action == "sent" and await rows(world, m.Outbox) == []


async def test_zalo_button_sets_offchannel_contact_and_approve_is_refused(
        app_client, world, api_key_factory, seed):
    d1, d2 = await _offchannel_draft(world, seed), await _offchannel_draft(world, seed)
    _, key = await api_key_factory(world.t, staff_ref="nv1")
    tok = await _login(app_client, key)
    r = await app_client.post(f"/review/drafts/{d1.id}/action", json={"action": "approved"},
                              headers={"X-Api-Key": key})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "OFFCHANNEL_DRAFT"
    await app_client.post(f"/staff/draft/{d2.id}", data={"action": "zalo", "csrf": tok})
    (conv,) = await rows(world, m.Conversation)
    assert conv.offchannel_contact is True and conv.touches == 1


async def test_supervisor_counts_offchannel_drafts_without_text(app_client, world, api_key_factory, seed):
    for _ in range(5):
        await _offchannel_draft(world, seed)
    _, key = await api_key_factory(world.t, "supervisor", None)
    r = await app_client.get("/supervisor/summary?since=2020-01-01T00:00:00", headers={"X-Api-Key": key})
    assert r.json()["draft_routes"] == {"offchannel": 5} and "Gợi ý lời gọi" not in r.text
