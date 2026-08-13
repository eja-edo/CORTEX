"""Event Bus subscribers that turn domain events into Notification rows."""

from datetime import datetime

from app.database_async import AsyncSessionLocal
from app.events.schemas import EventEnvelope
from app.services.attention_gate import request_attention_async
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def handle_schedule_reminder_due(event: EventEnvelope) -> None:
    """Create an in-app push notification for a due schedule reminder.

    Email reminders are handled elsewhere (not yet implemented) and don't
    get an in-app Notification row.
    """
    if event.payload.get("method") != "push":
        return
    if event.user_id is None:
        logger.warning("schedule.reminder.due event missing user_id, skipping: %s", event.event_id)
        return

    schedule_title = event.payload.get("schedule_title", "")
    scheduled_at = event.payload.get("scheduled_at", "")
    try:
        body = f"Starts at {datetime.fromisoformat(scheduled_at).strftime('%H:%M')}"
    except (TypeError, ValueError):
        body = "Starts soon"

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="reminder",
            title=f"Reminder: {schedule_title}",
            body=body,
            actions=[{"label": "View", "action": "navigate", "url": "/schedule"}],
            payload={
                "schedule_id": event.payload.get("schedule_id"),
                "start_time": scheduled_at,
            },
        )
