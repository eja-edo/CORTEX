"""
Structured memory extraction prompt for conversation summarization.

Designed for a tiered memory architecture:
- Episodic Summary  → PostgreSQL (rolling, updated each time)
- Semantic Memory   → Zep (long-term graph memory)
"""

from app.ai.loaders.prompt_loader import load
from app.services.task_extraction_prompt import append_task_instructions

MEMORY_EXTRACTION_SYSTEM_PROMPT = load("memory/semantic_extraction.md")


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
        user_content += "\n\nRespond with a JSON object containing episodic_summary, semantic_memories, and title."

    return [
        {"role": "system", "content": MEMORY_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
