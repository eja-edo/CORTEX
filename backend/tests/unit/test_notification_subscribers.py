"""Milestone 4.3 M3: the schedule.reminder.due -> Notification path must go
through the Attention Gate (app.services.attention_gate), not write to the
notifications table directly."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

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
