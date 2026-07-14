"""
Memory Extraction Service

Orchestrates the conversation memory extraction pipeline:
1. Fetches only new messages (since last extraction) + existing summary
2. Calls LLM with structured extraction prompt
3. Parses JSON response
4. Stores updated Episodic Summary in PostgreSQL (UPSERT)
5. Stores new Semantic Memories in Zep
"""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AgentConversation, AgentMessage
from app.ai.agents.model_client import ModelClient
from app.ai.agents.provider_types import Message, GenerationConfig
from app.services.memory_extraction_prompt import build_extraction_messages
from app.services.zep_memory import (
    ensure_user,
    add_semantic_memories_batch,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_model_client = ModelClient()


def _build_conversation_text(messages: list[AgentMessage]) -> str:
    """Build a conversation transcript from messages."""
    parts = []
    for msg in messages:
        role_label = msg.role.capitalize()
        content = msg.content or ""
        if msg.role == "tool":
            tool_name = msg.tool_name or "unknown"
            output = msg.tool_output or {}
            summary = str(output)[:200] if output else ""
            parts.append(f"Tool ({tool_name}): {summary}")
        else:
            parts.append(f"{role_label}: {content}")
    return "\n\n".join(parts)


async def extract_and_store(
    conversation_id: UUID,
    db: AsyncSession,
) -> dict:
    """Extract structured memory from a conversation and store it.

    Only processes messages added since the last extraction (incremental).
    Merges new findings with the existing episodic summary.

    Args:
        conversation_id: UUID of the conversation to analyze.
        db: Async database session.

    Returns:
        dict with keys: success, episodic_stored, semantic_count, model_used, title
    """
    # Fetch conversation
    stmt = select(AgentConversation).where(AgentConversation.id == conversation_id)
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        return {"success": False, "error": "Conversation not found"}

    workspace_id_str = str(conv.workspace_id) if conv.workspace_id else None

    # Fetch only messages since last extraction (or all if first time)
    if conv.last_extracted_at:
        msg_stmt = (
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .where(AgentMessage.created_at > conv.last_extracted_at)
            .order_by(AgentMessage.created_at.asc())
        )
    else:
        msg_stmt = (
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.created_at.asc())
        )
    result = await db.execute(msg_stmt)
    new_messages = result.scalars().all()

    if len(new_messages) < 5:
        return {"success": False, "reason": "Not enough new messages to extract memory"}

    conversation_text = _build_conversation_text(new_messages)
    existing_summary = conv.summary

    # Call LLM with structured extraction prompt
    try:
        extraction_messages = build_extraction_messages(
            conversation_text,
            existing_summary=existing_summary,
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
            estimated_tokens=3000,
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
        conv.last_extracted_at = datetime.utcnow()
        conv.updated_at = datetime.utcnow()
        await db.flush()
        logger.info(f"Stored episodic summary for conversation {conversation_id}")
        episodic_stored = True
    except Exception as exc:
        logger.error(f"Failed to store episodic summary: {exc}")
        episodic_stored = False

    # ── 2. Store Semantic Memories in Zep ──
    semantic_memories = result_data.get("semantic_memories", [])
    semantic_count = 0

    if semantic_memories:
        if not workspace_id_str:
            logger.warning(f"No workspace_id for conversation {conversation_id} — skipping Zep storage")
        else:
            await ensure_user(user_id=workspace_id_str)

            semantic_count = await add_semantic_memories_batch(
                user_id=workspace_id_str,
                memories=semantic_memories,
            )
            logger.info(f"Stored {semantic_count}/{len(semantic_memories)} semantic memories for workspace {workspace_id_str}")

    await db.commit()

    return {
        "success": True,
        "episodic_stored": episodic_stored,
        "semantic_count": semantic_count,
        "model_used": model_used,
        "title": title,
        "new_messages": len(new_messages),
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

    # Filter by confidence
    data["semantic_memories"] = [
        m for m in data["semantic_memories"]
        if isinstance(m, dict) and m.get("confidence", 0) >= 0.7
    ]

    return data
