"""
Memory Extraction Service

Orchestrates the conversation memory extraction pipeline:
1. Fetches only new messages (since last extraction) + existing summary
2. Calls LLM with structured extraction prompt
3. Parses JSON response
4. Stores updated Episodic Summary in PostgreSQL (UPSERT)
5. Stores new Semantic Memories in Zep

Tool output truncation (Issue 7):
- Conversation LLM pipeline truncates at TOOL_OUTPUT_MAX_CHARS (4000)
- Memory extraction pipeline uses MEMORY_TOOL_OUTPUT_MAX_CHARS
"""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AgentConversation, AgentMessage
from app.ai.agents.conversation_store import ConversationStore
from app.ai.agents.model_client import ModelClient
from app.ai.agents.provider_types import Message, GenerationConfig
from app.services.memory_extraction_prompt import build_extraction_messages
from app.services.semantic_memory_provider import get_semantic_memory_provider
from app.utils.logger import get_logger

logger = get_logger(__name__)

_model_client = ModelClient()

# Tool output truncation for the memory extraction LLM prompt.
# Value chosen based on production data (88 tool messages):
#   P50 = 216, P90 = 24,048, P95 = 41,586, P99 = 55,656, Max = 55,656
# 25,000 covers 90% of tool outputs while protecting the memory extraction
# model's context window from rare massive payloads.
# Independent from the conversation-LLM truncation (TOOL_OUTPUT_MAX_CHARS = 4000
# in openai_provider.py) because the two pipelines use different models with
# different context-window budgets.
MEMORY_TOOL_OUTPUT_MAX_CHARS = 25000


def _build_conversation_text(messages: list[AgentMessage]) -> str:
    """Build a conversation transcript from messages."""
    parts = []
    for msg in messages:
        role_label = msg.role.capitalize()
        content = msg.content or ""
        if msg.role == "tool":
            tool_name = msg.tool_name or "unknown"
            output = msg.tool_output or {}
            summary = str(output)[:MEMORY_TOOL_OUTPUT_MAX_CHARS] if output else ""
            if len(summary) >= MEMORY_TOOL_OUTPUT_MAX_CHARS:
                summary += (
                    f"\n\n[Output truncated at {MEMORY_TOOL_OUTPUT_MAX_CHARS} chars]"
                )
            parts.append(f"Tool ({tool_name}): {summary}")
        else:
            parts.append(f"{role_label}: {content}")
    return "\n\n".join(parts)


