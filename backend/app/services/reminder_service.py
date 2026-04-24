"""Reminder service for managing schedule reminders."""

from datetime import datetime, timedelta
from typing import List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Schedule, ScheduleReminder, ReminderStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ReminderService:
    """Service for creating and managing schedule reminders."""

    def create_reminders_for_schedule(
        self,
        schedule: Schedule,
        reminder_configs: List[dict],
        db: Session,
    ) -> List[ScheduleReminder]:
        """
        Create reminders for a schedule based on configurations.

        reminder_configs = [
            {"minutes_before": 10, "method": "push"},
            {"minutes_before": 60, "method": "push"},
            {"minutes_before": 1440, "method": "email"},
        ]
        """
        # Cancel old pending reminders if updating
        db.query(ScheduleReminder).filter(
            ScheduleReminder.schedule_id == schedule.id,
            ScheduleReminder.status == ReminderStatus.PENDING,
        ).update({"status": ReminderStatus.CANCELLED})

        reminders = []
        for cfg in reminder_configs:
            scheduled_at = schedule.start_time - timedelta(minutes=cfg["minutes_before"])

            # Skip if already past
            # Make both timezone-aware or naive for comparison
            now = datetime.utcnow()
            if scheduled_at.tzinfo is None:
                compare_scheduled = scheduled_at
            else:
                compare_scheduled = scheduled_at.replace(tzinfo=None)

            if compare_scheduled <= now:
                logger.info(
                    "Skipping reminder for schedule %s: scheduled_at %s is in the past",
                    schedule.id,
                    scheduled_at,
                )
                continue

            reminder = ScheduleReminder(
                schedule_id=schedule.id,
                user_id=schedule.user_id,
                minutes_before=cfg["minutes_before"],
                method=cfg.get("method", "push"),
                scheduled_at=scheduled_at,
                status=ReminderStatus.PENDING,
            )
            db.add(reminder)
            reminders.append(reminder)

        db.flush()
        logger.info(
            "Created %d reminders for schedule %s",
            len(reminders),
            schedule.id,
        )
        return reminders

    def cancel_reminders_for_schedule(
        self,
        schedule_id: UUID,
        db: Session,
    ) -> int:
        """Cancel all pending reminders for a schedule."""
        updated = db.query(ScheduleReminder).filter(
            ScheduleReminder.schedule_id == schedule_id,
            ScheduleReminder.status == ReminderStatus.PENDING,
        ).update({"status": ReminderStatus.CANCELLED})

        db.flush()
        logger.info("Cancelled %d reminders for schedule %s", updated, schedule_id)
        return updated

    def get_reminders_for_schedule(
        self,
        schedule_id: UUID,
        db: Session,
    ) -> List[ScheduleReminder]:
        """Get all reminders for a schedule."""
        return db.query(ScheduleReminder).filter(
            ScheduleReminder.schedule_id == schedule_id,
        ).order_by(ScheduleReminder.minutes_before.asc()).all()
