"""Service for summarizing long conversations to maintain context efficiency."""

import json
from uuid import UUID
from datetime import datetime

import google.generativeai as genai
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AgentConversation, AgentMessage
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConversationSummarizer:
    """Summarizes conversations when they exceed a threshold length."""
    
    # Trigger summarization when conversation exceeds this many messages
    MESSAGE_THRESHOLD = 20
    
    # Keep this many recent messages in context after summarization
    KEEP_RECENT_MESSAGES = 10
    
    def __init__(self, db: AsyncSession):
        """Initialize summarizer with database session."""
        self.db = db
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=self._get_summarizer_prompt(),
        )

    @staticmethod
    def _get_summarizer_prompt() -> str:
        """Return system prompt for conversation summarization."""
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
        """
        Check if conversation should be summarized.
        
        Args:
            conversation_id: ID of conversation to check
            
        Returns:
            True if message count exceeds threshold and no recent summary exists
        """
        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()
        
        if not conv:
            return False
        
        # Only summarize if we haven't already done so recently
        # and we exceed threshold
        return conv.message_count > self.MESSAGE_THRESHOLD and not conv.summary

    async def summarize_conversation(self, conversation_id: UUID) -> dict:
        """
        Summarize a conversation and store the summary.
        
        Args:
            conversation_id: ID of conversation to summarize
            
        Returns:
            Dictionary with summarization results {success, summary_length, messages_summarized}
        """
        logger.info(f"Starting summarization for conversation {conversation_id}")
        
        # Get conversation
        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()
        
        if not conv:
            logger.warning(f"Conversation {conversation_id} not found")
            return {"success": False, "error": "Conversation not found"}
        
        # Get all messages except the most recent N
        msg_stmt = select(AgentMessage).where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role != "tool",  # Don't include intermediate tool results in summary
        ).order_by(AgentMessage.created_at)
        
        result = await self.db.execute(msg_stmt)
        all_messages = result.scalars().all()
        
        # Messages to summarize (everything except recent ones)
        messages_to_summarize = all_messages[:-self.KEEP_RECENT_MESSAGES]
        
        if len(messages_to_summarize) < 5:
            logger.debug(f"Too few messages to summarize ({len(messages_to_summarize)})")
            return {"success": False, "reason": "Not enough messages"}
        
        # Build conversation text for summarization
        conversation_text = self._build_conversation_text(messages_to_summarize)
        
        try:
            # Call Gemini to summarize
            logger.debug(f"Calling Gemini to summarize {len(messages_to_summarize)} messages")
            response = await self.model.generate_content_async(conversation_text)
            
            if not response or not response.text:
                logger.error("Gemini returned empty response for summarization")
                return {"success": False, "error": "Empty summarization response"}
            
            summary_text = response.text.strip()
            summary_length = len(summary_text)
            
            logger.info(
                f"✅ Summarization complete: {len(messages_to_summarize)} messages → "
                f"{summary_length} chars | conversation={conversation_id}"
            )
            
            # Update conversation with summary
            stmt = update(AgentConversation).where(
                AgentConversation.id == conversation_id
            ).values(
                summary=summary_text,
                updated_at=datetime.utcnow(),
            )
            await self.db.execute(stmt)
            await self.db.commit()
            
            return {
                "success": True,
                "summary_length": summary_length,
                "messages_summarized": len(messages_to_summarize),
            }
            
        except Exception as exc:
            logger.error(f"Error summarizing conversation: {exc}", exc_info=True)
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _build_conversation_text(messages: list) -> str:
        """
        Build readable conversation text from messages.
        
        Args:
            messages: List of AgentMessage objects
            
        Returns:
            Formatted conversation text
        """
        parts = ["Conversation history to summarize:\n"]
        
        for msg in messages:
            if msg.role == "user":
                parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                parts.append(f"Assistant: {msg.content}")
            elif msg.role == "tool":
                tool_summary = f"[{msg.tool_name} → {msg.tool_output.get('count', '?')} results]"
                parts.append(f"Tool result: {tool_summary}")
            
            parts.append("")  # Blank line between messages
        
        return "\n".join(parts)

    async def get_conversation_context(
        self,
        conversation_id: UUID,
        include_summary: bool = True,
    ) -> str:
        """
        Get formatted context for a conversation including summary if available.
        
        This should be included in the LLM prompt to give the agent memory.
        
        Args:
            conversation_id: ID of conversation
            include_summary: Whether to include the summary in output
            
        Returns:
            Formatted context string, or empty string if no context available
        """
        # Get conversation
        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()
        
        if not conv:
            return ""
        
        context_parts = []
        
        # Include summary if available and requested
        if include_summary and conv.summary:
            context_parts.append("=== CONVERSATION SUMMARY ===")
            context_parts.append(conv.summary)
            context_parts.append("")
        
        return "\n".join(context_parts)


def get_conversation_summarizer(db: AsyncSession) -> ConversationSummarizer:
    """Factory function to get summarizer instance."""
    return ConversationSummarizer(db)
