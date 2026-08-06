"""
Google Calendar Sync Worker

Consumes GoogleSyncTask messages from Redis Stream and syncs schedules to
Google Calendar via GoogleCalendarSyncService.
"""

import asyncio
import time
from typing import Optional
from uuid import UUID

from sqlalchemy import select

from app.database_async import make_async_sessionmaker
from app.events.event_bus import get_event_bus
from app.events.payloads import GoogleCalendarSyncedPayload
from app.events.schemas import EventEnvelope
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
        self._consume_task: Optional[asyncio.Task] = None
        self._db_engine = None
        self._session_maker = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return

        # Per-worker async DB engine: bound to this thread's event loop.
        # Reusing the module-level AsyncSessionLocal would give us
        # connections owned by the FastAPI request loop and raise
        # "Future attached to a different loop" here.
        self._db_engine, self._session_maker = make_async_sessionmaker()

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
        # Run consume loop as a cancellable task
        self._consume_task = asyncio.create_task(self._consume_loop())
        try:
            await self._consume_task
        except asyncio.CancelledError:
            logger.info("GoogleSyncWorker: consume task cancelled during shutdown")
            raise

    async def stop(self) -> None:
        self._running = False
        # Cancel consume task first, wait for it to exit blocking call
        if self._consume_task and not self._consume_task.done():
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
        # Now safe to disconnect Redis
        if self._redis_service:
            await self._redis_service.stop_background_tasks()
            await self._redis_service.disconnect(release_pending=True)
            self._redis_service = None
        # Dispose per-worker DB engine so asyncpg connections held by this
        # loop are released cleanly.
        if self._db_engine is not None:
            try:
                await self._db_engine.dispose()
            except Exception as exc:
                logger.warning("GoogleSyncWorker: DB engine dispose failed: %s", exc)
            self._db_engine = None
            self._session_maker = None
        logger.info("GoogleSyncWorker stopped")

    # ------------------------------------------------------------------
    # Consume loop
    # ------------------------------------------------------------------

    async def _consume_loop(self) -> None:
        try:
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
        except asyncio.CancelledError:
            logger.info("GoogleSyncWorker: consume loop cancelled, exiting cleanly")
            raise

    # ------------------------------------------------------------------
    # Task processing
    # ------------------------------------------------------------------

    async def _process_task(self, task: GoogleSyncTask) -> None:
        """
        Xử lý một sync task: load Schedule từ DB rồi gọi GoogleCalendarSyncService.

        Schedule được load bằng async session (non-blocking) rồi detach khỏi
        session để GoogleCalendarSyncService (sync) có thể thao tác trên
        detached instance. Phần sync service chạy trong asyncio.to_thread để
        không block event loop trong khi chờ HTTP / DB I/O.
        """
        if not task.schedule_id:
            logger.warning(
                "GoogleSyncWorker: task %s has empty schedule_id, skipping", task.task_id
            )
            return

        # Bước 1: load schedule qua async session.
        async with self._session_maker() as async_db:
            schedule = (
                await async_db.execute(
                    select(Schedule).where(Schedule.id == UUID(task.schedule_id))
                )
            ).scalar_one_or_none()

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

        # Bước 2: chạy sync service (sync code) trong thread riêng để
        # không block event loop.
        start_time = time.time()
        try:
            if task.operation == SyncOperation.UPSERT.value:
                await asyncio.to_thread(self._sync_upsert, schedule)
            elif task.operation == SyncOperation.DELETE.value:
                await asyncio.to_thread(self._sync_delete, schedule)
            else:
                logger.warning(
                    "GoogleSyncWorker: unknown operation '%s' in task %s",
                    task.operation,
                    task.task_id,
                )
                return
        except Exception as exc:
            logger.exception(
                "GoogleSyncWorker: sync service raised for task %s", task.task_id
            )
            await self._publish_sync_event(schedule, task, time.time() - start_time, success=False, error=str(exc))
            raise

        await self._publish_sync_event(schedule, task, time.time() - start_time, success=True)

    async def _publish_sync_event(
        self,
        schedule: Schedule,
        task: "GoogleSyncTask",
        duration_seconds: float,
        *,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        """Publish google_calendar.synced. One event per processed schedule —
        this worker syncs one schedule per task, not a batched job, so
        events_added/updated/deleted here reflect that single schedule
        (never break the sync operation on publish failure)."""
        try:
            bus = await get_event_bus()
            is_upsert = task.operation == SyncOperation.UPSERT.value
            await bus.publish(EventEnvelope(
                type="google_calendar.synced",
                source="GoogleSyncWorker",
                user_id=schedule.user_id,
                payload=GoogleCalendarSyncedPayload(
                    user_id=schedule.user_id,
                    sync_direction="push",
                    events_added=0,
                    events_updated=1 if success and is_upsert else 0,
                    events_deleted=1 if success and not is_upsert else 0,
                    sync_duration_ms=int(duration_seconds * 1000),
                    errors=[error] if error else [],
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish google_calendar.synced event: {exc}")

    @staticmethod
    def _sync_upsert(schedule: Schedule) -> None:
        """Helper chạy trong thread — mở sync session cho GoogleCalendarSyncService."""
        from app.database import sync_session  # local import: tránh vòng phụ thuộc

        with sync_session() as db:
            GoogleCalendarSyncService(db).sync_upsert_schedule(schedule)

    @staticmethod
    def _sync_delete(schedule: Schedule) -> None:
        """Helper chạy trong thread — mở sync session cho GoogleCalendarSyncService."""
        from app.database import sync_session  # local import: tránh vòng phụ thuộc

        with sync_session() as db:
            GoogleCalendarSyncService(db).sync_delete_schedule(schedule)