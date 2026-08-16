"""Event Bus subscribers that turn domain events into attention candidates.

Each handler names its own `item_type`/`item_id`/`reason_key` and hands the
rest to the Attention Gate (6.1) — dedup, importance, and the busy check
happen there, not here. A handler that instead composed a Notification
directly would be exactly the "N producers = N sources of spam" pattern the
planning doc's boundary #1 rules out.
"""

from datetime import datetime
from uuid import UUID

from app.database_async import AsyncSessionLocal
from app.events.schemas import EventEnvelope
from app.models import AttentionItemType
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

    schedule_id = event.payload.get("schedule_id")

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="reminder",
            title=f"Reminder: {schedule_title}",
            body=body,
            actions=[{"label": "View", "action": "navigate", "url": "/schedule"}],
            payload={
                "schedule_id": schedule_id,
                "start_time": scheduled_at,
            },
            item_type=AttentionItemType.SCHEDULE,
            item_id=UUID(schedule_id) if schedule_id else None,
            reason_key="schedule.reminder.due",
        )


async def handle_task_overdue(event: EventEnvelope) -> None:
    """First real detection→delivery path for a task: until now,
    `task.overdue` (published by the State Evaluator, 4.6) only fed the
    "Hôm nay" screen (3.1) — nothing proactively told the user. This closes
    that loop through the Gate rather than by notifying directly.
    """
    if event.user_id is None:
        logger.warning("task.overdue event missing user_id, skipping: %s", event.event_id)
        return

    task_id = event.payload.get("task_id")
    if not task_id:
        logger.warning("task.overdue event missing task_id, skipping: %s", event.event_id)
        return

    title = event.payload.get("title", "")
    overdue_days = event.payload.get("overdue_days", 0)

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="task_overdue",
            title=f"Quá hạn: {title}",
            body=f"Trễ {overdue_days} ngày.",
            actions=[{"label": "Xem", "action": "navigate", "url": "/tasks"}],
            payload={"task_id": task_id, "overdue_days": overdue_days},
            item_type=AttentionItemType.TASK,
            item_id=UUID(task_id),
            reason_key="task.overdue",
        )


async def handle_task_due_soon(event: EventEnvelope) -> None:
    """Detection→delivery for `task.due_soon` (A1) — a softer, earlier nudge
    than `task.overdue`: the task hasn't been started and its due date is
    coming up, so the Gate gets a chance to say something before it's late."""
    if event.user_id is None:
        logger.warning("task.due_soon event missing user_id, skipping: %s", event.event_id)
        return

    task_id = event.payload.get("task_id")
    if not task_id:
        logger.warning("task.due_soon event missing task_id, skipping: %s", event.event_id)
        return

    title = event.payload.get("title", "")
    hours_until_due = event.payload.get("hours_until_due", 0)

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="task_due_soon",
            title=f"Sắp đến hạn: {title}",
            body=f"Còn {hours_until_due} giờ.",
            actions=[{"label": "Xem", "action": "navigate", "url": "/tasks"}],
            payload={"task_id": task_id, "hours_until_due": hours_until_due},
            item_type=AttentionItemType.TASK,
            item_id=UUID(task_id),
            reason_key="task.due_soon",
        )


async def handle_task_stale(event: EventEnvelope) -> None:
    """Detection→delivery for `task.stale` (A1) — an open, undated task
    nobody has touched in a while. Nothing else in the product surfaces
    a forgotten task with no deadline; this is that path."""
    if event.user_id is None:
        logger.warning("task.stale event missing user_id, skipping: %s", event.event_id)
        return

    task_id = event.payload.get("task_id")
    if not task_id:
        logger.warning("task.stale event missing task_id, skipping: %s", event.event_id)
        return

    title = event.payload.get("title", "")
    days_since_update = event.payload.get("days_since_update", 0)

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="task_stale",
            title=f"Việc bị bỏ quên: {title}",
            body=f"Chưa động tới trong {days_since_update} ngày.",
            actions=[{"label": "Xem", "action": "navigate", "url": "/tasks"}],
            payload={"task_id": task_id, "days_since_update": days_since_update},
            item_type=AttentionItemType.TASK,
            item_id=UUID(task_id),
            reason_key="task.stale",
        )


