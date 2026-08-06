"""
IntentDetectionService: orchestrates intent detection tiers.

Phase 1 scope is L1 (rule-based) only. L2 (LLM-based classification) and L3
(learned/adaptive) are Phase 7 work — see 08_INTENT_DETECTION.md. When L1
finds no match, this service returns an UNKNOWN/LOW-confidence intent
rather than calling an LLM; the caller (AgentService) treats that as "no
signal" and falls through to the existing full tool-calling loop unchanged.
This service's only Phase-1 job beyond delegating to RuleBasedDetector is
tracking hit-rate stats, so the L1-vs-L2 tradeoff is measurable before any
L2 work is scoped.
"""

from threading import Lock

from app.intents.rule_detector import RuleBasedDetector
from app.intents.schemas import DetectedIntent, IntentConfidence, IntentType
from app.utils.logger import get_logger

logger = get_logger(__name__)


class IntentDetectionService:
    """Detects user intent and tracks L1 hit-rate stats."""

    def __init__(self):
        self._detector = RuleBasedDetector()
        self._lock = Lock()
        self._total_detections = 0
        self._l1_hits = 0
        self._l2_fallbacks = 0

    def detect(self, message: str) -> DetectedIntent:
        """Detect intent from a message. Never returns None — falls back to
        an UNKNOWN/LOW-confidence DetectedIntent so callers can treat the
        return value uniformly (unlike RuleBasedDetector.detect, which
        returns None on no match)."""
        with self._lock:
            self._total_detections += 1

        result = self._detector.detect(message)
        if result is not None:
            with self._lock:
                self._l1_hits += 1
            return result

        with self._lock:
            self._l2_fallbacks += 1

        logger.info("Intent detection: no L1 match, falling back to unknown")
        return DetectedIntent(
            intent_type=IntentType.UNKNOWN,
            confidence=IntentConfidence.LOW,
            confidence_score=0.0,
            params={},
            detected_by="fallback",
            pattern_matched=None,
            suggested_command=None,
            requires_confirmation=False,
        )

    def get_stats(self) -> dict:
        """Snapshot of detection stats since process start (in-memory only,
        not persisted — resets on restart, same as other in-process
        counters in this codebase)."""
        with self._lock:
            total = self._total_detections
            l1_hits = self._l1_hits
            l2_fallbacks = self._l2_fallbacks

        hit_rate = (l1_hits / total) if total > 0 else 0.0
        return {
            "total_detections": total,
            "l1_hits": l1_hits,
            "l2_fallbacks": l2_fallbacks,
            "l1_hit_rate": round(hit_rate, 4),
        }

    def reset_stats(self) -> None:
        with self._lock:
            self._total_detections = 0
            self._l1_hits = 0
            self._l2_fallbacks = 0


_intent_service: IntentDetectionService | None = None


def get_intent_service() -> IntentDetectionService:
    global _intent_service
    if _intent_service is None:
        _intent_service = IntentDetectionService()
    return _intent_service


def reset_intent_service() -> None:
    global _intent_service
    _intent_service = None