async def extract_and_store(
    conversation_id: UUID,
    db: AsyncSession,
    extract_tasks: bool = False,
    min_new_messages: int = 5,
) -> dict:
    """Extract structured memory from a conversation and store it.

    Only processes messages added since the last extraction (incremental).
    Merges new findings with the existing episodic summary.

    Args:
        conversation_id: UUID of the conversation to analyze.
        db: Async database session.
        extract_tasks: Also pull tasks the user committed to out of the same
            call (see `app.services.task_extraction`). One prompt, one call
            — task extraction never adds an LLM round trip of its own.
        min_new_messages: Below this, extraction is skipped. The default of
            5 suits memory, which is accumulated background knowledge where
            a small gap is soft. The idle flush passes 1: a task suggestion
            is a discrete, dated, one-off statement, and "thứ 6 tôi gửi
            proposal cho John" is a two-message conversation. Applying the
            memory threshold there would drop exactly the case task
            extraction exists to catch.

    Returns:
        dict with keys: success, episodic_stored, semantic_count, model_used,
        title, and (when extract_tasks) tasks
    """
    # Fetch conversation
    stmt = select(AgentConversation).where(AgentConversation.id == conversation_id)
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        return {"success": False, "error": "Conversation not found"}

    workspace_id_str = str(conv.workspace_id) if conv.workspace_id else None

    store = ConversationStore(db)
    new_messages = await store.get_messages_since(conversation_id, conv.last_summary_message_id)

    if len(new_messages) < min_new_messages:
        return {"success": False, "reason": "Not enough new messages to extract memory"}

    conversation_text = _build_conversation_text(new_messages)
    existing_summary = conv.summary

    # Call LLM with structured extraction prompt
    try:
        extraction_messages = build_extraction_messages(
            conversation_text,
            existing_summary=existing_summary,
            include_tasks=extract_tasks,
        )
        msgs = [
            Message(role=m["role"], content=m["content"])
            for m in extraction_messages
        ]

        gen_config = GenerationConfig(
            temperature=0.2,
            max_output_tokens=4096,
        )

        model_used, response = await _model_client.generate(
            messages=msgs,
            config=gen_config,
        )

        if not response or not response.content:
            return {"success": False, "error": "Empty LLM response"}

        result_data = _parse_extraction_response(response.content)
        if not result_data:
            return {"success": False, "error": "Failed to parse structured response"}

    except Exception as exc:
        logger.error(f"LLM extraction failed for conversation {conversation_id}: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}

    # ── 1. Store Episodic Summary in PostgreSQL ──
    episodic_summary = result_data.get("episodic_summary", "")
    title = result_data.get("title", "")

    try:
        conv.summary = episodic_summary
        if title:
            conv.title = title
        conv.last_summary_message_id = new_messages[-1].id
        conv.last_extracted_at = datetime.utcnow()
        conv.updated_at = datetime.utcnow()
        await db.flush()
        logger.info(f"Stored episodic summary for conversation {conversation_id}")
        episodic_stored = True
    except Exception as exc:
        logger.error(f"Failed to store episodic summary: {exc}")
        episodic_stored = False

    # ── 2. Store Semantic Memories ──
    semantic_memories = result_data.get("semantic_memories", [])
    semantic_count = 0

    if semantic_memories:
        if not workspace_id_str:
            logger.warning(f"No workspace_id for conversation {conversation_id} — skipping semantic memory storage")
        else:
            provider = get_semantic_memory_provider(db)
            await provider.ensure_user(user_id=workspace_id_str)

            semantic_count = await provider.add_semantic_memories_batch(
                user_id=workspace_id_str,
                memories=semantic_memories,
            )
            logger.info(f"Stored {semantic_count}/{len(semantic_memories)} semantic memories for workspace {workspace_id_str}")

    # ── 3. Store task candidates ──
    #
    # Validated before anything is written: the LLM proposes, the
    # conditions in task_extraction.py dispose. Failures here never fail
    # the extraction — losing a conversation's episodic summary because one
    # candidate was malformed would be a much worse trade.
    task_result = None
    if extract_tasks:
        try:
            from app.services.task_extraction import TaskCandidateService

            candidate_service = TaskCandidateService(db)
            task_result = await candidate_service.store_candidates(
                raw_candidates=result_data.get("tasks") or [],
                user_id=conv.user_id,
                conversation_id=conversation_id,
                message_id=new_messages[-1].id if new_messages else None,
            )
            logger.info(
                f"Task extraction | conversation={conversation_id} | "
                f"created={task_result['created_count']} | "
                f"rejected={task_result['rejected_count']} | "
                f"rules={task_result['rejected_rules']}"
            )
        except Exception as exc:
            logger.error(f"Task candidate storage failed: {exc}", exc_info=True)

    await db.commit()

    return {
        "success": True,
        "episodic_stored": episodic_stored,
        "semantic_count": semantic_count,
        "model_used": model_used,
        "title": title,
        "new_messages": len(new_messages),
        "tasks": task_result,
    }


def _parse_extraction_response(content: str) -> dict | None:
    """Parse the LLM response into structured extraction result."""
    text = content.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]

    # Extract JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.error("No JSON object found in extraction response")
        return None

    text = text[start:end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(f"JSON parse error in extraction response: {exc}")
        return None

    # Validate structure
    if "episodic_summary" not in data:
        logger.error("Missing 'episodic_summary' in extraction response")
        return None

    # Ensure semantic_memories is a list
    if "semantic_memories" not in data or not isinstance(data["semantic_memories"], list):
        data["semantic_memories"] = []

    # Normalize string memories to dict format with defaults
    normalized = []
    for m in data["semantic_memories"]:
        if isinstance(m, str):
            normalized.append({
                "content": m,
                "category": "unknown",
                "confidence": 0.8,
                "expected_lifetime": "medium",
            })
        elif isinstance(m, dict) and m.get("confidence", 0) >= 0.7:
            normalized.append(m)
    data["semantic_memories"] = normalized

    return data
