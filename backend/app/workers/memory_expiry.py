import logging
from datetime import datetime

from app.database import SessionLocal
from app.memory.layers.semantic import SemanticMemory
from app.memory.layers.preference import PreferenceMemory
from app.memory.layers.action import ActionMemory

logger = logging.getLogger(__name__)


def run_memory_expiry():
    """
    Cron job: cleanup expired memory records.
    Should be called periodically (e.g. every hour via cron or scheduler).
    """
    logger.info("Starting memory expiry cleanup")
    session = SessionLocal()
    try:
        semantic = SemanticMemory()
        preference = PreferenceMemory()
        action = ActionMemory()

        semantic.expire(session)
        preference.apply_decay(session)
        action.expire_old(session)

        session.commit()
        logger.info("Memory expiry cleanup completed")
    except Exception as e:
        session.rollback()
        logger.error("Memory expiry cleanup failed: %s", e, exc_info=True)
        raise
    finally:
        session.close()
