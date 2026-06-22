import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from sqlalchemy import text

logger = logging.getLogger(__name__)


class MemoryLinker:
    """
    Rule-based memory link inference.
    Links related memories across layers based on subject overlap,
    temporal proximity, and entity co-occurrence.
    """

    LINK_THRESHOLD = 0.3
    TEMPORAL_WINDOW_DAYS = 7

    def link_new_memory(self, memory_type: str, memory_id: str,
                        subject: str, value: str, user_id: str, db):
        if memory_type == "episodic":
            self._link_episodic_to_semantic(memory_id, subject, value, user_id, db)
        else:
            self._link_semantic_to_episodic(memory_type, memory_id, subject, value, user_id, db)
            self._link_by_value_overlap(memory_type, memory_id, subject, value, user_id, db)

    def _link_episodic_to_semantic(self, episode_id: str, title: str,
                                    summary: str, user_id: str, db):
        keywords = self._extract_keywords(f"{title} {summary}")

        for keyword in keywords:
            matches = db.execute(
                text("""
                    SELECT id, memory_type, subject, value
                    FROM semantic_memories
                    WHERE user_id = :uid
                      AND is_active = TRUE
                      AND (subject ILIKE :kw OR value ILIKE :kw)
                    LIMIT 5
                """),
                {"uid": user_id, "kw": f"%{keyword}%"},
            ).fetchall()

            for row in matches:
                self._create_link(
                    source_type="episodic", source_id=episode_id,
                    target_type="semantic", target_id=str(row[0]),
                    relationship="related_to",
                    strength=0.5,
                    db=db,
                )

    def _link_semantic_to_episodic(self, mem_type: str, mem_id: str,
                                    subject: str, value: str, user_id: str, db):
        keywords = self._extract_keywords(f"{subject} {value}")

        for keyword in keywords:
            matches = db.execute(
                text("""
                    SELECT id, event_title, importance_score
                    FROM episodic_memories
                    WHERE user_id = :uid
                      AND is_active = TRUE
                      AND (event_title ILIKE :kw OR event_summary ILIKE :kw)
                    LIMIT 5
                """),
                {"uid": user_id, "kw": f"%{keyword}%"},
            ).fetchall()

            for row in matches:
                strength = min(0.9, 0.3 + float(row[2]) * 0.5)
                self._create_link(
                    source_type=mem_type, source_id=mem_id,
                    target_type="episodic", target_id=str(row[0]),
                    relationship="related_to",
                    strength=strength,
                    db=db,
                )

    def _link_by_value_overlap(self, mem_type: str, mem_id: str,
                                subject: str, value: str, user_id: str, db):
        keywords = self._extract_keywords(f"{subject} {value}")

        for keyword in keywords:
            matches = db.execute(
                text("""
                    SELECT id, memory_type, subject
                    FROM semantic_memories
                    WHERE user_id = :uid
                      AND id != :mid
                      AND is_active = TRUE
                      AND memory_type != :mtype
                      AND (subject ILIKE :kw OR value ILIKE :kw)
                    LIMIT 5
                """),
                {"uid": user_id, "mid": mem_id, "mtype": mem_type, "kw": f"%{keyword}%"},
            ).fetchall()

            for row in matches:
                self._create_link(
                    source_type=mem_type, source_id=mem_id,
                    target_type="semantic", target_id=str(row[0]),
                    relationship="related_to",
                    strength=0.4,
                    db=db,
                )

    def _create_link(self, source_type: str, source_id: str,
                     target_type: str, target_id: str,
                     relationship: str, strength: float, db):
        try:
            db.execute(
                text("""
                    INSERT INTO memory_links
                        (user_id, source_type, source_id,
                         target_type, target_id,
                         relationship, strength)
                    VALUES
                        (:uid, :stype, :sid,
                         :ttype, :tid,
                         :rel, :str)
                    ON CONFLICT (source_type, source_id, target_type, target_id, relationship)
                    DO UPDATE SET strength = LEAST(0.99, memory_links.strength + 0.05)
                """),
                {
                    "uid": self._get_user_for_memory(target_type, target_id, db),
                    "stype": source_type,
                    "sid": source_id,
                    "ttype": target_type,
                    "tid": target_id,
                    "rel": relationship,
                    "str": strength,
                },
            )
        except Exception as e:
            logger.debug("Failed to create memory link: %s", e)

    def _extract_keywords(self, text: str) -> List[str]:
        stop_words = {
            "và", "của", "có", "được", "một", "cho", "trong",
            "với", "không", "là", "này", "khi", "sẽ", "đã",
            "the", "a", "an", "in", "on", "at", "to", "for",
            "of", "with", "and", "is", "are", "was", "be",
            "this", "that", "it", "its", "my", "your", "our",
            "tôi", "mình", "bạn", "nó", "họ", "cái",
        }

        words = text.lower().split()
        keywords = []
        for w in words:
            w = w.strip(".,;:!?\"'()[]{}/\\")
            if len(w) >= 3 and w not in stop_words:
                keywords.append(w)

        return list(set(keywords[:10]))

    def _get_user_for_memory(self, memory_type: str, memory_id: str, db) -> str:
        try:
            table_map = {
                "semantic": "semantic_memories",
                "preference": "preference_memories",
                "episodic": "episodic_memories",
                "knowledge": "knowledge_chunks",
            }
            table = table_map.get(memory_type)
            if not table:
                return "unknown"

            result = db.execute(
                text(f"SELECT user_id FROM {table} WHERE id = :mid"),
                {"mid": memory_id},
            )
            row = result.fetchone()
            return str(row[0]) if row else "unknown"
        except Exception:
            return "unknown"
