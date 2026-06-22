import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SemanticMemory:
    """
    Layer 3: Semantic (Factual) Memory
    Chứa các fact về user, entity, context.
    """

    CLASSES = {
        "PERMANENT": None,
        "LONG_TERM": timedelta(days=180),
        "TEMPORARY": timedelta(days=14),
    }

    def extract(self, message: str, user_id: str, signals: List[str],
                db) -> Optional[Dict[str, Any]]:
        return None

    def store(self, user_id: str, workspace_id: Optional[str],
              memory_type: str, subject: str, value: str,
              confidence: float, importance: float, memory_class: str,
              source_message_id: Optional[str], tags: List[str],
              db):
        expires_at = None
        if memory_class in self.CLASSES and self.CLASSES[memory_class] is not None:
            expires_at = datetime.utcnow() + self.CLASSES[memory_class]

        db.execute("""
            INSERT INTO semantic_memories
                (user_id, workspace_id, memory_type, subject, value,
                 confidence_score, importance_score, memory_class,
                 source_message_id, expires_at, tags)
            VALUES
                (:uid, :wid, :mtype, :subject, :value,
                 :conf, :importance, :memclass,
                 :source_msg, :expires, :tags)
        """, {
            "uid": user_id,
            "wid": workspace_id,
            "mtype": memory_type,
            "subject": subject,
            "value": value,
            "conf": confidence,
            "importance": importance,
            "memclass": memory_class,
            "source_msg": source_message_id,
            "expires": expires_at,
            "tags": tags,
        })
        logger.info("Stored semantic memory [%s] %s = %s", memory_type, subject, value)

    def retrieve_by_subject(self, user_id: str, subject: str, db) -> List[Dict[str, Any]]:
        rows = db.execute("""
            SELECT * FROM semantic_memories
            WHERE user_id = :uid
              AND subject ILIKE :subject
              AND is_active = TRUE
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY importance_score DESC, confidence_score DESC
            LIMIT 10
        """, {"uid": user_id, "subject": f"%{subject}%"}).fetchall()

        return [dict(r._mapping) for r in rows]

    def expire(self, db):
        deleted = db.execute("""
            UPDATE semantic_memories
            SET is_active = FALSE
            WHERE expires_at IS NOT NULL
              AND expires_at < NOW()
              AND is_active = TRUE
        """).rowcount
        if deleted:
            logger.info("Expired %s semantic memories", deleted)