async def handle_task_blocked_cascade(event: EventEnvelope) -> None:
    """Detection→delivery for `task.blocked_cascade` (A1) — the
    parent-task replacement for "goal blocked": a parent is overdue and
    still has subtasks open under it."""
    if event.user_id is None:
        logger.warning("task.blocked_cascade event missing user_id, skipping: %s", event.event_id)
        return

    task_id = event.payload.get("task_id")
    if not task_id:
        logger.warning("task.blocked_cascade event missing task_id, skipping: %s", event.event_id)
        return

    title = event.payload.get("title", "")
    overdue_days = event.payload.get("overdue_days", 0)
    open_subtask_count = event.payload.get("open_subtask_count", 0)

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="task_blocked_cascade",
            title=f"Đang bị chặn: {title}",
            body=f"Trễ {overdue_days} ngày, còn {open_subtask_count} việc con chưa xong.",
            actions=[{"label": "Xem", "action": "navigate", "url": "/tasks"}],
            payload={
                "task_id": task_id,
                "overdue_days": overdue_days,
                "open_subtask_count": open_subtask_count,
            },
            item_type=AttentionItemType.TASK,
            item_id=UUID(task_id),
            reason_key="task.blocked_cascade",
        )


async def handle_schedule_starts_soon(event: EventEnvelope) -> None:
    """Detection→delivery for `schedule.starts_soon` (A1) — separate from
    `schedule.reminder.due` (a reminder the user explicitly set): this
    fires from the schedule itself, with no reminder configuration needed,
    and doubles as the lead time the Gate needs to go quiet *before* the
    meeting starts (step 3, `should_stay_quiet`)."""
    if event.user_id is None:
        logger.warning("schedule.starts_soon event missing user_id, skipping: %s", event.event_id)
        return

    schedule_id = event.payload.get("schedule_id")
    if not schedule_id:
        logger.warning("schedule.starts_soon event missing schedule_id, skipping: %s", event.event_id)
        return

    title = event.payload.get("title", "")
    minutes_until_start = event.payload.get("minutes_until_start", 0)

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="schedule_starts_soon",
            title=f"Sắp bắt đầu: {title}",
            body=f"Còn {minutes_until_start} phút.",
            actions=[{"label": "Xem", "action": "navigate", "url": "/schedule"}],
            payload={"schedule_id": schedule_id, "minutes_until_start": minutes_until_start},
            item_type=AttentionItemType.SCHEDULE,
            item_id=UUID(schedule_id),
            reason_key="schedule.starts_soon",
        )


async def handle_day_review(event: EventEnvelope) -> None:
    """Detection→delivery for `day.review` (A1) — per-user, not per-item
    (see `AttentionItemType.USER`'s docstring): a natural end-of-day point
    to say "here's what's still open", and the doc's intended anchor for
    the Gate's step-5 bundling once there's more than one predicate firing
    around the same time of day."""
    if event.user_id is None:
        logger.warning("day.review event missing user_id, skipping: %s", event.event_id)
        return

    open_task_count = event.payload.get("open_task_count", 0)
    overdue_task_count = event.payload.get("overdue_task_count", 0)

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="day_review",
            title="Tổng kết cuối ngày",
            body=f"Còn {open_task_count} việc chưa xong, {overdue_task_count} việc quá hạn.",
            actions=[{"label": "Xem", "action": "navigate", "url": "/today"}],
            payload={"open_task_count": open_task_count, "overdue_task_count": overdue_task_count},
            item_type=AttentionItemType.USER,
            item_id=event.user_id,
            reason_key="day.review",
        )


# The canonical list of "the backend already delivers this event directly,
# bypassing workflow_service" (Milestone A3). `app/__init__.py` subscribes
# each of these at startup instead of hardcoding one `event_bus.subscribe`
# call per handler — this dict is that subscription list, not just a
# lookup table, so the two can't drift apart.
#
# Exported into `event_vocabulary.json` (see
# `backend/scripts/generate_event_vocabulary.py`) as
# `has_direct_backend_delivery`, which is what workflow_service's conflict
# detector (`app/services/workflow_conflicts.py`) reads: seeding or letting
# a user create a workflow that triggers on one of these events with an
# `action.request_attention` node would fire a second notification for the
# same condition — this is exactly the bug A3 exists to catch (see
# `docs/planning-v3.md`'s A3 section for the real incident).
DIRECT_DELIVERY_HANDLERS = {
    "schedule.reminder.due": handle_schedule_reminder_due,
    "task.overdue": handle_task_overdue,
    "task.due_soon": handle_task_due_soon,
    "task.stale": handle_task_stale,
    "task.blocked_cascade": handle_task_blocked_cascade,
    "schedule.starts_soon": handle_schedule_starts_soon,
    "day.review": handle_day_review,
}
