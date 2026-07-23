"""Conversation store for persisting agent conversations and messages."""

from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_, delete, func, update, text
from sqlalchemy.orm import Session

from app.utils.logger import get_logger
from app.utils.tokens import estimate_message_tokens

from app.models import AgentConversation, AgentMessage, User

logger = get_logger(__name__)


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

    async def get_recent_messages_by_token_budget(
        self,
        conversation_id: UUID,
        max_tokens: int = 8000,
        fetch_limit: int = 50,
    ) -> list[AgentMessage]:
        """
        Load the most recent messages that fit within a token budget.
        Fetches fetch_limit newest messages, keeps newest first within
        budget, returns in chronological order (oldest -> newest).

        Falls back to get_recent_messages(limit=10) if token estimation fails.
        """
        try:
            stmt = (
                select(AgentMessage)
                .where(AgentMessage.conversation_id == conversation_id)
                .order_by(AgentMessage.created_at.desc())
                .limit(fetch_limit)
            )
            result = await self.db.execute(stmt)
            all_messages = list(result.scalars().all())
            if not all_messages:
                return []

            # Iterate newest -> oldest, keep newest within budget
            total_tokens = 0
            keep: list[AgentMessage] = []
            for msg in all_messages:
                tokens = estimate_message_tokens(
                    role=msg.role,
                    content=getattr(msg, 'content', None),
                    tool_name=getattr(msg, 'tool_name', None),
                    tool_output=getattr(msg, 'tool_output', None),
                )
                if total_tokens + tokens > max_tokens:
                    if not keep:
                        # Edge case: newest message alone exceeds budget
                        # Keep at least this one to avoid empty history
                        logger.warning(
                            f"Newest message exceeds max_tokens ({tokens} > {max_tokens}) "
                            f"for conversation {conversation_id} — keeping it anyway"
                        )
                        keep.append(msg)
                        total_tokens += tokens
                    break
                total_tokens += tokens
                keep.append(msg)

            # Reverse to oldest -> newest (expected by _build_history_contents)
            keep.reverse()

            logger.info(
                f"Token-budget history: kept {len(keep)}/{len(all_messages)} messages "
                f"({total_tokens}/{max_tokens} tokens) for conversation {conversation_id}"
            )
            return keep
        except Exception as exc:
            logger.warning(f"Token-budget history failed, falling back to message-count limit: {exc}")
            return await self.get_recent_messages(conversation_id, limit=10)

    async def save_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str | None = None,
        tool_name: str | None = None,
        tool_input: dict | None = None,
        tool_output: dict | None = None,
        tool_call_id: str | None = None,
        turn_id: UUID | None = None,
        token_count: int | None = None,
        context: dict | None = None,
    ) -> AgentMessage | None:
        """Save a message to the conversation."""

        normalized_role = role.strip().lower() if role else role
        normalized_content = content.strip() if isinstance(content, str) else content

        # Normalize non-tool messages
        if normalized_role in {"user", "assistant"}:
            if not normalized_content:
                logger.info(
                    f"⏭️ Skipping empty {normalized_role} message for conversation {conversation_id}"
                )
                return None
            tool_name = None
            tool_input = None
            tool_output = None

            # Collapse consecutive same-role messages to preserve alternation
            last_stmt = (
                select(AgentMessage)
                .where(AgentMessage.conversation_id == conversation_id)
                .order_by(AgentMessage.created_at.desc())
                .limit(1)
            )
            last_result = await self.db.execute(last_stmt)
            last_msg = last_result.scalar_one_or_none()
            if last_msg and last_msg.role == normalized_role:
                logger.info(
                    f"⏭️ Collapsing consecutive '{normalized_role}' message in conversation {conversation_id}"
                )
                last_msg.content = normalized_content
                last_msg.context = context
                last_msg.created_at = datetime.utcnow()
                await self.db.flush()
                return last_msg

        elif normalized_role == "tool":
            if not tool_name or tool_input is None or tool_output is None:
                logger.info(
                    f"⏭️ Skipping incomplete tool message for conversation {conversation_id}: "
                    f"tool_name={tool_name}, input_present={tool_input is not None}, "
                    f"output_present={tool_output is not None}"
                )
                return None
        else:
            logger.warning(
                f"Unknown role '{role}' when saving message for conversation {conversation_id}"
            )

        message = AgentMessage(
            conversation_id=conversation_id,
            role=normalized_role,
            content=normalized_content,
            context=context,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            tool_call_id=tool_call_id,
            turn_id=turn_id,
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
        """Increment the message count atomically using UPDATE ... RETURNING.

        Avoids the race-condition of SELECT-then-UPDATE when multiple
        concurrent requests add messages to the same conversation.
        """

        stmt = (
            update(AgentConversation)
            .where(AgentConversation.id == conversation_id)
            .values(message_count=AgentConversation.message_count + 1)
            .returning(AgentConversation.message_count)
        )
        result = await self.db.execute(stmt)
        row = result.one_or_none()
        if row is None:
            logger.warning(
                f"increment_message_count: conversation {conversation_id} not found"
            )
        await self.db.flush()

    async def increment_token_count(self, conversation_id: UUID, token_count: int) -> None:
        """Add tokens to the conversation's total token count atomically."""

        stmt = (
            update(AgentConversation)
            .where(AgentConversation.id == conversation_id)
            .values(total_token_count=AgentConversation.total_token_count + token_count)
            .returning(AgentConversation.total_token_count)
        )
        result = await self.db.execute(stmt)
        row = result.one_or_none()
        if row is None:
            logger.warning(
                f"increment_token_count: conversation {conversation_id} not found"
            )
        await self.db.flush()

    async def update_conversation_title(self, conversation_id: UUID, title: str) -> AgentConversation | None:
        """Update conversation title."""

        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv:
            conv.title = title
            conv.updated_at = datetime.utcnow()
            await self.db.flush()
        return conv

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