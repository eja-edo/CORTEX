"""Service for summarizing conversations using Layer 2 rolling summaries."""

from uuid import UUID
from datetime import datetime

from google.genai import types
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConversation, AgentMessage
from app.services.agent.model_client import ModelClient
from app.memory.layers.summaries import ConversationSummarizer as Layer2Summarizer
from app.utils.logger import get_logger

logger = get_logger(__name__)

_model_client = ModelClient()


class ConversationSummarizer:
    """Summarizes conversations with rolling versioned summaries (Layer 2)."""

    MESSAGE_THRESHOLD = 20
    KEEP_RECENT_MESSAGES = 10

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._layer2 = Layer2Summarizer()

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

    async def should_summarize(self, conversation_id: UUID) -> bool:
        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()
        if not conv:
            return False

        token_total = conv.total_token_count or 0
        return await self._layer2.should_summarize(str(conversation_id), token_total, self.db)

    async def summarize_conversation(self, conversation_id: UUID) -> dict:
        logger.info(f"Starting summarization for conversation {conversation_id}")

        conv_result = await self.db.execute(
            select(AgentConversation).where(AgentConversation.id == conversation_id)
        )
        conv = conv_result.scalar_one_or_none()

        if not conv:
            return {"success": False, "error": "Conversation not found"}

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

        messages_to_summarize = all_messages[: -self.KEEP_RECENT_MESSAGES]

        if len(messages_to_summarize) < 5:
            return {"success": False, "reason": "Not enough messages"}

        conversation_text = self._build_conversation_text(messages_to_summarize)
        first_msg_id = str(messages_to_summarize[0].id)
        last_msg_id = str(messages_to_summarize[-1].id)

        # Get latest version if exists
        version_result = await self.db.execute(
            text("""
                SELECT MAX(summary_version) FROM conversation_summaries
                WHERE conversation_id = :cid
            """),
            {"cid": str(conversation_id)},
        )
        max_version = version_result.scalar() or 0
        new_version = max_version + 1

        config = types.GenerateContentConfig(
            system_instruction=self._get_summarizer_prompt(),
        )

        try:
            model_used, response = await _model_client.generate(
                contents=conversation_text,
                config=config,
            )

            if not response or not response.text:
                return {"success": False, "error": "Empty summarization response"}

            summary_text = response.text.strip()
            summary_length = len(summary_text)

            await self._layer2.store_summary(
                conversation_id=str(conversation_id),
                user_id=str(conv.user_id),
                previous_summary_id=None,
                summary_text=summary_text,
                version=new_version,
                message_start_id=first_msg_id,
                message_end_id=last_msg_id,
                message_count=len(messages_to_summarize),
                model_used=model_used,
                tokens_used=summary_length // 4,
                db=self.db,
            )

            await self.db.commit()

            logger.info(
                f"✅ Summarization complete via model={model_used}: "
                f"{len(messages_to_summarize)} messages → {summary_length} chars | "
                f"conversation={conversation_id}"
            )

            return {
                "success": True,
                "model_used": model_used,
                "summary_length": summary_length,
                "messages_summarized": len(messages_to_summarize),
            }

        except Exception as exc:
            logger.error(f"Error summarizing conversation {conversation_id}: {exc}", exc_info=True)
            return {"success": False, "error": str(exc)}

    async def get_conversation_context(
        self,
        conversation_id: UUID,
        include_summary: bool = True,
    ) -> str:
        summaries = await self._layer2.get_summary_chain(str(conversation_id), self.db)

        if not summaries:
            return ""

        parts = []
        parts.append("=== CONVERSATION SUMMARY ===")
        parts.append(summaries[-1])
        parts.append("")
        return "\n".join(parts)

    @staticmethod
    def _build_conversation_text(messages: list) -> str:
        parts = ["Conversation history to summarize:\n"]

        for msg in messages:
            if msg.role == "user" and msg.content:
                parts.append(f"User: {msg.content}")
            elif msg.role == "assistant" and msg.content:
                parts.append(f"Assistant: {msg.content}")
            elif msg.role == "tool":
                count = (msg.tool_output or {}).get("count", "?")
                parts.append(f"Tool result: [{msg.tool_name} → {count} results]")
            parts.append("")

        return "\n".join(parts)


def get_conversation_summarizer(db: AsyncSession) -> ConversationSummarizer:
    return ConversationSummarizer(db)
