"""Tool: extract_memory - Retrieve stored memory about the workspace.

Searches Zep semantic memory graph and fetches conversation episodic summaries
from PostgreSQL to provide context-aware memory retrieval.
"""

from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
from app.services.zep_memory import search_semantic_memories
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ExtractMemoryInput(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=500,
        description="Search query to find relevant memories.",
    )
    workspace_id: str | None = Field(
        None,
        description="Workspace ID to scope the memory search. Defaults to the current workspace.",
    )
    conversation_id: str | None = Field(
        None,
        description="Optional conversation ID to include episodic summary context.",
    )
    limit: int = Field(
        default=10, ge=1, le=50,
        description="Maximum number of semantic memories to return.",
    )


async def extract_memory_handler(args: dict, ctx: ToolContext) -> dict:
    """Handle extract_memory tool call."""
    from uuid import UUID
    from sqlalchemy import select
    from app.models import AgentConversation

    ws_id = args.get("workspace_id") or str(ctx.workspace_id) if ctx.workspace_id else None
    conv_id = args.get("conversation_id")
    query = args.get("query", "")
    limit = args.get("limit", 10)

    if not ws_id:
        return {
            "success": False,
            "error": "No workspace_id available. Cannot search memories.",
        }

    # ── 1. Search Zep semantic memory ──
    memories = await search_semantic_memories(
        user_id=ws_id,
        query=query,
        limit=limit,
    )

    # ── 2. Fetch episodic summary from PostgreSQL ──
    episodic_summary = ""
    if conv_id:
        async with ctx.async_db() as db:
            stmt = select(AgentConversation).where(
                AgentConversation.id == UUID(conv_id)
            )
            result = await db.execute(stmt)
            conv = result.scalar_one_or_none()
            if conv and conv.summary:
                episodic_summary = conv.summary

    # ── 3. Format result ──
    parts = []

    if memories:
        lines = []
        for m in memories:
            score_str = f" (score: {m['score']:.2f})" if m.get("score") else ""
            category = m.get("category", "")
            cat_str = f" [{category}]" if category else ""
            fact = m.get("fact", m.get("content", ""))
            lines.append(f"- {fact}{cat_str}{score_str}")
        parts.append("=== SEMANTIC MEMORIES ===\n" + "\n".join(lines))

    if episodic_summary:
        parts.append(f"=== EPISODIC SUMMARY ===\n{episodic_summary}")

    if not parts:
        return {
            "success": True,
            "result": "No relevant memories found.",
            "memory_count": 0,
            "has_summary": False,
        }

    result_text = "\n\n".join(parts)

    return {
        "success": True,
        "result": result_text,
        "memory_count": len(memories),
        "has_summary": bool(episodic_summary),
    }


EXTRACT_MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query to find relevant memories about the workspace",
        },
        "workspace_id": {
            "type": "string",
            "description": "Optional workspace UUID to scope memory search",
        },
        "conversation_id": {
            "type": "string",
            "description": "Optional conversation UUID to include episodic summary context",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of semantic memories to return (1-50)",
            "default": 10,
        },
    },
    "required": ["query"],
}

EXTRACT_MEMORY_DEFINITION = {
    "name": "extract_memory",
    "handler": extract_memory_handler,
    "input_model": ExtractMemoryInput,
    "schema": EXTRACT_MEMORY_SCHEMA,
    "description": (
        "Retrieve stored memory about the workspace. "
        "Searches the long-term semantic memory graph for relevant information "
        "about projects, preferences, decisions, and environment. "
        "Optionally includes episodic summary from a specific conversation. "
        "Use this when you need to recall past decisions, preferences, or context."
    ),
}
