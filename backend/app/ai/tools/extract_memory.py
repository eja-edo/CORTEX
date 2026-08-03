"""Tool: extract_memory - Retrieve stored memory about the workspace.

Searches Zep semantic memory graph and fetches conversation episodic summaries
from PostgreSQL to provide context-aware memory retrieval.
"""

from uuid import UUID
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.agents.tool_context import ToolContext
from app.services.semantic_memory_provider import get_semantic_memory_provider
from app.services.workspace_permission import WorkspacePermission
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ExtractMemoryInput(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=500,
        description="Search query to find relevant memories.",
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
    from sqlalchemy import select
    from app.models import AgentConversation

    workspace_id = ctx.workspace_id
    if workspace_id is None:
        return {
            "success": False,
            "error": "workspace_id is required but not available in context",
        }

    # Check workspace membership
    with ctx.get_sync_db() as sync_db:
        WorkspacePermission.require_member(workspace_id, ctx.user_id, sync_db)

    ws_id = str(workspace_id)
    conv_id = args.get("conversation_id")
    query = args.get("query", "")
    limit = args.get("limit", 10)

    # ── 1. Search semantic memory (fallback-aware) ──
    async with ctx.async_db() as db:
        provider = get_semantic_memory_provider(db)
        memories = await provider.search_semantic_memories(
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
        "Retrieve stored long-term memory about the current workspace. "
        "Searches the semantic memory graph for relevant information "
        "about projects, preferences, decisions, and environment. "
        "Optionally includes episodic summary from a specific conversation. "
        "\n\n"
        "MUST be called when the user:\n"
        "- references a prior conversation, decision, or preference with relative "
        "time phrases (e.g. 'last time', 'yesterday', 'as I mentioned', 'as we discussed', "
        "'như đã nói', 'lần trước', 'hôm trước', 'tuần trước')\n"
        "- asks about a preference/setting they may have stated before that is not "
        "present in the current message\n"
        "- references an entity (project, note, task) without re-explaining what it "
        "is, expecting you to remember it\n"
        "- asks for personalized suggestions that depend on 'habits' or 'preferences' "
        "you may already know about them\n"
        "\n"
        "The recent-message window only covers the last 10 messages and may NOT contain "
        "what the user is referring to. Do not skip this check just because the recent "
        "context seems sufficient — past decisions and preferences live in long-term "
        "memory, not in the sliding window."
    ),
}
