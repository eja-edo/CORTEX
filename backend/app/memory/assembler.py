import logging
from typing import Dict, Any, List

from app.memory.models.schemas import RetrievalResult

logger = logging.getLogger(__name__)


class ContextAssembler:
    """
    Builds the final system prompt augmentation from all retrieved memories.
    """

    def assemble(self, retrieval: RetrievalResult) -> str:
        parts = []

        working = self._format_working_memory(retrieval.working_memory)
        if working:
            parts.append(f"[Recent Context]\n{working}")

        summaries = self._format_summaries(retrieval.conversation_summaries)
        if summaries:
            parts.append(f"[Conversation Summary]\n{summaries}")

        semantic = self._format_semantic(retrieval.semantic_memories)
        if semantic:
            parts.append(f"[What I Know About You]\n{semantic}")

        prefs = self._format_preferences(retrieval.preferences)
        if prefs:
            parts.append(f"[Your Preferences]\n{prefs}")

        episodic = self._format_episodic(retrieval.episodic_memories)
        if episodic:
            parts.append(f"[Recent Events]\n{episodic}")

        knowledge = self._format_knowledge(retrieval.knowledge_chunks)
        if knowledge:
            parts.append(f"[Your Project Context]\n{knowledge}")

        if not parts:
            return ""

        return "\n\n".join(parts)

    def _format_working_memory(self, messages: List[Dict[str, Any]]) -> str:
        if not messages:
            return ""
        return "\n".join(
            f"{m.get('role', 'user')}: {m.get('parts', [{}])[0].get('text', '')[:200]}"
            for m in messages[-5:]
        )

    def _format_summaries(self, summaries: List[str]) -> str:
        if not summaries:
            return ""
        return summaries[-1]

    def _format_semantic(self, memories: List[Dict[str, Any]]) -> str:
        if not memories:
            return ""
        lines = []
        for m in memories[:8]:
            subject = m.get("subject", "")
            value = m.get("value", "")
            confidence = m.get("confidence_score", 1.0)
            if confidence >= 0.7:
                lines.append(f"- {subject}: {value}")
            elif confidence >= 0.4:
                lines.append(f"- {subject}: {value} (possibly)")
        return "\n".join(lines) if lines else ""

    def _format_preferences(self, preferences: Dict[str, Any]) -> str:
        if not preferences:
            return ""
        lines = []
        for category, items in preferences.items():
            for key, info in items.items():
                if info["confidence"] >= 0.6:
                    lines.append(f"- {key}: {info['value']}")
        return "\n".join(lines)

    def _format_episodic(self, memories: List[Dict[str, Any]]) -> str:
        if not memories:
            return ""
        lines = []
        for m in memories[:5]:
            title = m.get("event_title", "")
            summary = m.get("event_summary", "")
            importance = m.get("importance_score", 0)
            if importance >= 0.5:
                lines.append(f"- {title}: {summary[:150]}")
        return "\n".join(lines)

    def _format_knowledge(self, chunks: List[Dict[str, Any]]) -> str:
        if not chunks:
            return ""
        return "".join(c.get("chunk_text", "") for c in chunks[:3])[:1000]
