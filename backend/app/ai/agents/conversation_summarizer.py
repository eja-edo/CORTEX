"""Service for summarizing conversations using structured memory extraction."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConversation, AgentMessage
from app.ai.agents.conversation_store import ConversationStore
from app.services.memory_extraction_service import extract_and_store
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConversationSummarizer:
    """
    Summarizes conversations using structured memory extraction.

    Pipeline:
      1. LLM extracts: Episodic Summary + Semantic Memories + Title
      2. Episodic Summary → PostgreSQL (conv.summary, UPSERT)
      3. Semantic Memories → Zep (long-term graph)
    """

    MESSAGE_THRESHOLD = 20
    TOKEN_THRESHOLD = 20000

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def summarize_conversation(
        self,
        conversation_id: UUID,
        extract_tasks: bool = True,
        min_new_messages: int = 5,
    ) -> dict:
        """
        Run memory extraction on a conversation.

        On success, resets summary counters (tokens_since_last_summary,
        messages_since_last_summary) and updates last_summary_message_id.

        Args:
            conversation_id: conversation to extract from.
            extract_tasks: ask the same LLM call for tasks the user
                committed to as well. Defaults to on — it costs no extra
                round trip, and the threshold trigger firing without it
                would mean a task sitting unnoticed in an already-summarised
                conversation.
            min_new_messages: see extract_and_store. The idle flush lowers
                this to 1 so two-message conversations aren't skipped.

        Returns dict with keys: success, episodic_stored, semantic_count,
        model_used, title, tasks
        """
        logger.info(f"Starting memory extraction for conversation {conversation_id}")

        result = await extract_and_store(
            conversation_id=conversation_id,
            db=self.db,
            extract_tasks=extract_tasks,
            min_new_messages=min_new_messages,
        )

        if result.get("success"):
            store = ConversationStore(self.db)
            await store.reset_summary_counters(conversation_id)
            logger.info(
                f"Memory extraction complete | conversation={conversation_id} | "
                f"episodic={result.get('episodic_stored')} | "
                f"semantic_count={result.get('semantic_count')} | "
                f"model={result.get('model_used')}"
            )
        else:
            logger.warning(
                f"Memory extraction failed | conversation={conversation_id} | "
                f"error={result.get('error', result.get('reason', 'unknown'))}"
            )

        return result

    async def get_conversation_context(
        self,
        conversation_id: UUID,
        include_summary: bool = True,
    ) -> str:
        """Get the episodic summary with boundary timestamp for context injection.

        Marks where the summary ends and recent conversation begins so the LLM
        understands the temporal scope of each section.
        """
        if not include_summary:
            return ""

        stmt = select(AgentConversation).where(
            AgentConversation.id == conversation_id
        )
        result = await self.db.execute(stmt)
        conv = result.scalar_one_or_none()

        if not conv or not conv.summary or not conv.last_summary_message_id:
            return ""

        last_msg = await self.db.get(AgentMessage, conv.last_summary_message_id)
        if not last_msg:
            return ""

        cutoff = last_msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            f"=== PREVIOUS CONVERSATION HISTORY (events up to {cutoff}) ===\n"
            f"{conv.summary}\n\n"
            f"=== RECENT CONVERSATION ===\n"
        )


def get_conversation_summarizer(db: AsyncSession) -> ConversationSummarizer:
    return ConversationSummarizer(db)
