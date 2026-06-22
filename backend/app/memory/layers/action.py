import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ActionMemory:
    """
    Layer 7: Action History
    Two-layer:
      - Redis: 24h hot (undo support)
      - PostgreSQL: 90d audit trail
    """

    PG_EXPIRY_DAYS = 90

    def store(self, user_id: str, conversation_id: str, tool_name: str,
              action_type: str, action_id: str,
              before_state: Optional[Dict[str, Any]],
              after_state: Optional[Dict[str, Any]], db):
        expires_at = datetime.utcnow() + timedelta(days=self.PG_EXPIRY_DAYS)

        db.execute("""
            INSERT INTO action_history
                (user_id, conversation_id, tool_name, action_type,
                 action_id, before_state, after_state, expires_at)
            VALUES
                (:uid, :conv_id, :tool, :atype,
                 :action_id, CAST(:before AS jsonb), CAST(:after AS jsonb), :expires)
        """, {
            "uid": user_id,
            "conv_id": conversation_id,
            "tool": tool_name,
            "atype": action_type,
            "action_id": action_id,
            "before": json.dumps(before_state) if before_state else "null",
            "after": json.dumps(after_state) if after_state else "null",
            "expires": expires_at,
        })
        logger.info("Stored action %s (%s/%s) in PG", action_id, tool_name, action_type)

    def get_unreverted(self, user_id: str, tool_name: str, db) -> List[Dict[str, Any]]:
        rows = db.execute("""
            SELECT * FROM action_history
            WHERE user_id = :uid
              AND tool_name = :tool
              AND is_reverted = FALSE
            ORDER BY created_at DESC
            LIMIT 10
        """, {"uid": user_id, "tool": tool_name}).fetchall()

        return [dict(r._mapping) for r in rows]

    def mark_reverted(self, action_id: str, db):
        db.execute("""
            UPDATE action_history
            SET is_reverted = TRUE, reverted_at = NOW()
            WHERE action_id = :aid
        """, {"aid": action_id})
        logger.info("Marked action %s as reverted", action_id)

    def expire_old(self, db):
        deleted = db.execute("""
            DELETE FROM action_history
            WHERE expires_at < NOW()
        """).rowcount
        if deleted:
            logger.info("Deleted %s expired action records", deleted)
