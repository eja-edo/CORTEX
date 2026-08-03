"""MemoryTriggerService — triggers memory extraction with advisory lock to prevent races.

Hybrid trigger: fires when either the message-count threshold or the token-count
threshold is crossed since the last summary. Uses the incremental counters
(messages_since_last_summary, tokens_since_last_summary) rather than total
conversation metrics.
"""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConversation
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
        """Trigger memory extraction when message or token threshold is crossed.

        Hybrid trigger:
        - messages_since_last_summary >= MESSAGE_THRESHOLD (20), OR
        - tokens_since_last_summary >= TOKEN_THRESHOLD (20000)

        Wrapped in a Postgres transaction-scoped advisory lock keyed on
        conv.id so concurrent requests on the same conversation cannot both
        run `summarize_conversation` simultaneously. The first request that
        acquires the lock does the extraction; others return immediately.

        Args:
            summarizer: ConversationSummarizer instance or None (no-op).
            conv: AgentConversation (may be stale — fresh counters are read from DB).
        """
        if summarizer is None:
            return

        # Read fresh counters from DB (conv object may be stale)
        stmt = select(
            AgentConversation.messages_since_last_summary,
            AgentConversation.tokens_since_last_summary,
        ).where(AgentConversation.id == conv.id)
        result = await self.db.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return
        fresh_msg_count, fresh_token_count = row

        msg_threshold = summarizer.MESSAGE_THRESHOLD
        token_threshold = summarizer.TOKEN_THRESHOLD

        msg_ok = fresh_msg_count >= msg_threshold
        token_ok = fresh_token_count >= token_threshold

        if not msg_ok and not token_ok:
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
                f"advisory lock for conv {conv.id} "
                f"(msgs_since={fresh_msg_count}, "
                f"tokens_since={fresh_token_count})"
            )
            return

        logger.info(
            f"Triggering memory extraction | conversation={conv.id} | "
            f"msgs_since={fresh_msg_count} | "
            f"tokens_since={fresh_token_count} (lock acquired)"
        )
        try:
            summary_result = await summarizer.summarize_conversation(conv.id)
            if summary_result.get("success"):
                logger.info(f"Memory extraction complete | {summary_result}")
            else:
                logger.warning(f"Memory extraction failed | {summary_result}")
        except Exception as exc:
            logger.warning(f"Error in memory extraction: {exc}")
