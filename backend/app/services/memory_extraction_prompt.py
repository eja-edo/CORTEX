"""
Structured memory extraction prompt for conversation summarization.

Designed for a tiered memory architecture:
- Episodic Summary  → PostgreSQL (rolling, updated each time)
- Semantic Memory   → Zep (long-term graph memory)
"""

from app.ai.loaders.prompt_loader import load
from app.services.task_extraction_prompt import append_task_instructions

MEMORY_EXTRACTION_SYSTEM_PROMPT = load("memory/semantic_extraction.md")

# Dòng chốt của lượt user — và là thứ quyết định định dạng thật sự.
#
# Trước đây chỗ này chỉ viết "a JSON object containing episodic_summary,
# semantic_memories, and title": gọi đúng tên ba khoá, nhưng không nói
# `semantic_memories` là *list of object*. Model đọc nó cuối cùng, sau cả
# system prompt, nên nó thắng — và trả về chuỗi trần. Bộ chuẩn hoá bên
# `memory_extraction_service` khi đó gán `category="unknown"`,
# `expected_lifetime="medium"`, xoá sạch phần phân loại mà system prompt
# vừa yêu cầu.
#
# Đo được, cùng một lời gọi: `tasks` — khoá duy nhất được vẽ hẳn shape ở
# gần cuối — luôn về đúng object; `semantic_memories` thì không. Nên chốt
# bằng shape, đừng chốt bằng tên khoá.
_RESPONSE_SHAPE = """Respond with a single JSON object:

{
  "episodic_summary": "markdown string",
  "semantic_memories": [
    {
      "category": "routine" | "preference" | "policy" | "fact" | "decision",
      "content": "one self-contained sentence",
      "confidence": 0.0-1.0,
      "expected_lifetime": "short" | "medium" | "long" | "permanent"
    }
  ],
  "title": "max 10 words"%s
}

Every entry in `semantic_memories` is an object with all four fields. A
bare string is not accepted — and do not write the category into the text
(`"... [routine]"`); it belongs in the `category` field.

A procedure with several steps is ONE entry, not one entry per step.

Write `content` in the language the user used. Memories are retrieved by
embedding similarity against what the user types later, so a Vietnamese
routine stored in English scores worse on the Vietnamese query that should
have found it."""


def response_shape(extra_keys: str = "") -> str:
    """The closing format instruction, optionally with extra top-level keys."""
    return _RESPONSE_SHAPE % extra_keys


def build_extraction_messages(
    conversation_text: str,
    existing_summary: str | None = None,
    include_tasks: bool = False,
) -> list[dict]:
    """Build the messages array for the memory extraction LLM call.

    Args:
        conversation_text: New messages to analyze (incremental or full).
        existing_summary: Previous episodic summary to merge with, if any.
        include_tasks: Also ask for tasks the user committed to. Rides on
            this same call rather than a second one — see
            task_extraction_prompt.

    Returns:
        List of message dicts for the LLM.
    """
    parts = []
    if existing_summary:
        parts.append(
            "=== EXISTING EPISODIC SUMMARY (merge new information into this) ==="
        )
        parts.append(existing_summary)
        parts.append("")
    parts.append("=== NEW MESSAGES TO ANALYZE ===")
    parts.append(conversation_text)

    user_content = "\n\n".join(parts)
    if include_tasks:
        user_content = append_task_instructions(user_content)
    else:
        user_content += "\n\n" + response_shape()

    return [
        {"role": "system", "content": MEMORY_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
