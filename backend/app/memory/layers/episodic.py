import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """
    Layer 5: Episodic Memory
    Ghi nhận các sự kiện quan trọng, thay đổi trạng thái.
    """

    EVENT_TYPES = [
        "project_created",
        "task_completed",
        "tool_action",
        "milestone",
        "error_encountered",
        "user_request",
        "system_change",
        "permission_granted",
        "integration_connected",
        "learning_milestone",
    ]

    def store(self, user_id: str, event_type: str, event_title: str,
              event_summary: str, importance: float,
              related_entities: List[str],
              source_conversation_ids: List[str],
              tags: List[str], db):
        existing = db.execute("""
            SELECT id, occurrence_count, last_seen_at, importance_score
            FROM episodic_memories
            WHERE user_id = :uid
              AND event_title ILIKE :title
              AND is_active = TRUE
            ORDER BY last_seen_at DESC
            LIMIT 1
        """, {"uid": user_id, "title": event_title}).fetchone()

        if existing:
            db.execute("""
                UPDATE episodic_memories
                SET occurrence_count = occurrence_count + 1,
                    last_seen_at = NOW(),
                    importance_score = LEAST(1.0, importance_score + 0.05),
                    source_conversation_ids = (
                        SELECT jsonb_agg(DISTINCT x)
                        FROM jsonb_array_elements_text(
                            source_conversation_ids || CAST(:conv_ids AS jsonb)
                        ) AS x
                    ),
                    updated_at = NOW()
                WHERE id = :id
            """, {
                "id": existing[0],
                "conv_ids": f'["{source_conversation_ids[0]}"]' if source_conversation_ids else '[]',
            })
            logger.info("Updated episodic memory %s (occ: %s)", event_title, existing[1] + 1)
        else:
            db.execute("""
                INSERT INTO episodic_memories
                    (user_id, event_type, event_title, event_summary,
                     importance_score, related_entities,
                     source_conversation_ids, tags)
                VALUES
                    (:uid, :etype, :title, :summary,
                     :importance, CAST(:entities AS jsonb),
                     CAST(:conv_ids AS jsonb), :tags)
            """, {
                "uid": user_id,
                "etype": event_type,
                "title": event_title,
                "summary": event_summary,
                "importance": importance,
                "entities": json.dumps(related_entities),
                "conv_ids": json.dumps(source_conversation_ids),
                "tags": tags,
            })
            logger.info("Stored episodic memory %s [%s]", event_title, event_type)

    def retrieve_recent(self, user_id: str, limit: int, db) -> List[Dict[str, Any]]:
        rows = db.execute("""
            SELECT * FROM episodic_memories
            WHERE user_id = :uid AND is_active = TRUE
            ORDER BY last_seen_at DESC
            LIMIT :lim
        """, {"uid": user_id, "lim": limit}).fetchall()

        return [dict(r._mapping) for r in rows]

    def retrieve_by_entity(self, user_id: str, entity: str, db) -> List[Dict[str, Any]]:
        rows = db.execute("""
            SELECT * FROM episodic_memories
            WHERE user_id = :uid
              AND related_entities ? :entity
              AND is_active = TRUE
            ORDER BY last_seen_at DESC
            LIMIT 20
        """, {"uid": user_id, "entity": entity}).fetchall()

        return [dict(r._mapping) for r in rows]
