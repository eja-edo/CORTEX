"""Unit tests for Milestone 1.8 — IntentDetectionService (L1 orchestration + stats)."""

import pytest

from app.intents.intent_service import IntentDetectionService, get_intent_service, reset_intent_service
from app.intents.schemas import IntentConfidence, IntentType


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_intent_service()
    yield
    reset_intent_service()


def test_detect_returns_matched_intent():
    service = IntentDetectionService()
    result = service.detect("help")
    assert result.intent_type == IntentType.HELP
    assert result.detected_by == "rule"


def test_detect_falls_back_to_unknown_on_no_match():
    service = IntentDetectionService()
    result = service.detect("this is just a normal chat message, nothing special")
    assert result.intent_type == IntentType.UNKNOWN
    assert result.confidence == IntentConfidence.LOW
    assert result.confidence_score == 0.0
    assert result.detected_by == "fallback"
    assert result.requires_confirmation is False


def test_detect_never_returns_none():
    service = IntentDetectionService()
    assert service.detect("") is not None
    assert service.detect("gibberish xyzzy plugh") is not None


def test_stats_track_l1_hits_and_fallbacks():
    service = IntentDetectionService()
    service.detect("help")                # L1 hit
    service.detect("what can you do?")     # L1 hit
    service.detect("random unmatched text")  # fallback

    stats = service.get_stats()
    assert stats["total_detections"] == 3
    assert stats["l1_hits"] == 2
    assert stats["l2_fallbacks"] == 1
    assert stats["l1_hit_rate"] == pytest.approx(2 / 3, rel=1e-3)


def test_stats_empty_before_any_detection():
    service = IntentDetectionService()
    stats = service.get_stats()
    assert stats == {
        "total_detections": 0,
        "l1_hits": 0,
        "l2_fallbacks": 0,
        "l1_hit_rate": 0.0,
    }


def test_reset_stats_clears_counters():
    service = IntentDetectionService()
    service.detect("help")
    service.reset_stats()
    stats = service.get_stats()
    assert stats["total_detections"] == 0
    assert stats["l1_hits"] == 0
    assert stats["l2_fallbacks"] == 0


def test_get_intent_service_returns_singleton():
    a = get_intent_service()
    b = get_intent_service()
    assert a is b


def test_reset_intent_service_creates_fresh_instance():
    a = get_intent_service()
    a.detect("help")
    reset_intent_service()
    b = get_intent_service()
    assert a is not b
    assert b.get_stats()["total_detections"] == 0
