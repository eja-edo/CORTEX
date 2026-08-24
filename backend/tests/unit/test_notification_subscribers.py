"""Milestone 4.3 M3: the schedule.reminder.due -> Notification path must go
through the Attention Gate (app.services.attention_gate), not write to the
notifications table directly."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.config import settings
from app.events.schemas import EventEnvelope
from app.services import notification_subscribers


@pytest.mark.asyncio
async def test_handle_schedule_reminder_due_goes_through_attention_gate(monkeypatch):
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    user_id = uuid4()
    event = EventEnvelope(
        type="schedule.reminder.due",
        source="test",
        user_id=user_id,
        payload={
            "method": "push",
            "schedule_id": str(uuid4()),
            "schedule_title": "Standup",
            "scheduled_at": "2026-08-10T09:00:00+00:00",
        },
    )

    await notification_subscribers.handle_schedule_reminder_due(event)

    assert gate_mock.await_count == 1
    _db, kwargs = gate_mock.call_args.args[0], gate_mock.call_args.kwargs
    assert kwargs["user_id"] == user_id
    assert kwargs["type"] == "reminder"
    assert "Standup" in kwargs["title"]


@pytest.mark.asyncio
async def test_handle_schedule_reminder_due_skips_non_push(monkeypatch):
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    event = EventEnvelope(
        type="schedule.reminder.due",
        source="test",
        user_id=uuid4(),
        payload={"method": "email"},
    )

    await notification_subscribers.handle_schedule_reminder_due(event)

    assert gate_mock.await_count == 0


@pytest.mark.asyncio
async def test_reminder_body_shows_start_time_not_reminder_time(monkeypatch):
    """The regression this file exists to prevent from coming back.

    `scheduled_at` is the moment the *reminder* fires — `reminder_service`
    computes it as `start_time - minutes_before`. Rendering it as the start
    time told the user a 14:00 meeting began at 13:45, and did it in UTC on
    top, so a Vietnamese user read "07:00" for a 14:00 event. The body must
    come from `start_time`, converted to `settings.DISPLAY_TIMEZONE`.
    """
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)
    monkeypatch.setattr(settings, "DISPLAY_TIMEZONE", "Asia/Ho_Chi_Minh")

    event = EventEnvelope(
        type="schedule.reminder.due",
        source="test",
        user_id=uuid4(),
        payload={
            "method": "push",
            "schedule_id": str(uuid4()),
            "schedule_title": "Standup",
            # 07:00Z == 14:00 in Asia/Ho_Chi_Minh; the reminder fired 15
            # minutes earlier, at 06:45Z.
            "scheduled_at": "2026-08-10T06:45:00+00:00",
            "start_time": "2026-08-10T07:00:00+00:00",
            "reminder_offset_minutes": 15,
        },
    )

    await notification_subscribers.handle_schedule_reminder_due(event)

    body = gate_mock.call_args.kwargs["body"]
    assert "14:00" in body, body
    assert "13:45" not in body
    assert "06:45" not in body and "07:00" not in body
    # The stored payload must name the same instant the text does.
    assert gate_mock.call_args.kwargs["payload"]["start_time"] == "2026-08-10T07:00:00+00:00"


@pytest.mark.asyncio
async def test_reminder_body_falls_back_when_start_time_absent(monkeypatch):
    """Events already on the Redis stream predate `start_time`. Replaying
    one must not crash and must not fall back to `scheduled_at` — saying
    nothing about the clock beats naming the wrong hour."""
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    event = EventEnvelope(
        type="schedule.reminder.due",
        source="test",
        user_id=uuid4(),
        payload={
            "method": "push",
            "schedule_id": str(uuid4()),
            "schedule_title": "Standup",
            "scheduled_at": "2026-08-10T06:45:00+00:00",
        },
    )

    await notification_subscribers.handle_schedule_reminder_due(event)

    body = gate_mock.call_args.kwargs["body"]
    assert body == "Sắp bắt đầu"
    assert "06:45" not in body


@pytest.mark.asyncio
async def test_reminder_body_appends_location(monkeypatch):
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)
    monkeypatch.setattr(settings, "DISPLAY_TIMEZONE", "Asia/Ho_Chi_Minh")

    event = EventEnvelope(
        type="schedule.reminder.due",
        source="test",
        user_id=uuid4(),
        payload={
            "method": "push",
            "schedule_id": str(uuid4()),
            "schedule_title": "Standup",
            "scheduled_at": "2026-08-10T06:45:00+00:00",
            "start_time": "2026-08-10T07:00:00+00:00",
            "location": "Phòng họp A",
        },
    )

    await notification_subscribers.handle_schedule_reminder_due(event)

    assert "Phòng họp A" in gate_mock.call_args.kwargs["body"]


@pytest.mark.asyncio
async def test_due_soon_under_one_hour_does_not_say_zero_hours(monkeypatch):
    """`hours_until_due` is a floor, so a task due in 50 minutes arrives as
    0. "Còn 0 giờ." reads as already expired — the opposite of the nudge."""
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    event = EventEnvelope(
        type="task.due_soon",
        source="test",
        user_id=uuid4(),
        payload={"task_id": str(uuid4()), "title": "Nộp hồ sơ", "hours_until_due": 0},
    )

    await notification_subscribers.handle_task_due_soon(event)

    body = gate_mock.call_args.kwargs["body"]
    assert body.startswith("Còn dưới 1 giờ")
    assert "0 giờ" not in body


# ---------------------------------------------------------------------------
# Digests must name work, not just count it
# ---------------------------------------------------------------------------


def _item(title, due=None, priority=None):
    return {"task_id": str(uuid4()), "title": title, "due_date": due, "priority": priority}


def _content_text(gate_mock) -> str:
    blocks = gate_mock.call_args.kwargs.get("content") or []
    return "\n".join(b["text"] for b in blocks)


@pytest.mark.asyncio
async def test_day_plan_lists_todays_work_and_keeps_carry_over_separate(monkeypatch):
    """The start-of-day briefing. Carried-over work is labelled as such
    rather than blended into "you have 3 things", because it is the part
    the plan has to confront first."""
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)
    monkeypatch.setattr(settings, "DISPLAY_TIMEZONE", "Asia/Ho_Chi_Minh")

    event = EventEnvelope(
        type="day.plan",
        source="test",
        user_id=uuid4(),
        payload={
            "due_today_count": 1,
            "carried_over_count": 1,
            "schedule_count": 1,
            "due_today": [_item("Nộp hồ sơ thầu", "2026-08-24T17:00:00", "urgent")],
            "carried_over": [_item("Viết báo cáo Q3", "2026-08-21T00:00:00", "high")],
            "schedules": [{
                "schedule_id": str(uuid4()), "title": "Họp khách hàng",
                "start_time": "2026-08-24T07:00:00+00:00", "location": "Phòng A",
            }],
        },
    )

    await notification_subscribers.handle_day_plan(event)

    kwargs = gate_mock.call_args.kwargs
    assert kwargs["reason_key"] == "day.plan"
    assert kwargs["type"] == "day_plan"
    text = _content_text(gate_mock)
    assert "Nộp hồ sơ thầu" in text
    assert "Viết báo cáo Q3" in text
    assert "Họp khách hàng" in text
    # The two task lists stay under separate headings.
    assert "Đến hạn hôm nay:" in text
    assert "Trễ từ trước, cần xử lý:" in text
    # Meeting time is converted; the task deadline is not.
    assert "14:00 24/08" in text


@pytest.mark.asyncio
async def test_day_plan_still_speaks_when_only_meetings_are_scheduled(monkeypatch):
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    event = EventEnvelope(
        type="day.plan",
        source="test",
        user_id=uuid4(),
        payload={
            "due_today_count": 0, "carried_over_count": 0, "schedule_count": 1,
            "due_today": [], "carried_over": [],
            "schedules": [{
                "schedule_id": str(uuid4()), "title": "Standup",
                "start_time": "2026-08-24T02:00:00+00:00", "location": None,
            }],
        },
    )

    await notification_subscribers.handle_day_plan(event)

    body = gate_mock.call_args.kwargs["body"]
    assert "chưa có việc đến hạn" in body
    assert "Standup" in _content_text(gate_mock)


@pytest.mark.asyncio
async def test_day_review_reports_both_halves_of_the_day(monkeypatch):
    """Two counts made a productive day and a wasted one read identically."""
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    event = EventEnvelope(
        type="day.review",
        source="test",
        user_id=uuid4(),
        payload={
            "open_task_count": 2, "overdue_task_count": 1, "completed_today_count": 1,
            "completed_today": [_item("Sửa bug đăng nhập", None, "high")],
            "still_open": [_item("Viết báo cáo Q3", "2026-08-21T00:00:00", "high")],
        },
    )

    await notification_subscribers.handle_day_review(event)

    body = gate_mock.call_args.kwargs["body"]
    assert "Xong 1 việc hôm nay" in body
    text = _content_text(gate_mock)
    assert "Đã hoàn thành hôm nay:" in text
    assert "Sửa bug đăng nhập" in text
    assert "Còn đọng lại:" in text
    assert "Viết báo cáo Q3" in text


@pytest.mark.asyncio
async def test_at_risk_shows_the_inputs_the_risk_score_was_built_from(monkeypatch):
    """`risk_score` alone is uninterpretable — 12.0 means nothing without
    the deadline missed, the priority, and the work stuck behind it, which
    are exactly the three `compute_risk` multiplies."""
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    event = EventEnvelope(
        type="task.at_risk",
        source="test",
        user_id=uuid4(),
        payload={
            "task_id": str(uuid4()), "title": "Viết báo cáo Q3", "risk_score": 12.0,
            "overdue_days": 3, "open_subtask_count": 2, "priority": "high",
            "due_date": "2026-08-21T17:00:00",
            "open_subtasks": [_item("Thu thập số liệu", "2026-08-20T00:00:00", "high"),
                              _item("Vẽ biểu đồ")],
        },
    )

    await notification_subscribers.handle_task_at_risk(event)

    body = gate_mock.call_args.kwargs["body"]
    assert "Trễ 3 ngày" in body
    assert "21/08 17:00" in body
    assert "ưu tiên cao" in body
    assert "2 việc con" in body
    text = _content_text(gate_mock)
    assert "Thu thập số liệu" in text
    assert "Vẽ biểu đồ" in text


@pytest.mark.asyncio
async def test_blocked_cascade_names_the_subtasks_and_drops_the_wrong_label(monkeypatch):
    """"Đang bị chặn" said the opposite of what this reason detects:
    nothing is blocking the parent, other work is stuck behind it."""
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    event = EventEnvelope(
        type="task.blocked_cascade",
        source="test",
        user_id=uuid4(),
        payload={
            "task_id": str(uuid4()), "title": "Chuẩn bị demo", "overdue_days": 2,
            "open_subtask_count": 1, "priority": "medium", "due_date": "2026-08-22T00:00:00",
            "open_subtasks": [_item("Dựng dữ liệu mẫu", "2026-08-23T00:00:00", "medium")],
        },
    )

    await notification_subscribers.handle_task_blocked_cascade(event)

    title = gate_mock.call_args.kwargs["title"]
    assert "Đang bị chặn" not in title
    assert "Chuẩn bị demo" in title
    assert "Dựng dữ liệu mẫu" in _content_text(gate_mock)


@pytest.mark.asyncio
async def test_overdue_names_the_deadline_it_missed(monkeypatch):
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    event = EventEnvelope(
        type="task.overdue",
        source="test",
        user_id=uuid4(),
        payload={
            "task_id": str(uuid4()), "title": "Viết báo cáo Q3", "overdue_days": 3,
            "due_date": "2026-08-21T17:00:00", "priority": "high",
        },
    )

    await notification_subscribers.handle_task_overdue(event)

    body = gate_mock.call_args.kwargs["body"]
    assert "Trễ 3 ngày" in body
    assert "21/08 17:00" in body
    assert "ưu tiên cao" in body


@pytest.mark.asyncio
async def test_digests_survive_events_that_predate_the_detail_fields(monkeypatch):
    """Events already on the Redis stream carry only the old counts.
    Replaying one must degrade to the summary line, not raise."""
    gate_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(notification_subscribers, "request_attention_async", gate_mock)

    old_review = EventEnvelope(
        type="day.review", source="test", user_id=uuid4(),
        payload={"open_task_count": 5, "overdue_task_count": 2},
    )
    old_cascade = EventEnvelope(
        type="task.blocked_cascade", source="test", user_id=uuid4(),
        payload={"task_id": str(uuid4()), "title": "X", "overdue_days": 2, "open_subtask_count": 3},
    )

    await notification_subscribers.handle_day_review(old_review)
    await notification_subscribers.handle_task_blocked_cascade(old_cascade)

    assert gate_mock.await_count == 2
    assert "còn 5 việc chưa xong" in gate_mock.call_args_list[0].kwargs["body"]
