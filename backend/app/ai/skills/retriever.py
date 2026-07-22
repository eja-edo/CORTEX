"""SkillRetriever — matches user intent to relevant skills.

Two strategies (configurable):
  A. Keyword matching: zero-cost, fast, good enough for most cases
  B. LLM-based routing: model picks the right skill (higher accuracy)

Phase 2 will add embedding-based matching via pgvector.
"""

from __future__ import annotations

import re
from typing import Callable

from app.utils.logger import get_logger
from app.ai.skills.models import SkillMetadata
from app.ai.skills.registry import get_skill_registry

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Keyword extractors
# ---------------------------------------------------------------------------

# Skill → keyword signatures (manually curated for precision)
_SKILL_SIGNATURES: dict[str, list[str]] = {
    "research": [
        "research", "search", "find", "look up", "investigate",
        "fact-check", "sources", "citation", "reference", "deep dive",
        "analyze this topic", "what is", "tell me about", "information on",
        "web", "internet", "online", "article", "news", "latest",
        "current event", "explain", "how does", "why is",
        # Vietnamese
        "nghiên cứu", "tìm kiếm", "tra cứu", "tìm hiểu",
        "thông tin", "bài báo", "tin tức", "web",
        "giải thích", "là gì", "như thế nào", "tại sao",
    ],
    "planning": [
        "plan", "schedule", "time", "calendar", "deadline", "task",
        "organize", "arrange", "prepare", "agenda", "timeline",
        "free slot", "available", "busy", "conflict", "prioritize",
        "this week", "this month", "today", "tomorrow", "upcoming",
        "goal", "routine", "habit", "time-block",
        # Vietnamese
        "kế hoạch", "lịch", "thời gian", "tuần này", "tháng này",
        "hôm nay", "ngày mai", "deadline", "hạn chót",
        "sắp xếp", "tổ chức", "chuẩn bị", "ưu tiên",
        "rảnh", "bận", "xung đột", "lịch trình",
        "mục tiêu", "thói quen", "công việc", "việc cần làm",
    ],
    "reasoning": [
        "reason", "think", "analyze", "compare", "evaluate",
        "pros and cons", "trade-off", "decision", "should I",
        "what if", "scenario", "root cause", "why did",
        "hypothesis", "assume", "logic", "implication",
        "framework", "methodology", "strategy",
        "complex", "ambiguous", "multi-dimensional",
        # Vietnamese
        "suy nghĩ", "phân tích", "so sánh", "đánh giá",
        "nên", "lựa chọn", "quyết định", "giả sử",
        "nguyên nhân", "kịch bản", "chiến lược",
        "ưu điểm", "nhược điểm", "lợi ích", "rủi ro",
        "phức tạp", "logic", "khung", "phương pháp",
    ],
    "memory": [
        "remember", "forget", "recall", "memory", "context",
        "preference", "habit", "pattern", "previous",
        "as we discussed", "last time", "you know that",
        "save this", "keep this", "note this",
        "I always", "I usually", "I prefer", "I like",
        "personal", "background",
        # Vietnamese
        "nhớ", "quên", "ghi nhớ", "thói quen",
        "sở thích", "ưu tiên", "cá nhân", "background",
        "lúc trước", "hồi trước", "như đã nói",
        "tôi thường", "tôi thích", "tôi luôn", "tôi hay",
        "lưu lại", "ghi lại", "ghi chú",
    ],
    "workflow": [
        "workflow", "automate", "auto", "trigger", "pipeline",
        "when this happens", "every time", "recurring task",
        "process", "integration", "connect", "sync",
        "routine task", "automatic", "notification",
        "if this then", "chain", "sequence", "step",
        # Vietnamese
        "tự động", "tự động hóa", "quy trình", "workflow",
        "khi", "mỗi khi", "hàng ngày", "hàng tuần",
        "báo cáo", "thông báo", "notification",
        "kết nối", "tích hợp", "đồng bộ",
        "bước", "chuỗi", "trình tự", "tác vụ",
    ],
}


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


class SkillRetriever:
    """Matches user message + conversation context to relevant skills."""

    def __init__(self, strategy: str = "keyword") -> None:
        if strategy not in ("keyword",):
            raise ValueError(f"Unknown retriever strategy: {strategy}")
        self._strategy = strategy
        self._registry = get_skill_registry()

    # -- public API ---------------------------------------------------------

    def select(
        self,
        message: str,
        context: dict | None = None,
        max_skills: int = 2,
    ) -> list[SkillMetadata]:
        """Return the top-N skills relevant to the current user message.

        Args:
            message: The user's current message.
            context: Optional conversation context (pills, runtime, history).
            max_skills: Maximum number of skills to return.

        Returns:
            Ordered list of SkillMetadata, most relevant first.
        """
        if self._strategy == "keyword":
            return self._select_keyword(message, context, max_skills)
        return []

    def select_and_load(
        self,
        message: str,
        context: dict | None = None,
        max_skills: int = 2,
    ):
        """Convenience: select skills and load them in one call."""
        selected = self.select(message, context, max_skills)
        return self._registry.load_all([s.name for s in selected])

    # -- keyword strategy ---------------------------------------------------

    def _select_keyword(
        self,
        message: str,
        context: dict | None = None,
        max_skills: int = 2,
    ) -> list[SkillMetadata]:
        all_meta = self._registry.list_metadata()
        if not all_meta:
            return []

        combined = message.lower()
        if context:
            pills = context.get("pills", [])
            for p in pills:
                text = p.get("text", "") if isinstance(p, dict) else getattr(p, "text", "")
                combined += " " + text.lower()

        scored: list[tuple[SkillMetadata, int]] = []
        for meta in all_meta:
            score = self._keyword_score(combined, meta.name)
            if score > 0:
                scored.append((meta, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        result = [meta for meta, _ in scored[:max_skills]]
        if result:
            names = [s.name for s in result]
            logger.debug("SkillRetriever: selected %s (keyword)", names)
        return result

    def _keyword_score(self, text: str, skill_name: str) -> int:
        """Count how many signature keywords match in text (word-boundary).

        Uses word-boundary regex so that 'reference' does NOT match
        inside 'preference', and 'plan' does NOT match 'planned'.
        """
        signatures = _SKILL_SIGNATURES.get(skill_name, [])
        if not signatures:
            return 0
        score = 0
        for kw in signatures:
            pattern = re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
            if pattern.search(text):
                score += 1
        return score


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_retriever: SkillRetriever | None = None


def get_skill_retriever(strategy: str = "keyword") -> SkillRetriever:
    global _retriever
    if _retriever is None:
        _retriever = SkillRetriever(strategy=strategy)
    return _retriever


def reset_skill_retriever() -> None:
    global _retriever
    _retriever = None
