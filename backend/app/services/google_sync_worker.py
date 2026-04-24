"""Background worker for async Google Calendar synchronization."""

import asyncio
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ScheduleSyncQueue, Schedule, SyncQueueStatus, SyncOperation
from app.services.google_calendar_sync import GoogleCalendarSyncService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GoogleSyncWorker:
    """Background worker that processes the schedule sync queue."""

    POLL_INTERVAL = 5  # seconds
    MAX_RETRIES = 3
    BATCH_SIZE = 20

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the sync worker."""
        self._running = True
        logger.info(
            "GoogleSyncWorker started with poll_interval=%ds, batch_size=%d",
            self.POLL_INTERVAL,
            self.BATCH_SIZE,
        )

        while self._running:
            try:
                await self._process_sync_queue()
            except Exception as e:
                logger.exception("Error in sync worker loop: %s", e)

            await asyncio.sleep(self.POLL_INTERVAL)

    async def stop(self):
        """Stop the sync worker."""
        self._running = False
        logger.info("GoogleSyncWorker stopping...")
        if self._task:
            self._task.cancel()

    async def _process_sync_queue(self):
        """Process pending sync queue entries."""
        db: Session = next(get_db())
        try:
            # Claim batch with optimistic lock (skip_locked prevents contention)
            batch = db.query(ScheduleSyncQueue).filter(
                ScheduleSyncQueue.status == SyncQueueStatus.PENDING,
            ).order_by(
                ScheduleSyncQueue.priority.desc(),
                ScheduleSyncQueue.created_at.asc(),
            ).limit(self.BATCH_SIZE).with_for_update(skip_locked=True).all()

            if not batch:
                return

            logger.info("Processing %d sync queue entries", len(batch))

            # Mark as processing
            for entry in batch:
                entry.status = SyncQueueStatus.PROCESSING
            db.commit()

            for entry in batch:
                try:
                    schedule = db.query(Schedule).filter(
                        Schedule.id == entry.schedule_id
                    ).first()

                    if schedule is None:
                        logger.warning(
                            "Schedule %s not found for sync queue entry %s",
                            entry.schedule_id,
                            entry.id,
                        )
                        entry.status = SyncQueueStatus.DONE
                        db.commit()
                        continue

                    sync_service = GoogleCalendarSyncService(db)

                    if entry.operation == SyncOperation.UPSERT:
                        sync_service.sync_upsert_schedule(schedule)
                    elif entry.operation == SyncOperation.DELETE:
                        sync_service.sync_delete_schedule(schedule)

                    entry.status = SyncQueueStatus.DONE
                    entry.processed_at = datetime.utcnow()
                    db.commit()
                    logger.info("Sync queue entry %s completed", entry.id)

                except Exception as e:
                    logger.exception("Failed to process sync queue entry %s", entry.id)
                    entry.retry_count += 1
                    entry.last_error = str(e)[:500]

                    if entry.retry_count >= self.MAX_RETRIES:
                        entry.status = SyncQueueStatus.FAILED
                        logger.error(
                            "Sync queue entry %s failed after %d retries",
                            entry.id,
                            entry.retry_count,
                        )
                    else:
                        entry.status = SyncQueueStatus.PENDING
                        logger.info(
                            "Sync queue entry %s will retry (attempt %d/%d)",
                            entry.id,
                            entry.retry_count,
                            self.MAX_RETRIES,
                        )

                    db.commit()

        except Exception as e:
            logger.exception("Error processing sync queue")
            db.rollback()
        finally:
            db.close()
