"""Conversation store for persisting agent conversations and messages."""

from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_, delete, func
from sqlalchemy.orm import Session

from app.models import AgentConversation, AgentMessage, User


class ConversationStore:
    """Handles loading and saving conversations and messages."""

    def __init__(self, async_db: AsyncSession):
        """Initialize store with async database session."""
        self.db = async_db

    async def get_or_create_conversation(
        self,
        user_id: UUID,
        conversation_id: UUID | None = None,
        workspace_id: UUID | None = None,
        title: str | None = None,
    ) -> AgentConversation:
        """Get existing conversation or create new one."""

        # If conversation_id provided, load it
        if conversation_id:
            stmt = select(AgentConversation).where(
                and_(
                    AgentConversation.id == conversation_id,
                    AgentConversation.user_id == user_id
                )
            )
            result = await self.db.execute(stmt)
            conv = result.scalar_one_or_none()
            if conv:
                return conv
            # If conversation not found, treat as new conversation

        # Create new conversation
        new_conv = AgentConversation(
            user_id=user_id,
            workspace_id=workspace_id,
            title=title or f"Conversation {datetime.utcnow().isoformat()}",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(new_conv)
        await self.db.flush()
        return new_conv

    async def get_recent_messages(
        self,
        conversation_id: UUID,
        limit: int = 10,
    ) -> list[AgentMessage]:
        """
        Load the most recent N messages from conversation, returned in
        chronological order (oldest first) so they can be fed directly
        into the LLM context window.

        FIX: The original query used .order_by(asc).limit(N) which returned
        the OLDEST N messages, not the newest. With 25 messages and limit=10
        this gave msg 1-10 instead of msg 16-25, making the AI lose all recent
        context. Correct approach: sort DESC to get newest N, then reverse in
        Python to restore chronological order for the LLM.

        Memory coverage logic:
        - If conv.summary exists: it already covers messages older than what
          get_recent_messages returns, so fetching newest N is sufficient.
        - If conv.summary is None and total messages > limit: there is a gap.
          The summarizer triggers at MESSAGE_THRESHOLD (20 msgs). Until then
          the sliding window is the only context — always fetch the newest N.
        """
        # Fetch newest N by sorting DESC, then reverse to chronological order
        stmt = (
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        messages = result.scalars().all()
        # Reverse so the list is oldest→newest (correct order for LLM context)
        return list(reversed(messages))

    async def save_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str | None = None,
        tool_name: str | None = None,
        tool_input: dict | None = None,
        tool_output: dict | None = None,
        token_count: int | None = None,
    ) -> AgentMessage:
        """Save a message to the conversation."""

        message = AgentMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_input=tool_input or {},
            tool_output=tool_output or {},
            token_count=token_count,
            created_at=datetime.utcnow(),
        )
        self.db.add(message)
        await self.db.flush()
        return message

    async def update_conversation_timestamp(self, conversation_id: UUID) -> None:
        """Update conversation's updated_at timestamp."""

        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one()
        conv.updated_at = datetime.utcnow()
        await self.db.flush()

    async def increment_message_count(self, conversation_id: UUID) -> None:
        """Increment the message count for a conversation."""

        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv:
            conv.message_count = (conv.message_count or 0) + 1
            await self.db.flush()

    async def increment_token_count(self, conversation_id: UUID, token_count: int) -> None:
        """Add tokens to the conversation's total token count."""

        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv:
            conv.total_token_count = (conv.total_token_count or 0) + token_count
            await self.db.flush()

    async def get_conversation_by_id(self, conversation_id: UUID, user_id: UUID) -> AgentConversation | None:
        """Get a specific conversation, verifying user ownership."""

        stmt = select(AgentConversation).where(
            and_(
                AgentConversation.id == conversation_id,
                AgentConversation.user_id == user_id
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_conversations(
        self, user_id: UUID, limit: int = 50, offset: int = 0
    ) -> tuple[list[AgentConversation], int]:
        """List conversations for a user with pagination."""

        # FIX: Use COUNT aggregate instead of loading all rows into memory
        count_stmt = select(func.count()).select_from(AgentConversation).where(
            AgentConversation.user_id == user_id
        )
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar_one()

        # Get paginated results
        stmt = (
            select(AgentConversation)
            .where(AgentConversation.user_id == user_id)
            .order_by(desc(AgentConversation.updated_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        conversations = result.scalars().all()

        return conversations, total

    async def delete_conversation(self, conversation_id: UUID, user_id: UUID) -> bool:
        """Delete a conversation and all its messages (hard delete for privacy)."""

        # Verify ownership
        stmt = select(AgentConversation).where(
            and_(
                AgentConversation.id == conversation_id,
                AgentConversation.user_id == user_id
            )
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()

        if not conv:
            return False

        # FIX: Use proper SQLAlchemy delete() DML statement instead of
        # incorrectly chaining .delete() on a select() query.
        await self.db.execute(
            delete(AgentMessage).where(
                AgentMessage.conversation_id == conversation_id
            )
        )

        # Delete conversation
        await self.db.delete(conv)
        await self.db.flush()
        return True