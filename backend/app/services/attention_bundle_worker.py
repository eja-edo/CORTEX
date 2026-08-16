"""AttentionBundleWorker (Milestone 6.1 M3).

Same shape as StateEvaluator (app/services/state_evaluator.py) on purpose —
a background worker polling on an interval, one per-worker async engine
bound to its own thread's event loop (see that module's `start()` comment
for why a shared engine would be wrong here). Where StateEvaluator turns
"time passed" into an event, this turns "the user stopped being busy" into
a delivery: see app/services/attention_bundle.py for the actual flush logic.
"""

import asyncio
from typing import Optional

from app.database_async import make_async_sessionmaker
from app.services.attention_bundle import flush_due_bundles
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AttentionBundleWorker:
    """Background worker that periodically flushes busy-silenced attention
    candidates for users who are no longer busy."""

    POLL_INTERVAL_SECONDS = 60

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._db_engine = None
        self._session_maker = None

    async def start(self):
        self._db_engine, self._session_maker = make_async_sessionmaker()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("AttentionBundleWorker started with poll interval=%ds", self.POLL_INTERVAL_SECONDS)
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("AttentionBundleWorker: task cancelled during shutdown")
            raise
        finally:
            await self._cleanup()

    async def stop(self):
        self._running = False
        logger.info("AttentionBundleWorker stopping...")
        if self._task and not self._task.done():
            self._task.cancel()

    async def _cleanup(self):
        if self._db_engine is not None:
            try:
                await self._db_engine.dispose()
            except Exception as exc:
                logger.warning("AttentionBundleWorker: DB engine dispose failed: %s", exc)
            self._db_engine = None
            self._session_maker = None

    async def _run_loop(self):
        try:
            while self._running:
                try:
                    async with self._session_maker() as db:
                        flushed = await flush_due_bundles(db)
                        if flushed:
                            logger.info("AttentionBundleWorker flushed bundles for %d user(s)", flushed)
                except Exception as e:
                    logger.exception("Error in attention bundle worker loop: %s", e)

                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("AttentionBundleWorker: run loop cancelled, exiting cleanly")
            raise
