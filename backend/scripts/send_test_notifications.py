"""Fire every detection reason at a real user, end to end, and report what
actually reached Mezon.

**What this exercises.** It publishes the real events onto the real Event
Bus. It does *not* call the bot's `/internal/deliver` directly and it does
not compose notification text itself — so everything in between is under
test: `notification_subscribers` (the wording), the Attention Gate (level,
dedup, supersession, quiet hours), `plan_deliveries` (the per-channel
`min_level` floor) and `DeliveryWorker` (the DM itself). A script that
POSTed to the bot would prove only that the bot renders, which is the one
part least likely to be wrong.

**How the events get there.** The running backend subscribes
`DIRECT_DELIVERY_HANDLERS` and starts the Event Bus's durable cross-process
consumer at startup (see `app/__init__.py`), so an event published from
this separate process is picked up there and routed to the real handlers.
Nothing needs to be subscribed here.

    # what would be sent, no writes, no DMs
    venv/bin/python scripts/send_test_notifications.py --dry-run

    # the real thing
    venv/bin/python scripts/send_test_notifications.py --email you@example.com

    # leave the seeded tasks behind to inspect them
    venv/bin/python scripts/send_test_notifications.py --keep

**Requirements**, all checked before anything is published:
  * the backend is running (it owns the subscribers and the delivery worker)
  * the user has a verified, enabled Mezon `user_channel`
  * that channel's `min_level` is low enough for the reason's level —
    `MezonAdapter.default_min_level` is RECOMMEND, so the four INFORM
    reasons stay in-app unless the user lowered their own floor

**One deliberate wrinkle.** `task.overdue`, `task.blocked_cascade` and
`task.at_risk` are nested predicates and the Gate collapses them
(`attention_reason_catalog.SUPERSEDES`). Pointing all three at one task
would correctly produce a single DM — which is right, but useless for
eyeballing three renders. So each gets its own seeded task, and
`--same-task` exists to demonstrate the collapse on purpose.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database_async import make_async_sessionmaker  # noqa: E402
from app.events.event_bus import EventBus  # noqa: E402
from app.events.schemas import EventEnvelope  # noqa: E402
from app.models import (  # noqa: E402
    AttentionChannel,
    AttentionLog,
    Notification,
    NotificationDelivery,
    Schedule,
    ScheduleType,
    Task,
    TaskPriority,
    TaskStatus,
    User,
    UserChannel,
)

# Everything this script creates is prefixed, so teardown can be exact and
# a stray run can never delete a real task.
PREFIX = "[notif-test] "

TODAY = date.today()
NOW = datetime.now(timezone.utc)


def _dt(day: date, hour: int = 0, minute: int = 0) -> datetime:
    """Naive, for `Task.due_date` — a wall-clock deadline, not an instant."""
    return datetime.combine(day, time(hour, minute))


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


async def seed(db, user_id: UUID) -> dict:
    """Real rows, so the digest lines read like real work and the "Xem"
    link lands on something that exists."""

    def task(title, *, status=TaskStatus.TODO, due=None, priority=None, parent=None):
        row = Task(
            user_id=user_id, title=f"{PREFIX}{title}", status=status,
            due_date=due, priority=priority, parent_task_id=parent,
        )
        db.add(row)
        return row

    # task.overdue / task.due_soon / task.stale — one each, so nothing
    # supersedes anything.
    overdue = task("Viết báo cáo Q3", due=_dt(TODAY - timedelta(days=3), 17), priority=TaskPriority.HIGH)
    due_soon = task("Nộp hồ sơ thầu", due=_dt(TODAY, 17), priority=TaskPriority.URGENT)
    stale = task("Dọn backlog", due=None, priority=TaskPriority.LOW)

    # task.blocked_cascade — its own parent, with children to name.
    cascade = task("Chuẩn bị demo", due=_dt(TODAY - timedelta(days=2)), priority=TaskPriority.MEDIUM)

    # task.at_risk — a separate parent, likewise.
    risky = task("Chốt hợp đồng nhà cung cấp", due=_dt(TODAY - timedelta(days=4), 9), priority=TaskPriority.URGENT)

    # Finished today, so day.review has a "đã hoàn thành" half to report.
    done = task("Sửa bug đăng nhập", status=TaskStatus.DONE, priority=TaskPriority.HIGH)
    done.completed_at = _dt(TODAY, 9)

    await db.flush()

    cascade_kids = [
        task("Dựng dữ liệu mẫu", due=_dt(TODAY - timedelta(days=1)), priority=TaskPriority.MEDIUM, parent=cascade.id),
    ]
    risky_kids = [
        task("Thu thập số liệu bán hàng", due=_dt(TODAY - timedelta(days=5)), priority=TaskPriority.HIGH, parent=risky.id),
        task("Vẽ biểu đồ tăng trưởng", parent=risky.id),
    ]

    start = NOW + timedelta(minutes=25)
    meeting = Schedule(
        user_id=user_id, title=f"{PREFIX}Họp khách hàng", type=ScheduleType.PERSONAL,
        start_time=start, end_time=start + timedelta(hours=1), location="Phòng A",
    )
    db.add(meeting)

    await db.commit()
    for row in (overdue, due_soon, stale, cascade, risky, done, meeting, *cascade_kids, *risky_kids):
        await db.refresh(row)

    return {
        "overdue": overdue, "due_soon": due_soon, "stale": stale,
        "cascade": cascade, "cascade_kids": cascade_kids,
        "risky": risky, "risky_kids": risky_kids,
        "done": done, "meeting": meeting,
    }


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def _item(task: Task) -> dict:
    return {
        "task_id": str(task.id),
        "title": task.title,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "priority": task.priority.value if task.priority else None,
    }


def build_events(rows: dict, *, same_task: bool) -> list[tuple[str, dict]]:
    """Ordered strongest-first inside the overdue family, mirroring
    `StateEvaluator._run_loop` — which is what makes `--same-task` show the
    collapse rather than a race."""
    overdue_target = rows["risky"] if same_task else rows["overdue"]
    cascade_target = rows["risky"] if same_task else rows["cascade"]
    cascade_kids = rows["risky_kids"] if same_task else rows["cascade_kids"]

    risky, meeting = rows["risky"], rows["meeting"]
    start = meeting.start_time

    return [
        ("task.at_risk", {
            "task_id": str(risky.id), "title": risky.title, "risk_score": 4 * 4 * 3.0,
            "overdue_days": 4, "open_subtask_count": len(rows["risky_kids"]),
            "priority": "urgent", "due_date": risky.due_date.isoformat(),
            "open_subtasks": [_item(t) for t in rows["risky_kids"]],
        }),
        ("task.blocked_cascade", {
            "task_id": str(cascade_target.id), "title": cascade_target.title,
            "overdue_days": 2, "open_subtask_count": len(cascade_kids),
            "due_date": cascade_target.due_date.isoformat(),
            "priority": cascade_target.priority.value if cascade_target.priority else None,
            "open_subtasks": [_item(t) for t in cascade_kids],
        }),
        ("task.overdue", {
            "task_id": str(overdue_target.id), "title": overdue_target.title,
            "due_date": overdue_target.due_date.isoformat(), "priority": "high", "overdue_days": 3,
        }),
        ("task.due_soon", {
            "task_id": str(rows["due_soon"].id), "title": rows["due_soon"].title,
            "due_date": rows["due_soon"].due_date.isoformat(), "priority": "urgent",
            "hours_until_due": 5,
        }),
        ("task.stale", {
            "task_id": str(rows["stale"].id), "title": rows["stale"].title,
            "created_at": rows["stale"].created_at.isoformat(),
            "days_since_update": 12, "priority": "low",
        }),
        ("schedule.starts_soon", {
            "schedule_id": str(meeting.id), "title": meeting.title,
            "start_time": start.isoformat(), "minutes_until_start": 25,
            "location": meeting.location,
        }),
        ("schedule.reminder.due", {
            "reminder_id": str(uuid4()), "schedule_id": str(meeting.id),
            "schedule_title": meeting.title,
            # The distinction the reminder bug was about: fires 15 minutes
            # before the event, and must print the event's time, not its own.
            "scheduled_at": (start - timedelta(minutes=15)).isoformat(),
            "start_time": start.isoformat(),
            "location": meeting.location, "reminder_offset_minutes": 15, "method": "push",
        }),
        ("day.plan", {
            "due_today_count": 1, "carried_over_count": 3, "schedule_count": 1,
            "due_today": [_item(rows["due_soon"])],
            "carried_over": [_item(rows["overdue"]), _item(rows["cascade"]), _item(rows["risky"])],
            "schedules": [{
                "schedule_id": str(meeting.id), "title": meeting.title,
                "start_time": start.isoformat(), "location": meeting.location,
            }],
        }),
        ("day.review", {
            "open_task_count": 6, "overdue_task_count": 3, "completed_today_count": 1,
            "completed_today": [_item(rows["done"])],
            "still_open": [_item(rows["overdue"]), _item(rows["risky"]), _item(rows["due_soon"])],
        }),
    ]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


async def report(db, user_id: UUID, since: datetime) -> None:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id, Notification.created_at >= since)
        .order_by(Notification.created_at)
    )
    notifications = list(result.scalars().all())

    print(f"\n{'=' * 78}\nNotification rows created: {len(notifications)}\n{'=' * 78}")
    for n in notifications:
        deliveries = (await db.execute(
            select(NotificationDelivery).where(NotificationDelivery.notification_id == n.id)
        )).scalars().all()
        mezon = [d for d in deliveries if d.channel is AttentionChannel.MEZON]
        state = ", ".join(
            f"{d.status.value if hasattr(d.status, 'value') else d.status}"
            + (f" ({d.last_error[:60]})" if getattr(d, "last_error", None) else "")
            for d in mezon
        ) or "no mezon delivery row (below the channel's min_level)"

        print(f"\n[{n.attention_level.value if n.attention_level else '-':9}] {n.reason_key}")
        print(f"  title  : {n.title}")
        print(f"  body   : {n.body}")
        for block in (n.content or [])[1:]:
            if block.get("type") == "text":
                print(f"           {block['text']}")
        print(f"  mezon  : {state}")


async def cleanup(db, user_id: UUID, since: datetime) -> None:
    """Undo everything this run created, including the Gate's own bookkeeping.

    **The attention_log part is what makes the script re-runnable.** Dedup
    keys on `(item_id, reason_key)` inside a 24h window. Task reasons are
    safe across runs because each run seeds new tasks with new ids — but
    `day.plan` and `day.review` are per-user (`item_id = user_id`, see
    `AttentionItemType.USER`), so their rows would suppress the next run's
    digests for a day and the script would look like it had silently
    stopped working. Clearing the log rows this run wrote resets that.
    """
    tasks = (await db.execute(
        select(Task.id).where(Task.user_id == user_id, Task.title.like(f"{PREFIX}%"))
    )).scalars().all()
    if tasks:
        # Children first: parent_task_id is SET NULL on delete, so deleting
        # parents first would orphan the children into real top-level tasks.
        await db.execute(delete(Task).where(Task.parent_task_id.in_(tasks)))
        await db.execute(delete(Task).where(Task.id.in_(tasks)))
    await db.execute(delete(Schedule).where(Schedule.user_id == user_id, Schedule.title.like(f"{PREFIX}%")))

    notification_ids = (await db.execute(
        select(Notification.id).where(
            Notification.user_id == user_id, Notification.created_at >= since
        )
    )).scalars().all()
    if notification_ids:
        # Deliveries first — they carry the FK to the notification.
        await db.execute(
            delete(NotificationDelivery).where(NotificationDelivery.notification_id.in_(notification_ids))
        )
        await db.execute(delete(Notification).where(Notification.id.in_(notification_ids)))

    log_result = await db.execute(
        delete(AttentionLog).where(AttentionLog.user_id == user_id, AttentionLog.surfaced_at >= since)
    )
    await db.commit()
    print(
        f"\nCleaned up: {len(tasks)} task(s) + schedules, {len(notification_ids)} notification(s), "
        f"{log_result.rowcount} attention_log row(s) — safe to re-run immediately."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="target user; defaults to the only user with a Mezon channel")
    parser.add_argument("--dry-run", action="store_true", help="print the events, write nothing, send nothing")
    parser.add_argument("--keep", action="store_true", help="leave the seeded tasks/schedules behind")
    parser.add_argument("--same-task", action="store_true",
                        help="point all three overdue-family reasons at one task, to show the Gate collapse them")
    parser.add_argument("--wait", type=int, default=None,
                        help="seconds to wait for DeliveryWorker (default: 3 sweeps)")
    args = parser.parse_args()

    wait_seconds = args.wait if args.wait is not None else settings.DELIVERY_WORKER_POLL_SECONDS * 3

    engine, session_maker = make_async_sessionmaker()
    try:
        async with session_maker() as db:
            # --- who, and can we even reach them ---
            if args.email:
                user = (await db.execute(select(User).where(User.email == args.email))).scalar_one_or_none()
                if user is None:
                    print(f"No user with email {args.email!r}")
                    return 1
            else:
                channel = (await db.execute(
                    select(UserChannel).where(UserChannel.channel == AttentionChannel.MEZON)
                )).scalars().first()
                if channel is None:
                    print("No Mezon user_channel exists — link an account first (*link in a DM to the bot).")
                    return 1
                user = await db.get(User, channel.user_id)

            channel = (await db.execute(
                select(UserChannel).where(
                    UserChannel.user_id == user.id,
                    UserChannel.channel == AttentionChannel.MEZON,
                )
            )).scalars().first()

            print(f"user      : {user.email} ({user.id})")
            if channel is None:
                print("mezon     : NOT LINKED — nothing will be DM'd, in-app rows only.")
            else:
                print(f"mezon     : address={channel.address} verified={channel.verified_at is not None} "
                      f"enabled={channel.enabled} min_level={channel.min_level.value if channel.min_level else '-'}")
                if channel.verified_at is None:
                    print("            ⚠ unverified — the dispatcher records skipped/unverified instead of sending.")
            print(f"bot url   : {settings.MEZON_BOT_INTERNAL_URL or '(unset — MezonAdapter returns unavailable)'}")

            if args.dry_run:
                # Seeding is a write, so dry-run cannot build real rows; it
                # reports the plan instead of faking one.
                print("\n--dry-run: would seed 9 tasks + 1 schedule, then publish:")
                for event_type, _ in build_events(
                    {k: _Stub() for k in
                     ("overdue", "due_soon", "stale", "cascade", "risky", "done", "meeting")}
                    | {"cascade_kids": [_Stub()], "risky_kids": [_Stub(), _Stub()]},
                    same_task=args.same_task,
                ):
                    print(f"  - {event_type}")
                print("\nNothing was written and no DM was sent.")
                return 0

            rows = await seed(db, user.id)
            print(f"\nSeeded {len([r for r in rows.values() if isinstance(r, Task)])} task(s) "
                  f"+ {len(rows['cascade_kids']) + len(rows['risky_kids'])} subtask(s) + 1 schedule.")

            events = build_events(rows, same_task=args.same_task)

        # --- publish through the real bus ---
        bus = EventBus()
        await bus.connect()
        started = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            for event_type, payload in events:
                await bus.publish(EventEnvelope(
                    type=event_type, source="send_test_notifications",
                    user_id=user.id, payload=payload,
                ))
                print(f"  published {event_type}")
        finally:
            await bus.disconnect()

        print(f"\nWaiting {wait_seconds}s for the backend consumer + DeliveryWorker...")
        await asyncio.sleep(wait_seconds)

        async with session_maker() as db:
            await report(db, user.id, started)
            if not args.keep:
                await cleanup(db, user.id, started)
            else:
                print(f"\n--keep: seeded rows left in place (titles start with {PREFIX!r}).")
                print("        Note: day.plan/day.review are per-user, so their attention_log rows")
                print("        will dedup the next run for ATTENTION_DEDUP_WINDOW_HOURS "
                      f"({settings.ATTENTION_DEDUP_WINDOW_HOURS}h).")
        return 0
    finally:
        await engine.dispose()


class _Stub:
    """Stand-in for a seeded row, so --dry-run can walk `build_events`
    without writing anything."""
    id = uuid4()
    title = "(dry-run)"
    due_date = datetime.now()
    created_at = datetime.now()
    priority = TaskPriority.HIGH
    start_time = datetime.now(timezone.utc)
    location = "-"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
