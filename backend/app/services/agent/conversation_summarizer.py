"""Service for summarizing long conversations to maintain context efficiency."""

from uuid import UUID
from datetime import datetime

from google.genai import types
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConversation, AgentMessage
from app.services.agent.model_client import ModelClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Module-level ModelClient shared across all summarizer instances.
# Uses the same AVAILABLE_MODELS + round-robin rotation as the agent service.
_model_client = ModelClient()


class ConversationSummarizer:
    """Summarizes conversations when they exceed a threshold length."""

    # Trigger summarization when conversation exceeds this many messages
    MESSAGE_THRESHOLD = 20

    # Keep this many recent messages in context after summarization.
    # Must be kept in sync with MAX_CONVERSATION_HISTORY in agent_service so
    # the sliding window covers exactly what the summary does not.
    KEEP_RECENT_MESSAGES = 10

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    @staticmethod
    def _get_summarizer_prompt() -> str:
        return """You are an expert at creating concise, accurate summaries of conversations.

Your task is to summarize a series of agent messages from a conversation thread.

IMPORTANT RULES:
1. Be concise but comprehensive - capture the key points and decisions
2. Preserve important context like decisions made, data retrieved, and user preferences
3. Note any tool calls and their results that are relevant to understanding the conversation flow
4. Format as a structured summary with clear sections if needed
5. Focus on facts, not repetition
6. Keep it under 300 words

Output format:
Provide a natural language summary that captures the essence of the conversation so far."""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def should_summarize(self, conversation_id: UUID) -> bool:
        """
        Return True if the conversation has exceeded MESSAGE_THRESHOLD and
        does not yet have a summary stored.
        """
        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        return conv.message_count > self.MESSAGE_THRESHOLD and not conv.summary

    async def summarize_conversation(self, conversation_id: UUID) -> dict:
        """
        Generate and persist a summary for the given conversation.

        Summarizes all messages *except* the most recent KEEP_RECENT_MESSAGES
        so the sliding context window in agent_service always has fresh turns
        and the summary covers everything older.

        Returns
        -------
        dict with keys: success, summary_length, messages_summarized
                     or success=False, error/reason.
        """
        logger.info(f"Starting summarization for conversation {conversation_id}")

        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()

        if not conv:
            logger.warning(f"Conversation {conversation_id} not found")
            return {"success": False, "error": "Conversation not found"}

        # Fetch user/assistant messages only — tool rows are too noisy for a
        # human-readable summary and inflate token count unnecessarily.
        msg_stmt = (
            select(AgentMessage)
            .where(
                AgentMessage.conversation_id == conversation_id,
                AgentMessage.role != "tool",
            )
            .order_by(AgentMessage.created_at.asc())
        )
        result = await self.db.execute(msg_stmt)
        all_messages = result.scalars().all()

        # Only summarize messages older than the recent window so the two
        # layers (summary + recent window) cover the full history without
        # overlap or gap.
        messages_to_summarize = all_messages[: -self.KEEP_RECENT_MESSAGES]

        if len(messages_to_summarize) < 5:
            logger.debug(
                f"Too few messages to summarize ({len(messages_to_summarize)})"
            )
            return {"success": False, "reason": "Not enough messages"}

        conversation_text = self._build_conversation_text(messages_to_summarize)

        config = types.GenerateContentConfig(
            system_instruction=self._get_summarizer_prompt(),
        )

        try:
            model_used, response = await _model_client.generate(
                contents=conversation_text,
                config=config,
            )

            if not response or not response.text:
                logger.error(
                    f"Empty summarization response from model={model_used}"
                )
                return {"success": False, "error": "Empty summarization response"}

            summary_text = response.text.strip()
            summary_length = len(summary_text)

            logger.info(
                f"✅ Summarization complete via model={model_used}: "
                f"{len(messages_to_summarize)} messages → {summary_length} chars | "
                f"conversation={conversation_id}"
            )

            await self.db.execute(
                update(AgentConversation)
                .where(AgentConversation.id == conversation_id)
                .values(summary=summary_text, updated_at=datetime.utcnow())
            )
            await self.db.commit()

            return {
                "success": True,
                "model_used": model_used,
                "summary_length": summary_length,
                "messages_summarized": len(messages_to_summarize),
            }

        except Exception as exc:
            logger.error(
                f"Error summarizing conversation {conversation_id}: {exc}",
                exc_info=True,
            )
            return {"success": False, "error": str(exc)}

    async def get_conversation_context(
        self,
        conversation_id: UUID,
        include_summary: bool = True,
    ) -> str:
        """
        Return a formatted context string to prepend to the system prompt.
        Contains the stored summary when available.
        """
        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()

        if not conv:
            return ""

        parts: list[str] = []
        if include_summary and conv.summary:
            parts.append("=== CONVERSATION SUMMARY ===")
            parts.append(conv.summary)
            parts.append("")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_conversation_text(messages: list) -> str:
        """Convert a list of AgentMessage objects to a plain-text transcript."""
        parts = ["Conversation history to summarize:\n"]

        for msg in messages:
            if msg.role == "user" and msg.content:
                parts.append(f"User: {msg.content}")
            elif msg.role == "assistant" and msg.content:
                parts.append(f"Assistant: {msg.content}")
            elif msg.role == "tool":
                count = (msg.tool_output or {}).get("count", "?")
                parts.append(f"Tool result: [{msg.tool_name} → {count} results]")
            parts.append("")  # blank line between turns

        return "\n".join(parts)


def get_conversation_summarizer(db: AsyncSession) -> ConversationSummarizer:
    """Factory function — returns a ConversationSummarizer bound to *db*."""
    return ConversationSummarizer(db)