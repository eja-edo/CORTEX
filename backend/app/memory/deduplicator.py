import logging

logger = logging.getLogger(__name__)


class SemanticDeduplicator:
    """
    Xử lý conflict khi extract memory mới trùng với memory cũ.
    """

    SIMILARITY_THRESHOLD = 0.85

    def deduplicate(self, new_memory: dict, user_id: str, db) -> str:
        """
        Returns: 'insert' | 'update' | 'skip'
        """
        existing = db.execute("""
            SELECT id, value, confidence_score, importance_score
            FROM semantic_memories
            WHERE user_id = :user_id
              AND subject = :subject
              AND memory_type = :memory_type
              AND is_active = TRUE
        """, {
            "user_id": user_id,
            "subject": new_memory["subject"],
            "memory_type": new_memory["memory_type"],
        }).fetchall()

        if not existing:
            return "insert"

        for row in existing:
            if self._is_same_fact(row.value, new_memory["value"]):
                if new_memory["confidence_score"] > row.confidence_score:
                    self._update_confidence(row.id, new_memory["confidence_score"], db)
                return "skip"

            if self._is_contradicting(row.value, new_memory["value"]):
                if new_memory["confidence_score"] > row.confidence_score + 0.1:
                    self._deactivate(row.id, db)
                    return "insert"
                else:
                    self._reduce_confidence(row.id, db)
                    return "skip"

        return "insert"

    def _is_same_fact(self, value_a: str, value_b: str) -> bool:
        a = value_a.lower().strip()
        b = value_b.lower().strip()
        if a == b:
            return True
        if a in b or b in a:
            return True
        return False

    def _is_contradicting(self, value_a: str, value_b: str) -> bool:
        return True

    def _update_confidence(self, memory_id, new_confidence: float, db):
        db.execute("""
            UPDATE semantic_memories
            SET confidence_score = :conf, updated_at = NOW()
            WHERE id = :id
        """, {"conf": new_confidence, "id": memory_id})

    def _deactivate(self, memory_id, db):
        db.execute("""
            UPDATE semantic_memories
            SET is_active = FALSE, updated_at = NOW()
            WHERE id = :id
        """, {"id": memory_id})

    def _reduce_confidence(self, memory_id, db):
        db.execute("""
            UPDATE semantic_memories
            SET confidence_score = confidence_score * 0.7, updated_at = NOW()
            WHERE id = :id
        """, {"id": memory_id})
