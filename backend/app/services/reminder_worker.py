"""Background worker for processing schedule reminders."""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import AsyncSessionLocal
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

    async def start(self):
        """Start the reminder worker."""
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
        async with AsyncSessionLocal() as db:
            try:
                now = datetime.utcnow()
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
                        await self._send_notification(reminder, db)

                        sent_stmt = (
                            update(ScheduleReminder)
                            .where(ScheduleReminder.id == reminder.id)
                            .values(
                                status=ReminderStatus.SENT,
                                sent_at=datetime.utcnow(),
                            )
                            .execution_options(synchronize_session=False)
                        )
                        await db.execute(sent_stmt)
                        await db.commit()
                        logger.info("Reminder %s sent successfully", reminder.id)

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
                            new_scheduled_at = datetime.utcnow() + timedelta(minutes=2 ** retry_count)

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

    async def _send_notification(self, reminder: ScheduleReminder, db: AsyncSession):
        """Send notification for a reminder."""
        schedule = (
            await db.execute(select(Schedule).where(Schedule.id == reminder.schedule_id))
        ).scalar_one_or_none()

        if not schedule:
            logger.warning("Schedule %s not found for reminder %s", reminder.schedule_id, reminder.id)
            return

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
            pass
