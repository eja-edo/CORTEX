"""Tool: extract_memory - Retrieve stored memory about the workspace.

Searches Zep semantic memory graph and fetches conversation episodic summaries
from PostgreSQL to provide context-aware memory retrieval.
"""

from uuid import UUID
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.agents.tool_context import ToolContext
from app.services.semantic_memory_provider import (
    MIN_RELEVANCE_SCORE,
    get_semantic_memory_provider,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Ngưỡng sống ở tầng provider, không phải ở tool: recall tự động của
# `ContextService` đọc cùng kho này và phải dùng cùng một sàn. Phần đo
# đạc giải thích con số nằm cạnh chỗ khai, trong
# `app/services/semantic_memory_provider.py`.


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

    # Không đòi ngữ cảnh dự án: bộ nhớ ngữ nghĩa được lọc theo `user_id`
    # bên dưới, và DM Mezon không có dự án nào đang mở. Cổng cũ ở đây làm
    # tool này chết ở đúng bề mặt hay dùng nhất.
    # Bộ nhớ khoá theo **người**, không theo container.
    #
    # Trường này từng nhận `workspace_id`, và khi workspace bị gỡ tôi để lại
    # một tham chiếu `project_id` chưa gán — tool ném `NameError` ở mọi lời
    # gọi. Nó không lộ ra vì tool đang đóng băng lúc đó.
    #
    # `user_id` mới là khoá đúng: `memory_extraction_service` ghi bằng
    # `conv.user_id`, nên đọc phải cùng khoá. Khoá theo container sẽ chia bộ
    # nhớ của một người thành nhiều mảnh không biết gì về nhau.
    memory_owner_id = str(ctx.user_id)
    conv_id = args.get("conversation_id")
    query = args.get("query", "")
    limit = args.get("limit", 10)

    # ── 1. Search semantic memory (fallback-aware) ──
    async with ctx.async_db() as db:
        provider = get_semantic_memory_provider(db)
        # Ngưỡng liên quan, không phải tuỳ chọn.
        #
        # Không có nó, tìm kiếm vector luôn trả về bộ nhớ *gần nhất* dù nó
        # có liên quan hay không — đo được: truy vấn "deadline dự án" trả
        # về quy trình làm-việc-từ-xa, vì đó là bộ nhớ duy nhất trong kho.
        #
        # Với tính năng này thì đó là kiểu hỏng nguy hiểm: prompt bảo agent
        # tra bộ nhớ mỗi khi người dùng nêu một hoàn cảnh, nên "luôn tìm
        # thấy gì đó" nghĩa là agent luôn đề xuất một quy trình — kể cả
        # quy trình sai. Thà không trả về gì còn hơn trả về nhầm (P7).
        memories = await provider.search_semantic_memories(
            user_id=memory_owner_id,
            query=query,
            limit=limit,
            min_score=MIN_RELEVANCE_SCORE,
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
        "Search this user's long-term memory for something OTHER than what "
        "they just said.\n\n"
        "Memories matching the current message are already retrieved for you "
        "every turn and appear in your context under \"What you already know "
        "about this user\". Calling this tool to fetch those again returns the "
        "same rows one round trip later — don't.\n\n"
        "Call it when the thing to look up is different from the current "
        "message:\n"
        "- the user asks what was decided about a specific topic "
        "('lần trước mình chốt gì về giá?') — search that topic, not their "
        "sentence\n"
        "- you need a preference the current message doesn't hint at, so the "
        "automatic recall had no reason to surface it\n"
        "- you want the episodic summary of a specific conversation "
        "(pass conversation_id)\n\n"
        "If the answer is already in your context section, answer from there."
    ),
}
