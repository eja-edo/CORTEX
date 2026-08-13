"""
Idle flush for task extraction. Replaces the former
`app.services.commitment_flush_worker` (Commitment folded into Task — see
"Xoá bỏ Commitment, gộp vào Task"). The sweep mechanism below is unchanged
from that module, including the cross-loop DB-session fix — see the class
docstring.

**Without this, short conversations lose their tasks permanently.**

`MemoryTriggerService.maybe_trigger()` runs after every message and returns
immediately when the counters are below threshold. There is no timer, no
sweep and no flush at end of conversation — so a conversation that stops at
message 5 never reaches 20 and is never extracted. That threshold is right
for memory, which is accumulated background knowledge where a small gap is
soft and information repeats. Tasks are the opposite: discrete, dated,
one-off. Missing one fails at exactly the moment it mattered.

And the gap lands on the most common shape of all. *"Nhắc tôi gửi proposal
cho John thứ 6"* is a two-message conversation — the single most important
sentence the feature can catch, sitting in the one conversation length the
threshold can never reach.

The fix, per the planning doc:

    conversation idle > IDLE_MINUTES, messages not yet extracted
            ↓
       any L0 signal?
            ↓ yes                     ↓ no
      extract now                 wait for the 20-message threshold
                                  (memory is not in a hurry)

Cost stays near zero because only conversations that actually look like they
contain a task trigger an early call.

The sweep takes the **same** `pg_try_advisory_xact_lock` as the inline
trigger. Without that they would race on the same conversation and both call
the LLM, double-billing and double-creating candidates.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text

from app.ai.agents.conversation_summarizer import ConversationSummarizer
from app.database_async import make_async_sessionmaker
from app.intents.task_signals import has_task_signal
from app.models import AgentConversation, AgentMessage
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How long a conversation must be quiet before it counts as over. Short
# enough that a task shows up while the user still remembers saying it;
# long enough not to fire mid-conversation while they're typing.
IDLE_MINUTES = 10

# How often the sweep runs. A task appearing a few minutes after the user
# stops typing is fine for "thứ 6" deadlines.
SWEEP_INTERVAL_SECONDS = 120

# Safety valve: never look further back than this. A conversation abandoned
# weeks ago isn't worth an LLM call on every sweep.
MAX_IDLE_HOURS = 48

# Retire unanswered candidates once a day (the 7-day rule).
EXPIRY_SWEEP_INTERVAL_SECONDS = 86_400


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TaskFlushWorker:
    """Periodic sweep for idle conversations carrying an L0 signal.

    Runs in its own OS thread with its own event loop — see
    `WorkerThread` in `app/__init__.py`, the same mechanism
    `ReminderWorker` and `GoogleSyncWorker` use. That means it **must not**
    reach for the module-level `AsyncSessionLocal`: that engine's asyncpg
    connections are bound to whichever loop first initialised it, which is
    the main FastAPI loop (`init_async_engine()` runs there explicitly, on
    purpose, before any worker thread starts — see the lifespan handler's
    comment). Using them from this worker's thread fails with "Future
    attached to a different loop", and can corrupt the pooled connection's
    prepared-statement cache badly enough that later unrelated queries on
    that same connection raise `AttributeError: 'NoneType' object has no
    attribute '_init_types'` deep inside asyncpg — a real production crash
    this class (then `CommitmentFlushWorker`) caused before this fix, found
    via the server's own logs rather than a test, because every existing
    test called `find_flushable`/`flush_conversation` with a session passed
    in directly and never exercised `sweep_once()`/`_sessions()` at all.

    `make_async_sessionmaker()` is `database_async.py`'s documented answer
    to exactly this: a fresh engine bound to whichever loop calls it, created
    inside `start()` so that loop is this worker's own.
    """

    def __init__(self, session_factory=None) -> None:
        # Test-only override, checked first — lets a test hand this worker a
        # session factory bound to *its* loop instead of either the worker's
        # own (not created until start() runs) or the FastAPI singleton.
        self._session_factory = session_factory
        self._db_engine = None
        self._session_maker = None
        self._running = False
        self._last_expiry_sweep = 0.0
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        # Per-worker async engine: bound to this thread's event loop. See
        # the class docstring for why the module-level singleton is wrong
        # here.
        self._db_engine, self._session_maker = make_async_sessionmaker()
        self._running = True
        logger.info(
            f"TaskFlushWorker started "
            f"(idle={IDLE_MINUTES}m, sweep={SWEEP_INTERVAL_SECONDS}s)"
        )
        # Run the sweep loop as a cancellable task rather than awaiting it
        # inline — otherwise stop() setting _running=False can't interrupt
        # an in-flight asyncio.sleep(SWEEP_INTERVAL_SECONDS) (up to 2
        # minutes), and the worker thread lingers past WorkerThread's
        # join(timeout=10) ("did not stop gracefully").
        self._task = asyncio.create_task(self._run_loop())
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("TaskFlushWorker: task cancelled during shutdown")
            raise
        finally:
            # Runs inside the same task run_until_complete is awaiting, so
            # cleanup is guaranteed to finish before WorkerThread closes the
            # loop — see WorkerThread._run()/stop() in app/__init__.py for
            # why doing this from stop() instead used to race the shutdown.
            await self._cleanup()

    async def _run_loop(self) -> None:
        try:
            while self._running:
                try:
                    await self.sweep_once()
                except Exception as exc:
                    logger.error(f"Task flush sweep failed: {exc}", exc_info=True)
                await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("TaskFlushWorker: run loop cancelled, exiting cleanly")
            raise

    async def stop(self) -> None:
        """Signal the worker to stop. Cleanup runs in start()'s finally
        block, not here — see the comment there."""
        self._running = False
        logger.info("TaskFlushWorker stopping...")
        if self._task and not self._task.done():
            self._task.cancel()

    async def _cleanup(self) -> None:
        # Dispose the per-worker engine so its asyncpg connections are
        # released cleanly, rather than lingering bound to a loop that's
        # about to be torn down.
        if self._db_engine is not None:
            try:
                await self._db_engine.dispose()
            except Exception as exc:
                logger.warning(f"TaskFlushWorker: DB engine dispose failed: {exc}")
            self._db_engine = None
            self._session_maker = None
        logger.info("TaskFlushWorker stopped")

    def _sessions(self):
        if self._session_factory is not None:
            return self._session_factory()
        if self._session_maker is not None:
            return self._session_maker()
        # Reachable only if sweep_once() is called before start() has run
        # (or after stop()) — a caller bug, not a loop-affinity one. Fail
        # loudly rather than silently falling back to the singleton and
        # reintroducing the exact bug this class exists to avoid.
        raise RuntimeError(
            "TaskFlushWorker has no session source — call start() first, "
            "or pass session_factory= for direct sweep_once() use outside the worker loop."
        )

    async def sweep_once(self) -> dict:
        """One pass. Returns a summary so tests and metrics can see what it did."""
        async with self._sessions() as db:
            conversations = await self.find_flushable(db)
            flushed = 0
            for conversation_id in conversations:
                if await self.flush_conversation(db, conversation_id):
                    flushed += 1

            expired = 0
            now = asyncio.get_event_loop().time()
            if now - self._last_expiry_sweep >= EXPIRY_SWEEP_INTERVAL_SECONDS:
                expired = await self._expire_candidates(db)
                self._last_expiry_sweep = now

            return {
                "candidates": len(conversations),
                "flushed": flushed,
                "expired": expired,
            }

    async def find_flushable(self, db) -> list[UUID]:
        """Idle conversations with unextracted messages that look like they
        contain a task.

        The L0 check runs in Python rather than SQL: the pattern list is the
        same one used per-message, and keeping one implementation means the
        scheduler and the scanner cannot disagree about what a signal is.
        """
        idle_before = _naive_utcnow() - timedelta(minutes=IDLE_MINUTES)
        oldest = _naive_utcnow() - timedelta(hours=MAX_IDLE_HOURS)

        stmt = (
            select(AgentConversation.id)
            .where(
                AgentConversation.updated_at <= idle_before,
                AgentConversation.updated_at >= oldest,
                # Something has arrived since the last extraction. Zero means
                # there's nothing to look at.
                AgentConversation.messages_since_last_summary > 0,
            )
            .order_by(AgentConversation.updated_at.asc())
            .limit(50)
        )
        candidate_ids = list((await db.execute(stmt)).scalars().all())

        flushable: list[UUID] = []
        for conversation_id in candidate_ids:
            if await self._has_signal(db, conversation_id):
                flushable.append(conversation_id)
        return flushable

    async def _has_signal(self, db, conversation_id: UUID) -> bool:
        """Any L0 hit among the messages not yet extracted."""
        conv = await db.get(AgentConversation, conversation_id)
        if conv is None:
            return False

        stmt = select(AgentMessage.content).where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role.in_(("user", "assistant")),
        )
        if conv.last_summary_message_id is not None:
            last = await db.get(AgentMessage, conv.last_summary_message_id)
            if last is not None:
                stmt = stmt.where(AgentMessage.created_at > last.created_at)

        contents = (await db.execute(stmt)).scalars().all()
        return any(has_task_signal(content) for content in contents)

    async def flush_conversation(self, db, conversation_id: UUID) -> bool:
        """Extract now, under the inline trigger's own advisory lock.

        `min_new_messages=1` on purpose: this path exists for the two-message
        conversation, so applying memory's five-message floor here would skip
        precisely the case it was written for.
        """
        lock_key = (
            conversation_id.hex if isinstance(conversation_id, UUID)
            else str(conversation_id).replace("-", "")
        )
        lock_stmt = text(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"
        ).bindparams(k=lock_key)

        try:
            acquired = (await db.execute(lock_stmt)).scalar()
        except Exception as exc:
            logger.warning(f"Flush advisory lock failed for conv {conversation_id}: {exc}")
            return False

        if not acquired:
            # The inline trigger is mid-extraction on this conversation. It
            # will pick these messages up; trying again would double-bill.
            logger.info(f"Skipping flush — lock held for conv {conversation_id}")
            return False

        logger.info(
            f"Idle flush: extracting tasks | conversation={conversation_id} "
            f"(idle > {IDLE_MINUTES}m, L0 signal present)"
        )
        try:
            summarizer = ConversationSummarizer(db)
            result = await summarizer.summarize_conversation(
                conversation_id,
                extract_tasks=True,
                min_new_messages=1,
            )
            if not result.get("success"):
                logger.info(f"Idle flush produced nothing | {result}")
            return bool(result.get("success"))
        except Exception as exc:
            logger.error(f"Idle flush failed for {conversation_id}: {exc}", exc_info=True)
            return False

    async def _expire_candidates(self, db) -> int:
        from app.services.task_extraction import TaskCandidateService

        try:
            return await TaskCandidateService(db).expire_stale_candidates()
        except Exception as exc:
            logger.error(f"Candidate expiry sweep failed: {exc}", exc_info=True)
            return 0
