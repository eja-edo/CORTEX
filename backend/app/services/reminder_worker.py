"""Background worker for processing schedule reminders."""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.database import get_db
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
        logger.info("ReminderWorker started with poll interval=%ds", self.POLL_INTERVAL_SECONDS)

        while self._running:
            try:
                await self._process_due_reminders()
            except Exception as e:
                logger.exception("Error in reminder worker loop: %s", e)

            await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

    async def stop(self):
        """Stop the reminder worker."""
        self._running = False
        logger.info("ReminderWorker stopping...")
        if self._task:
            self._task.cancel()

    async def _process_due_reminders(self):
        """Fetch and process reminders that are due within the next poll window."""
        db: Session = next(get_db())
        try:
            now = datetime.utcnow()
            window_end = now + timedelta(seconds=self.POLL_INTERVAL_SECONDS)

            # Fetch reminders due in the next window
            due = db.query(ScheduleReminder).filter(
                ScheduleReminder.status == ReminderStatus.PENDING,
                ScheduleReminder.scheduled_at <= window_end,
            ).limit(100).all()

            if not due:
                return

            logger.info("Processing %d due reminders", len(due))

            for reminder in due:
                # Optimistic lock: only process if still pending
                updated = db.query(ScheduleReminder).filter(
                    ScheduleReminder.id == reminder.id,
                    ScheduleReminder.status == ReminderStatus.PENDING,
                ).update({"status": ReminderStatus.PROCESSING})

                if updated == 0:
                    continue  # Another worker grabbed it

                try:
                    await self._send_notification(reminder, db)

                    db.query(ScheduleReminder).filter(
                        ScheduleReminder.id == reminder.id
                    ).update({
                        "status": ReminderStatus.SENT,
                        "sent_at": datetime.utcnow(),
                    })
                    db.commit()
                    logger.info("Reminder %s sent successfully", reminder.id)

                except Exception as e:
                    logger.exception("Failed to send reminder %s", reminder.id)
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

                    db.query(ScheduleReminder).filter(
                        ScheduleReminder.id == reminder.id
                    ).update({
                        "status": new_status,
                        "retry_count": retry_count,
                        "failed_reason": str(e)[:500],
                        "scheduled_at": new_scheduled_at,
                    })
                    db.commit()

        except Exception as e:
            logger.exception("Error processing due reminders")
            db.rollback()
        finally:
            db.close()

    async def _send_notification(self, reminder: ScheduleReminder, db: Session):
        """Send notification for a reminder."""
        schedule = db.query(Schedule).filter(
            Schedule.id == reminder.schedule_id
        ).first()

        if not schedule:
            logger.warning("Schedule %s not found for reminder %s", reminder.schedule_id, reminder.id)
            return

        if reminder.method == "push":
            # Create notification record
            notification = Notification(
                user_id=reminder.user_id,
                type="reminder",
                title=f"Reminder: {schedule.title}",
                body=f"Starts at {schedule.start_time.strftime('%H:%M')}",
                payload={
                    "schedule_id": str(schedule.id),
                    "start_time": schedule.start_time.isoformat(),
                },
            )
            db.add(notification)

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
