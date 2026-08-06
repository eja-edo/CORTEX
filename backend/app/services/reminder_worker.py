"""Background worker for processing schedule reminders."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import make_async_sessionmaker
from app.events.event_bus import get_event_bus
from app.events.payloads import ReminderDuePayload
from app.events.schemas import EventEnvelope
from app.models import ScheduleReminder, Schedule, ReminderStatus, Notification
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ReminderWorker:
    """Background worker that polls for due reminders and sends notifications."""

    POLL_INTERVAL_SECONDS = 30
    MAX_RETRIES = 3

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._db_engine = None
        self._session_maker = None
        self._event_bus = None  # Lazy init

    async def _get_event_bus(self):
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus

    async def start(self):
        """Start the reminder worker."""
        # Per-worker async DB engine: bound to this thread's event loop.
        # Reusing the module-level AsyncSessionLocal would give us
        # connections owned by the FastAPI request loop and raise
        # "Future attached to a different loop" here.
        self._db_engine, self._session_maker = make_async_sessionmaker()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("ReminderWorker started with poll interval=%ds", self.POLL_INTERVAL_SECONDS)
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("ReminderWorker: task cancelled during shutdown")
            raise

    async def stop(self):
        """Stop the reminder worker."""
        self._running = False
        logger.info("ReminderWorker stopping...")
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Dispose per-worker DB engine so asyncpg connections held by this
        # loop are released cleanly.
        if self._db_engine is not None:
            try:
                await self._db_engine.dispose()
            except Exception as exc:
                logger.warning("ReminderWorker: DB engine dispose failed: %s", exc)
            self._db_engine = None
            self._session_maker = None

    async def _run_loop(self):
        """Main loop with proper cancellation handling."""
        try:
            while self._running:
                try:
                    await self._process_due_reminders()
                except Exception as e:
                    logger.exception("Error in reminder worker loop: %s", e)

                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("ReminderWorker: run loop cancelled, exiting cleanly")
            raise

    async def _process_due_reminders(self):
        """Fetch and process reminders that are due within the next poll window."""
        async with self._session_maker() as db:
            try:
                # timezone-aware: scheduled_at is TIMESTAMPTZ. A naive
                # datetime.utcnow() here gets encoded by asyncpg using the
                # OS-local timezone when compared to a tz-aware column — on a
                # non-UTC host this silently shifts the "due" window by the
                # local UTC offset, so reminders miss their window entirely.
                now = datetime.now(timezone.utc)
                window_end = now + timedelta(seconds=self.POLL_INTERVAL_SECONDS)

                # Fetch reminders due in the next window
                stmt = (
                    select(ScheduleReminder)
                    .where(
                        ScheduleReminder.status == ReminderStatus.PENDING,
                        ScheduleReminder.scheduled_at <= window_end,
                    )
                    .limit(100)
                )
                result = await db.execute(stmt)
                due = result.scalars().all()

                if not due:
                    return

                logger.info("Processing %d due reminders", len(due))

                for reminder in due:
                    # Optimistic lock: only process if still pending
                    upd_stmt = (
                        update(ScheduleReminder)
                        .where(
                            ScheduleReminder.id == reminder.id,
                            ScheduleReminder.status == ReminderStatus.PENDING,
                        )
                        .values(status=ReminderStatus.PROCESSING)
                        .execution_options(synchronize_session=False)
                    )
                    update_result = await db.execute(upd_stmt)
                    if update_result.rowcount == 0:
                        continue  # Another worker grabbed it

                    try:
                        schedule = await self._send_notification(reminder, db)

                        sent_stmt = (
                            update(ScheduleReminder)
                            .where(ScheduleReminder.id == reminder.id)
                            .values(
                                status=ReminderStatus.SENT,
                                sent_at=datetime.now(timezone.utc),
                            )
                            .execution_options(synchronize_session=False)
                        )
                        await db.execute(sent_stmt)
                        await db.commit()
                        logger.info("Reminder %s sent successfully", reminder.id)

                        if schedule is not None:
                            await self._publish_reminder_due(reminder, schedule)

                    except Exception as e:
                        logger.exception("Failed to send reminder %s", reminder.id)
                        await db.rollback()

                        retry_count = reminder.retry_count + 1
                        new_status = (
                            ReminderStatus.FAILED
                            if retry_count >= self.MAX_RETRIES
                            else ReminderStatus.PENDING
                        )

                        # Exponential backoff for retries
                        new_scheduled_at = reminder.scheduled_at
                        if new_status == ReminderStatus.PENDING:
                            new_scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=2 ** retry_count)

                        fail_stmt = (
                            update(ScheduleReminder)
                            .where(ScheduleReminder.id == reminder.id)
                            .values(
                                status=new_status,
                                retry_count=retry_count,
                                failed_reason=str(e)[:500],
                                scheduled_at=new_scheduled_at,
                            )
                            .execution_options(synchronize_session=False)
                        )
                        await db.execute(fail_stmt)
                        await db.commit()

            except Exception:
                logger.exception("Error processing due reminders")
                await db.rollback()

    async def _publish_reminder_due(self, reminder: ScheduleReminder, schedule: Schedule) -> None:
        try:
            event_bus = await self._get_event_bus()
            await event_bus.publish(EventEnvelope(
                type="schedule.reminder.due",
                source="ReminderWorker",
                user_id=schedule.user_id,
                payload=ReminderDuePayload(
                    reminder_id=reminder.id,
                    schedule_id=reminder.schedule_id,
                    schedule_title=schedule.title,
                    scheduled_at=reminder.scheduled_at,
                    reminder_offset_minutes=reminder.minutes_before,
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish schedule.reminder.due event: {exc}")

    async def _send_notification(self, reminder: ScheduleReminder, db: AsyncSession) -> Optional[Schedule]:
        """Send notification for a reminder. Returns the schedule (for event
        emission by the caller), or None if the schedule no longer exists."""
        schedule = (
            await db.execute(select(Schedule).where(Schedule.id == reminder.schedule_id))
        ).scalar_one_or_none()

        if not schedule:
            logger.warning("Schedule %s not found for reminder %s", reminder.schedule_id, reminder.id)
            return None

        if reminder.method == "push":
            # Create notification record
            body_text = f"Starts at {schedule.start_time.strftime('%H:%M')}"
            notification = Notification(
                user_id=reminder.user_id,
                type="reminder",
                title=f"Reminder: {schedule.title}",
                body=body_text,
                content=[{"type": "text", "text": body_text}],
                actions=[{"label": "View", "action": "navigate", "url": "/schedule"}],
                payload={
                    "schedule_id": str(schedule.id),
                    "start_time": schedule.start_time.isoformat(),
                },
            )
            db.add(notification)
            await db.flush()

            # TODO: Publish via SSE/FCM if available
            # publish_sync_event(user_id=str(reminder.user_id), ...)

            logger.info(
                "Push notification created for user %s, schedule %s",
                reminder.user_id,
                schedule.id,
            )

        elif reminder.method == "email":
            # TODO: Integrate email service
            logger.info("Email reminder not yet implemented for reminder %s", reminder.id)

        return schedule
