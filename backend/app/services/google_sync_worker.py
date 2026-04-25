"""
Google Calendar Sync Worker

Consumes GoogleSyncTask messages from Redis Stream and syncs schedules to
Google Calendar via GoogleCalendarSyncService.
"""

import asyncio
from typing import Optional
from uuid import UUID

from app.database import get_db
from app.models import Schedule, SyncOperation
from app.services.google_calendar_sync import GoogleCalendarSyncService
from app.services.redis.google_sync_task import (
    GOOGLE_SYNC_CONSUMER_GROUP,
    GOOGLE_SYNC_STREAM_KEY,
    GoogleSyncTask,
)
from app.services.redis.redis_stream_service import RedisStreamService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GoogleSyncWorker:
    """
    Background worker that consumes GoogleSyncTask from Redis Stream and
    applies the sync via GoogleCalendarSyncService.

    Chạy trong WorkerThread riêng với event loop riêng (xem app/__init__.py).
    KHÔNG dùng RedisStreamService.get_instance() singleton để tránh cross-loop
    issue — tạo instance mới trực tiếp trong start() khi đã ở đúng event loop.
    """

    def __init__(self) -> None:
        self._running = False
        self._redis_service: Optional[RedisStreamService] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return

        # FIX: Dùng constructor trực tiếp thay vì get_instance() singleton.
        # get_instance() trả cached instance có thể đã bind với loop khác
        # (FastAPI loop). Tạo instance mới đảm bảo Redis client bind đúng
        # với worker thread loop hiện tại.
        self._redis_service = RedisStreamService(
            task_class=GoogleSyncTask,
            stream_key=GOOGLE_SYNC_STREAM_KEY,
            group_name=GOOGLE_SYNC_CONSUMER_GROUP,
        )

        try:
            await self._redis_service.connect()
        except ConnectionError as exc:
            logger.error("GoogleSyncWorker: Redis connection failed on start: %s", exc)
            # Tiếp tục vào consume_loop — loop sẽ retry connect khi ConnectionError

        await self._redis_service.start_background_tasks()

        self._running = True
        logger.info(
            "GoogleSyncWorker started (stream=%s, group=%s, consumer=%s)",
            GOOGLE_SYNC_STREAM_KEY,
            GOOGLE_SYNC_CONSUMER_GROUP,
            self._redis_service._consumer_id,
        )
        await self._consume_loop()

    async def stop(self) -> None:
        self._running = False
        if self._redis_service:
            await self._redis_service.stop_background_tasks()
            await self._redis_service.disconnect(release_pending=True)
            self._redis_service = None
        logger.info("GoogleSyncWorker stopped")

    # ------------------------------------------------------------------
    # Consume loop
    # ------------------------------------------------------------------

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                tasks = await self._redis_service.read_tasks(count=10, block_ms=5000)

                # Khi stream idle, thử claim orphaned tasks từ worker cũ crash
                if not tasks:
                    claimed = await self._redis_service.claim_orphaned_tasks(count=5)
                    if claimed:
                        logger.info(
                            "GoogleSyncWorker: claimed %d orphaned task(s)", len(claimed)
                        )
                        tasks = claimed

                for task in tasks:
                    try:
                        logger.info(
                            "Processing sync task: task_id=%s schedule_id=%s op=%s retry=%d",
                            task.task_id,
                            task.schedule_id,
                            task.operation,
                            task.retry_count,
                        )
                        await self._process_task(task)
                        await self._redis_service.acknowledge(task)
                        logger.info("Sync task done: task_id=%s", task.task_id)

                    except Exception as exc:
                        logger.exception(
                            "Sync task failed: task_id=%s — %s", task.task_id, exc
                        )
                        try:
                            await self._redis_service.reject(
                                task, error=str(exc)[:500], retry=True
                            )
                        except Exception as reject_err:
                            logger.error(
                                "Failed to reject task %s: %s", task.task_id, reject_err
                            )

            except ConnectionError as exc:
                logger.error("GoogleSyncWorker: Redis connection lost: %s", exc)
                await asyncio.sleep(5)
                try:
                    await self._redis_service.connect()
                    logger.info("GoogleSyncWorker: reconnected to Redis")
                except Exception as reconnect_err:
                    logger.error("GoogleSyncWorker: reconnect failed: %s", reconnect_err)

            except Exception as exc:
                logger.error("GoogleSyncWorker: loop error: %s", exc, exc_info=True)
                await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # Task processing
    # ------------------------------------------------------------------

    async def _process_task(self, task: GoogleSyncTask) -> None:
        """
        Xử lý một sync task: load Schedule từ DB rồi gọi GoogleCalendarSyncService.

        DB session mở ngắn gọn per-task để tránh giữ connection
        trong suốt thời gian Redis blocking read.
        """
        if not task.schedule_id:
            logger.warning(
                "GoogleSyncWorker: task %s has empty schedule_id, skipping", task.task_id
            )
            return

        db_gen = get_db()
        db = next(db_gen)
        try:
            schedule = (
                db.query(Schedule)
                .filter(Schedule.id == UUID(task.schedule_id))
                .first()
            )

            if schedule is None:
                # Schedule đã bị xoá trước khi worker kịp xử lý — bình thường.
                # Không raise để tránh retry vô ích.
                logger.warning(
                    "GoogleSyncWorker: schedule %s not found (deleted?), "
                    "acknowledging task %s without sync",
                    task.schedule_id,
                    task.task_id,
                )
                return

            sync_service = GoogleCalendarSyncService(db)

            if task.operation == SyncOperation.UPSERT.value:
                sync_service.sync_upsert_schedule(schedule)
            elif task.operation == SyncOperation.DELETE.value:
                sync_service.sync_delete_schedule(schedule)
            else:
                logger.warning(
                    "GoogleSyncWorker: unknown operation '%s' in task %s",
                    task.operation,
                    task.task_id,
                )

        finally:
            db.close()