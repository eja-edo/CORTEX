import logging
from typing import Dict, Any

from app.database import SessionLocal
from app.memory.detector import MemoryCandidateDetector
from app.memory.deduplicator import SemanticDeduplicator
from app.memory.extractor import LLMExtractor
from app.memory.layers.semantic import SemanticMemory
from app.memory.layers.preference import PreferenceMemory
from app.memory.layers.episodic import EpisodicMemory
from app.memory.layers.knowledge import KnowledgeChunk
from app.memory.layers.action import ActionMemory

logger = logging.getLogger(__name__)

detector = MemoryCandidateDetector()
deduplicator = SemanticDeduplicator()
llm_extractor = LLMExtractor()
semantic = SemanticMemory()
preference = PreferenceMemory()
episodic = EpisodicMemory()


def process_memory_extraction(job_data: Dict[str, Any]):
    """
    RQ worker entry point.
    Runs LLM extraction on detected message, stores into appropriate layer.
    """
    message_id = job_data["message_id"]
    user_id = job_data["user_id"]
    content = job_data.get("content", "")
    signals = job_data.get("signals", [])

    logger.info("Processing extraction for message %s (signals: %s)", message_id, signals)

    extracted = llm_extractor.extract(content, signals)
    if not extracted:
        logger.info("No facts extracted from message %s", message_id)
        return

    session = SessionLocal()
    try:
        for fact in extracted:
            fact_type = fact["type"]
            subject = fact["subject"]
            value = fact["value"]
            importance = float(fact.get("importance", 0.5))
            confidence = float(fact.get("confidence", 0.7))

            if fact_type in ("preference", "tech_stack"):
                dedup_result = deduplicator.deduplicate(
                    {"subject": subject, "memory_type": fact_type, "value": value,
                     "confidence_score": confidence},
                    user_id, session,
                )
                if dedup_result == "insert":
                    semantic.store(
                        user_id=user_id, workspace_id=None,
                        memory_type=fact_type, subject=subject, value=value,
                        confidence=confidence, importance=importance,
                        memory_class="LONG_TERM",
                        source_message_id=message_id, tags=[fact_type],
                        db=session,
                    )
                    preference.store(
                        user_id=user_id, category=fact_type,
                        key=subject, value=value,
                        confidence=confidence, db=session,
                    )

            elif fact_type in ("goal", "deadline", "identity", "relationship"):
                memory_class = "PERMANENT" if fact_type == "identity" else "LONG_TERM"
                if fact_type == "deadline":
                    memory_class = "TEMPORARY"

                dedup_result = deduplicator.deduplicate(
                    {"subject": subject, "memory_type": fact_type, "value": value,
                     "confidence_score": confidence},
                    user_id, session,
                )
                if dedup_result == "insert":
                    semantic.store(
                        user_id=user_id, workspace_id=None,
                        memory_type=fact_type, subject=subject, value=value,
                        confidence=confidence, importance=importance,
                        memory_class=memory_class,
                        source_message_id=message_id, tags=[fact_type],
                        db=session,
                    )

            if fact_type in ("goal", "deadline"):
                episodic.store(
                    user_id=user_id, event_type=fact_type,
                    event_title=f"{fact_type}: {subject}",
                    event_summary=value,
                    importance=importance,
                    related_entities=[subject],
                    source_conversation_ids=[message_id],
                    tags=[fact_type],
                    db=session,
                )

        session.commit()
        logger.info("Stored %s extracted facts for message %s", len(extracted), message_id)

    except Exception as e:
        session.rollback()
        logger.error("Extraction failed for message %s: %s", message_id, str(e), exc_info=True)
        raise
    finally:
        session.close()
