import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class PreferenceMemory:
    """
    Layer 4: Preference Memory
    User preferences — categorical key-value with decay.
    """

    DECAY_FACTOR = 0.1

    def store(self, user_id: str, category: str, key: str, value: str,
              confidence: float, db):
        existing = db.execute("""
            SELECT id, confidence_score, evidence_count
            FROM preference_memories
            WHERE user_id = :uid AND category = :cat AND key = :k
        """, {"uid": user_id, "cat": category, "k": key}).fetchone()

        if existing:
            evidence_count = existing[2] + 1
            new_confidence = min(0.99, existing[1] + (0.05 * evidence_count))

            db.execute("""
                UPDATE preference_memories
                SET value = :value,
                    confidence_score = :conf,
                    evidence_count = :ev_count,
                    last_evidenced_at = NOW(),
                    updated_at = NOW()
                WHERE id = :id
            """, {
                "value": value,
                "conf": new_confidence,
                "ev_count": evidence_count,
                "id": existing[0],
            })
            logger.info("Updated preference %s/%s (evidence: %s)", category, key, evidence_count)
        else:
            db.execute("""
                INSERT INTO preference_memories
                    (user_id, category, key, value, confidence_score,
                     evidence_count, last_evidenced_at)
                VALUES
                    (:uid, :cat, :k, :value, :conf,
                     1, NOW())
            """, {
                "uid": user_id,
                "cat": category,
                "k": key,
                "value": value,
                "conf": confidence,
            })
            logger.info("Stored preference %s/%s = %s", category, key, value)

    def get_all(self, user_id: str, db) -> Dict[str, Any]:
        rows = db.execute("""
            SELECT category, key, value, confidence_score
            FROM preference_memories
            WHERE user_id = :uid AND is_active = TRUE
            ORDER BY confidence_score DESC, updated_at DESC
        """, {"uid": user_id}).fetchall()

        result: Dict[str, Any] = {}
        for row in rows:
            cat = row[0]
            if cat not in result:
                result[cat] = {}
            result[cat][row[1]] = {
                "value": row[2],
                "confidence": row[3],
            }
        return result

    def get_by_category(self, user_id: str, category: str, db) -> Dict[str, Any]:
        rows = db.execute("""
            SELECT key, value, confidence_score
            FROM preference_memories
            WHERE user_id = :uid AND category = :cat AND is_active = TRUE
            ORDER BY confidence_score DESC
        """, {"uid": user_id, "cat": category}).fetchall()

        return {r[0]: {"value": r[1], "confidence": r[2]} for r in rows}

    def apply_decay(self, db):
        rows = db.execute("""
            UPDATE preference_memories
            SET confidence_score = confidence_score * (1.0 - :decay)
            WHERE is_active = TRUE
              AND last_evidenced_at < NOW() - INTERVAL '30 days'
        """, {"decay": self.DECAY_FACTOR})
        if rows.rowcount:
            logger.info("Decayed confidence for %s preferences", rows.rowcount)
