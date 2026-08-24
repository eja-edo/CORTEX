"""Event Bus subscribers that turn domain events into attention candidates.

Each handler names its own `item_type`/`item_id`/`reason_key` and hands the
rest to the Attention Gate (6.1) — dedup, importance, and the busy check
happen there, not here. A handler that instead composed a Notification
directly would be exactly the "N producers = N sources of spam" pattern the
planning doc's boundary #1 rules out.
"""

from uuid import UUID

from app.database_async import AsyncSessionLocal
from app.events.schemas import EventEnvelope
from app.models import AttentionItemType
from app.services.attention_gate import request_attention_async
from app.services.notification_format import (
    MAX_LISTED_ITEMS,
    join_facts,
    local_clock,
    overflow_line,
    priority_label,
    schedule_line,
    task_due_stamp,
    task_line,
    text_blocks,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _listed(items: list[dict], total: int, *, heading: str, formatter=task_line, noun: str = "việc") -> list[str]:
    """A heading, up to MAX_LISTED_ITEMS lines, then an honest remainder.

    The counts these digests used to lead with aren't wrong, they were just
    the *only* thing there — so they stay, as the tail of a list the user
    can actually read, instead of standing in for it.
    """
    if not items:
        return []
    lines = [heading]
    lines.extend(formatter(item) for item in items[:MAX_LISTED_ITEMS])
    tail = overflow_line(min(len(items), MAX_LISTED_ITEMS), total, noun=noun)
    if tail:
        lines.append(tail)
    return lines


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
    # `start_time`, never `scheduled_at`: the latter is when this reminder
    # fires (start minus the offset), so rendering it as the start time
    # announced a 14:00 meeting as starting at 13:45. Older events on a
    # replayed queue may predate the field — fall back rather than lie.
    start_time = event.payload.get("start_time")
    clock = local_clock(start_time)
    body = f"Bắt đầu lúc {clock}" if clock else "Sắp bắt đầu"
    location = event.payload.get("location")
    if location:
        body += f" — {location}"

    schedule_id = event.payload.get("schedule_id")

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="reminder",
            title=f"Nhắc lịch: {schedule_title}",
            body=body,
            actions=[{"label": "Xem", "action": "navigate", "url": "/schedule"}],
            payload={
                "schedule_id": schedule_id,
                "start_time": start_time,
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
    # The deadline it actually missed, and how much the miss costs. "Trễ 3
    # ngày" alone left the user to go look up both.
    due_stamp = task_due_stamp(event.payload.get("due_date"))
    body = join_facts(
        f"Trễ {overdue_days} ngày",
        f"hạn {due_stamp}" if due_stamp else None,
        priority_label(event.payload.get("priority")),
    )

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="task_overdue",
            title=f"Quá hạn: {title}",
            body=body,
            actions=[{"label": "Xem", "action": "navigate", "url": "/tasks"}],
            payload={
                "task_id": task_id,
                "overdue_days": overdue_days,
                "due_date": event.payload.get("due_date"),
                "priority": event.payload.get("priority"),
            },
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
    # `hours_until_due` is a floor, so anything under an hour arrives as 0 —
    # "Còn 0 giờ" reads as already expired, the opposite of this nudge.
    remaining = "Còn dưới 1 giờ" if hours_until_due < 1 else f"Còn {hours_until_due} giờ"
    due_stamp = task_due_stamp(event.payload.get("due_date"))
    body = join_facts(
        remaining,
        f"hạn {due_stamp}" if due_stamp else None,
        priority_label(event.payload.get("priority")),
    )

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="task_due_soon",
            title=f"Sắp đến hạn: {title}",
            body=body,
            actions=[{"label": "Xem", "action": "navigate", "url": "/tasks"}],
            payload={
                "task_id": task_id,
                "hours_until_due": hours_until_due,
                "due_date": event.payload.get("due_date"),
                "priority": event.payload.get("priority"),
            },
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
    body = join_facts(
        f"Chưa động tới trong {days_since_update} ngày",
        "chưa đặt hạn",
        priority_label(event.payload.get("priority")),
    )

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="task_stale",
            title=f"Việc bị bỏ quên: {title}",
            body=body,
            actions=[{"label": "Xem", "action": "navigate", "url": "/tasks"}],
            payload={
                "task_id": task_id,
                "days_since_update": days_since_update,
                "priority": event.payload.get("priority"),
            },
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
    open_subtasks = event.payload.get("open_subtasks") or []
    due_stamp = task_due_stamp(event.payload.get("due_date"))

    body = join_facts(
        f"Trễ {overdue_days} ngày",
        f"còn {open_subtask_count} việc con chưa xong",
        f"hạn {due_stamp}" if due_stamp else None,
        priority_label(event.payload.get("priority")),
    )
    content = text_blocks(
        [body] + _listed(open_subtasks, open_subtask_count, heading="Việc con chưa xong:")
    )

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            # "Đang bị chặn" said the opposite of what this reason detects:
            # nothing is blocking the parent, the parent is what other work
            # is stuck behind.
            type="task_blocked_cascade",
            title=f"Còn việc con chưa xong: {title}",
            body=body,
            content=content,
            actions=[{"label": "Xem", "action": "navigate", "url": "/tasks"}],
            payload={
                "task_id": task_id,
                "overdue_days": overdue_days,
                "open_subtask_count": open_subtask_count,
                "open_subtasks": open_subtasks,
                "due_date": event.payload.get("due_date"),
                "priority": event.payload.get("priority"),
            },
            item_type=AttentionItemType.TASK,
            item_id=UUID(task_id),
            reason_key="task.blocked_cascade",
        )


async def handle_task_at_risk(event: EventEnvelope) -> None:
    """Detection→delivery for `task.at_risk` (6.8/4.4) — an escalation on
    top of `task.overdue`: this task's combined priority, lateness, and
    blocked subtasks crossed `compute_risk`'s threshold, not just its due
    date. Fires alongside `task.overdue` for the same task, at a higher
    base level (ASK vs RECOMMEND) — see attention_reason_catalog.py."""
    if event.user_id is None:
        logger.warning("task.at_risk event missing user_id, skipping: %s", event.event_id)
        return

    task_id = event.payload.get("task_id")
    if not task_id:
        logger.warning("task.at_risk event missing task_id, skipping: %s", event.event_id)
        return

    title = event.payload.get("title", "")
    risk_score = event.payload.get("risk_score", 0)
    overdue_days = event.payload.get("overdue_days", 0)
    open_subtask_count = event.payload.get("open_subtask_count", 0)
    open_subtasks = event.payload.get("open_subtasks") or []
    due_stamp = task_due_stamp(event.payload.get("due_date"))

    # This reason exists to say *why* one late task is worse than another,
    # so it has to show its working. `compute_risk` multiplies exactly these
    # three, and the body used to name only one of them.
    body = join_facts(
        f"Trễ {overdue_days} ngày",
        f"hạn {due_stamp}" if due_stamp else None,
        priority_label(event.payload.get("priority")),
        f"còn {open_subtask_count} việc con chưa xong" if open_subtask_count else None,
    )
    lines = [body]
    if open_subtasks:
        lines.extend(_listed(open_subtasks, open_subtask_count, heading="Đang kẹt lại phía sau:"))
    lines.append("Nguy cơ trễ tiếp tục tăng nếu chưa xử lý.")

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="task_at_risk",
            title=f"Rủi ro cao: {title}",
            body=body,
            content=text_blocks(lines),
            actions=[{"label": "Xem", "action": "navigate", "url": "/tasks"}],
            payload={
                "task_id": task_id,
                "risk_score": risk_score,
                "overdue_days": overdue_days,
                "open_subtask_count": open_subtask_count,
                "open_subtasks": open_subtasks,
                "due_date": event.payload.get("due_date"),
                "priority": event.payload.get("priority"),
            },
            item_type=AttentionItemType.TASK,
            item_id=UUID(task_id),
            reason_key="task.at_risk",
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
    clock = local_clock(event.payload.get("start_time"))
    body = join_facts(
        f"Còn {minutes_until_start} phút",
        f"bắt đầu {clock}" if clock else None,
        event.payload.get("location") or None,
    )

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="schedule_starts_soon",
            title=f"Sắp bắt đầu: {title}",
            body=body,
            actions=[{"label": "Xem", "action": "navigate", "url": "/schedule"}],
            payload={
                "schedule_id": schedule_id,
                "minutes_until_start": minutes_until_start,
                "start_time": event.payload.get("start_time"),
                "location": event.payload.get("location"),
            },
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
    completed_count = event.payload.get("completed_today_count", 0)
    completed_today = event.payload.get("completed_today") or []
    still_open = event.payload.get("still_open") or []

    body = join_facts(
        f"Xong {completed_count} việc hôm nay",
        f"còn {open_task_count} việc chưa xong",
        f"{overdue_task_count} việc quá hạn" if overdue_task_count else None,
    )
    lines = [body]
    lines.extend(_listed(completed_today, completed_count, heading="Đã hoàn thành hôm nay:"))
    lines.extend(_listed(still_open, open_task_count, heading="Còn đọng lại:"))

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="day_review",
            title="Tổng kết cuối ngày",
            body=body,
            content=text_blocks(lines),
            actions=[{"label": "Xem", "action": "navigate", "url": "/today"}],
            payload={
                "open_task_count": open_task_count,
                "overdue_task_count": overdue_task_count,
                "completed_today_count": completed_count,
                "completed_today": completed_today,
                "still_open": still_open,
            },
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
async def handle_day_plan(event: EventEnvelope) -> None:
    """Detection→delivery for `day.plan` — the start-of-day briefing.

    The only reason here that isn't a warning. Every task predicate fires
    off a deadline that is already close or already missed, so before this
    existed the first thing Cortex said about a day's work was that some of
    it had gone wrong. This is the one that arrives while the day can still
    be planned, which is also why it leads with what is *due today* and
    keeps carried-over work as a second, separately-labelled list rather
    than blending the two into one count.
    """
    if event.user_id is None:
        logger.warning("day.plan event missing user_id, skipping: %s", event.event_id)
        return

    due_today_count = event.payload.get("due_today_count", 0)
    carried_over_count = event.payload.get("carried_over_count", 0)
    schedule_count = event.payload.get("schedule_count", 0)
    due_today = event.payload.get("due_today") or []
    carried_over = event.payload.get("carried_over") or []
    schedules = event.payload.get("schedules") or []

    body = join_facts(
        f"{due_today_count} việc đến hạn hôm nay" if due_today_count else "Hôm nay chưa có việc đến hạn",
        f"{carried_over_count} việc trễ từ trước" if carried_over_count else None,
        f"{schedule_count} lịch" if schedule_count else None,
    )
    lines = [body]
    lines.extend(_listed(due_today, due_today_count, heading="Đến hạn hôm nay:"))
    lines.extend(_listed(carried_over, carried_over_count, heading="Trễ từ trước, cần xử lý:"))
    lines.extend(
        _listed(schedules, schedule_count, heading="Lịch hôm nay:", formatter=schedule_line, noun="lịch")
    )

    async with AsyncSessionLocal() as db:
        await request_attention_async(
            db,
            user_id=event.user_id,
            type="day_plan",
            title="Kế hoạch hôm nay",
            body=body,
            content=text_blocks(lines),
            actions=[{"label": "Xem", "action": "navigate", "url": "/today"}],
            payload={
                "due_today_count": due_today_count,
                "carried_over_count": carried_over_count,
                "schedule_count": schedule_count,
                "due_today": due_today,
                "carried_over": carried_over,
                "schedules": schedules,
            },
            # Per-user, not per-item — same reasoning as `day.review`.
            item_type=AttentionItemType.USER,
            item_id=event.user_id,
            reason_key="day.plan",
        )


DIRECT_DELIVERY_HANDLERS = {
    "schedule.reminder.due": handle_schedule_reminder_due,
    "task.overdue": handle_task_overdue,
    "task.due_soon": handle_task_due_soon,
    "task.stale": handle_task_stale,
    "task.blocked_cascade": handle_task_blocked_cascade,
    "task.at_risk": handle_task_at_risk,
    "schedule.starts_soon": handle_schedule_starts_soon,
    "day.review": handle_day_review,
    "day.plan": handle_day_plan,
}
