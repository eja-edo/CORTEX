"""WP19: cron slots, the morning list and the weekly digest (templates, 0 token, idempotent per slot)."""
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import update
from wp5_support import NOW, rows

from cortex_leads.core.ids import uuid7
from cortex_leads.cron.runner import cron_once
from cortex_leads.cron.schedule import morning_slot, weekly_slot
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.notify import worker

TZ = "Asia/Ho_Chi_Minh"  # UTC+7
VN = lambda y, mo, d, h, mi=0: datetime(y, mo, d, h, mi, tzinfo=UTC) - timedelta(hours=7)


def test_morning_slot_opens_at_0745_local():
    assert morning_slot(VN(2026, 10, 13, 7, 44), TZ) is None
    assert morning_slot(VN(2026, 10, 13, 7, 45), TZ) == date(2026, 10, 13)
    assert morning_slot(VN(2026, 10, 13, 23, 59), TZ) == date(2026, 10, 13)  # a late worker still catches up
    assert morning_slot(datetime(2026, 10, 12, 20, 0, tzinfo=UTC), TZ) is None  # 03:00 next day, local


def test_weekly_slot_is_the_monday_once_0800_has_passed():
    assert weekly_slot(VN(2026, 10, 12, 7, 59), TZ) is None  # Monday, too early
    assert weekly_slot(VN(2026, 10, 12, 8, 0), TZ) == date(2026, 10, 12)
    assert weekly_slot(VN(2026, 10, 14, 15), TZ) == date(2026, 10, 12)  # a missed Monday runs when we are back
    assert weekly_slot(VN(2026, 10, 18, 22), TZ) == date(2026, 10, 12)  # Sunday still belongs to that week
    assert weekly_slot(VN(2026, 10, 19, 8, 0), TZ) == date(2026, 10, 19)


async def test_morning_list_names_who_was_left_unanswered_once_a_day(world):
    assert await cron_once(NOW) == 1  # 10:00 in Vietnam; the world's lead has been silent 26h
    (task,) = await rows(world, m.StaffTask)
    assert task.kind == "morning_list" and task.for_date == date(2026, 10, 12) and task.status == "open"
    assert task.payload["leads"] == [str(world.conv.id)] and task.payload["bookings_today"] == 0
    (n,) = await rows(world, m.Notification)
    assert (n.kind, n.ref_id) == ("task", task.id)
    assert await cron_once(NOW + timedelta(hours=1)) == 0  # same slot: nothing new, nobody pushed twice
    assert len(await rows(world, m.StaffTask)) == 1 and len(await rows(world, m.Notification)) == 1
    assert await cron_once(NOW + timedelta(days=1)) == 1  # next day, next slot
    assert "Nguyễn" not in json.dumps(task.payload, ensure_ascii=False)


async def test_nothing_to_say_means_no_task_and_no_push(world):
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Conversation).values(state="lost"))
    assert await cron_once(NOW) == 0
    assert not await rows(world, m.StaffTask) and not await rows(world, m.Notification)


async def test_before_0745_and_a_paused_sandbox_do_nothing(world):
    assert await cron_once(VN(2026, 10, 12, 7, 0)) == 0
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).values(status="paused"))
    assert await cron_once(NOW) == 0 and not await rows(world, m.StaffTask)  # kill switch


async def test_todays_trial_seats_are_counted_in_the_list(world, conversation_factory):
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Conversation).values(state="lost"))  # no unanswered lead: seats alone make a task
        s.add(m.Booking(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id,
                        contact_id=world.conv.contact_id, slot_code="LH", starts_at=VN(2026, 10, 12, 19),
                        actor="ai:x"))
        s.add(m.Booking(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id,
                        contact_id=world.conv.contact_id, slot_code="LH2", starts_at=VN(2026, 10, 13, 19),
                        actor="ai:x", status="cancelled"))
    assert await cron_once(NOW) == 1
    (task,) = await rows(world, m.StaffTask)
    assert task.payload["bookings_today"] == 1 and task.payload["leads"] == []


# --- weekly digest ----------------------------------------------------------------------------------
def next_monday_after_today() -> date:
    today = datetime.now(UTC).date()
    return today + timedelta(days=7 - today.weekday())


async def owner_sandbox(world, sandbox_factory):
    return await sandbox_factory(world.t, name="owner_digest", purpose="owner_digest", profile_ref="digest_template@1")


