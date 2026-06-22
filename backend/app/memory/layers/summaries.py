import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from sqlalchemy import text

logger = logging.getLogger(__name__)


class ConversationSummarizer:
    """
    Layer 2: Conversation Summaries
    Rolling summaries — chain versions, không overwrite.
    """

    SUMMARY_TRIGGER_TOKEN_COUNT = 8_000

    async def should_summarize(self, conversation_id: str, token_total: int, db) -> bool:
        if token_total < self.SUMMARY_TRIGGER_TOKEN_COUNT:
            return False

        result = await db.execute(text("""
            SELECT summary_version, message_end_id
            FROM conversation_summaries
            WHERE conversation_id = :conv_id
            ORDER BY summary_version DESC
            LIMIT 1
        """), {"conv_id": conversation_id})
        latest = result.fetchone()

        if latest is None:
            return True

        new_result = await db.execute(text("""
            SELECT COUNT(*) FROM agent_messages
            WHERE conversation_id = :conv_id
              AND id > :last_end_id
        """), {"conv_id": conversation_id, "last_end_id": latest[1]})

        return new_result.fetchone()[0] > 5

    async def store_summary(self, conversation_id: str, user_id: str, previous_summary_id: Optional[str],
                             summary_text: str, version: int, message_start_id: str, message_end_id: str,
                             message_count: int, model_used: str, tokens_used: int, db):
        await db.execute(text("""
            INSERT INTO conversation_summaries
                (conversation_id, user_id, summary_text, summary_version,
                 message_start_id, message_end_id, message_count,
                 previous_summary_id, model_used, tokens_used)
            VALUES
                (:conv_id, :user_id, :summary, :version,
                 :msg_start, :msg_end, :msg_count,
                 :prev_summary, :model, :tokens)
        """), {
            "conv_id": conversation_id,
            "user_id": user_id,
            "summary": summary_text,
            "version": version,
            "msg_start": message_start_id,
            "msg_end": message_end_id,
            "msg_count": message_count,
            "prev_summary": previous_summary_id,
            "model": model_used,
            "tokens": tokens_used,
        })
        logger.info("Stored summary v%s for conversation %s", version, conversation_id)

    async def get_summary_chain(self, conversation_id: str, db) -> List[str]:
        result = await db.execute(text("""
            SELECT summary_text
            FROM conversation_summaries
            WHERE conversation_id = :conv_id
            ORDER BY summary_version ASC
        """), {"conv_id": conversation_id})

        return [r[0] for r in result.fetchall()]
