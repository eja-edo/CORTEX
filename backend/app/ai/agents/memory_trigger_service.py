"""MemoryTriggerService — triggers memory extraction with advisory lock to prevent races."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.conversation_summarizer import ConversationSummarizer
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryTriggerService:
    """Triggers memory extraction with Postgres advisory lock to prevent concurrent extractions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def maybe_trigger(
        self,
        summarizer: ConversationSummarizer | None,
        conv,
    ) -> None:
        """Trigger memory extraction when conversation crosses message-count threshold.

        Wrapped in a Postgres transaction-scoped advisory lock keyed on
        conv.id so concurrent requests on the same conversation cannot both
        run `summarize_conversation` simultaneously. The first request that
        acquires the lock does the extraction; others return immediately.

        Args:
            summarizer: ConversationSummarizer instance or None (no-op).
            conv: AgentConversation — the latest message_count should be
                  current (already incremented by caller).
        """
        if summarizer is None:
            return
        threshold = summarizer.MESSAGE_THRESHOLD
        if conv.message_count < threshold or conv.message_count % threshold >= 2:
            return

        lock_key = conv.id.hex if isinstance(conv.id, UUID) else str(conv.id).replace("-", "")
        lock_stmt = text(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"
        ).bindparams(k=lock_key)

        try:
            result = await self.db.execute(lock_stmt)
            acquired = result.scalar()
        except Exception as exc:
            logger.warning(f"Advisory lock attempt failed for conv {conv.id}: {exc}")
            return

        if not acquired:
            logger.info(
                f"Skipping memory extraction — another request holds the "
                f"advisory lock for conv {conv.id} (message_count={conv.message_count})"
            )
            return

        logger.info(
            f"Triggering memory extraction | conversation={conv.id} | "
            f"messages={conv.message_count} (lock acquired)"
        )
        try:
            summary_result = await summarizer.summarize_conversation(conv.id)
            if summary_result.get("success"):
                logger.info(f"Memory extraction complete | {summary_result}")
            else:
                logger.warning(f"Memory extraction failed | {summary_result}")
        except Exception as exc:
            logger.warning(f"Error in memory extraction: {exc}")