async def test_weekly_digest_counts_the_week_that_just_ended(world, sandbox_factory, message_factory, seed):
    slot = next_monday_after_today()  # the week before it contains the real clock the fixtures stamp
    now = datetime.combine(slot, datetime.min.time(), tzinfo=UTC) + timedelta(hours=3)  # Monday 10:00 local
    owner = await owner_sandbox(world, sandbox_factory)
    await message_factory(world.conv, "alo", occurred_at=now - timedelta(days=2))
    await seed(m.Outbox(tenant_id=world.t.id, action_id=uuid7(), conversation_id=world.conv.id, connector_id=world.cn.id,
                        actor="ai:customer_drafter@1", text="x", status="sent", sent_at=now - timedelta(days=1)))
    await seed(m.Outbox(tenant_id=world.t.id, action_id=uuid7(), conversation_id=world.conv.id, connector_id=world.cn.id,
                        actor="staff:nv1", text="x", status="sent", sent_at=now - timedelta(days=1)))
    await seed(m.Booking(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id,
                         contact_id=world.conv.contact_id, slot_code="LH", starts_at=now + timedelta(days=3), actor="ai:x"))
    assert await cron_once(now) == 2  # the morning list and the digest
    (d,) = await rows(world, m.Digest)
    assert d.sandbox_id == owner.id and d.kind == "weekly"
    assert (d.period_start, d.period_end) == (slot - timedelta(days=7), slot - timedelta(days=1))
    this = d.payload["this"]
    assert this["new_conversations"] == 1 and this["customer_messages"] == 1  # the world's own message is 26h old
    assert this["ai_sent"] == 1  # the staff-sent one is not the AI's
    assert this["bookings"] == 1 and this["bookings_cancelled"] == 0
    assert d.payload["prev"]["new_conversations"] == 0 and d.payload["dropped_now"] >= 0
    assert all(isinstance(v, int) for v in this.values())  # numbers only: nothing a customer wrote
    assert await cron_once(now + timedelta(hours=2)) == 0 and len(await rows(world, m.Digest)) == 1


async def test_digest_counts_outcomes_by_kind(world, sandbox_factory, seed):
    slot = next_monday_after_today()
    now = datetime.combine(slot, datetime.min.time(), tzinfo=UTC) + timedelta(hours=3)
    await owner_sandbox(world, sandbox_factory)
    for st in ("won", "won", "lost", "booked"):
        await seed(m.ContactFact(tenant_id=world.t.id, contact_id=world.conv.contact_id, conversation_id=world.conv.id,
                                 kind="outcome", value={"status": st}, status="done"))
    await cron_once(now)
    this = (await rows(world, m.Digest))[0].payload["this"]
    assert (this["outcome_won"], this["outcome_lost"], this["outcome_booked"]) == (2, 1, 1)


# --- pushes --------------------------------------------------------------------------------------
@pytest.fixture
def telegram(monkeypatch):
    monkeypatch.setattr(worker, "get_settings", lambda: type("S", (), {
        "TELEGRAM_BOT_TOKEN": "1:a", "PUBLIC_BASE_URL": "https://cx.example.vn"})())
    sent: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content)["text"])
        return httpx.Response(200, json={"ok": True})
    return sent, httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_task_and_digest_pushes_carry_numbers_only(world, sandbox_factory, telegram):
    sent, client = telegram
    async with tenant_session(world.t.id) as s:
        s.add(m.NotifyTarget(tenant_id=world.t.id, kind="telegram", address="9"))
    slot = next_monday_after_today()
    now = datetime.combine(slot, datetime.min.time(), tzinfo=UTC) + timedelta(hours=3)
    await owner_sandbox(world, sandbox_factory)
    await cron_once(now)
    assert await worker.notify_once(now, client=client) == 2
    assert sorted(sent) == sorted([
        "📋 Việc sáng nay: 1 khách chưa được trả lời, 0 lịch học thử hôm nay.\nMở: https://cx.example.vn/staff",
        "📊 Báo cáo tuần: 1 khách mới, 0 lịch học thử, 0 tin AI tự gửi, 1 khách đang bị bỏ rơi.\n"
        "Chi tiết: https://cx.example.vn/staff/digest"])
    assert not any("Nguyễn" in t for t in sent)
