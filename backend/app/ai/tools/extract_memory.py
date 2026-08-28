"""Tool: extract_memory - Retrieve stored memory about the workspace.

Searches Zep semantic memory graph and fetches conversation episodic summaries
from PostgreSQL to provide context-aware memory retrieval.
"""

from uuid import UUID
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.agents.tool_context import ToolContext
from app.services.semantic_memory_provider import get_semantic_memory_provider
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Sàn chặn rác, **không phải** bộ lọc liên quan.
#
# Đo tại 2026-08-27 với `gemini-embedding-2-preview`, trên bộ nhớ "khi tôi
# remote thì phải check-in Slack…":
#
#     làm việc từ xa      0.6285   ✓ đúng
#     hôm nay tôi remote  0.5966   ✓ đúng
#     deadline dự án      0.5835   ✗ SAI
#     remote              0.5810   ✓ đúng
#     thời tiết hôm nay   0.5232   ✗ sai
#
# `deadline dự án` xếp **trên** `remote` — một dương tính thật. Hai dải
# chồng nhau, nên không con số nào tách được chúng: đặt ngưỡng ở 0.59 để
# chặn `deadline` thì mất luôn `remote`, mà 0.581 với 0.5835 chỉ cách nhau
# bằng nhiễu.
#
# Nên ngưỡng ở đây chỉ làm một việc khiêm tốn: cắt phần rõ ràng không liên
# quan (~0.50–0.52). Việc phán đoán "quy trình này có thật sự nói về hoàn
# cảnh người dùng vừa nêu không" giao cho model — nó *đọc* được điều kiện
# "khi tôi remote" và biết ngay `deadline dự án` không khớp, thứ mà một
# phép so sánh số không làm được. Prompt hệ thống ra lệnh kiểm điều đó
# trước khi đề xuất bất cứ gì.
MIN_RELEVANCE_SCORE = 0.55


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
