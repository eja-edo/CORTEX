"""Unit tests for Milestone 1.8 — Intent schemas."""

import pytest
from pydantic import ValidationError

from app.intents.schemas import DetectedIntent, IntentConfidence, IntentPattern, IntentType


def test_intent_type_has_no_delete_variants():
    """No AI tool exposes note/schedule delete yet (06_TOOL_MIGRATION.md) —
    a pattern for an unreachable intent would be untestable noise."""
    values = {member.value for member in IntentType}
    assert "note.delete" not in values
    assert "schedule.delete" not in values


def test_detected_intent_defaults():
    intent = DetectedIntent(
        intent_type=IntentType.HELP,
        confidence=IntentConfidence.HIGH,
        confidence_score=0.95,
        detected_by="rule",
    )
    assert intent.params == {}
    assert intent.pattern_matched is None
    assert intent.suggested_command is None
    assert intent.requires_confirmation is False


def test_detected_intent_confidence_score_bounds():
    with pytest.raises(ValidationError):
        DetectedIntent(
            intent_type=IntentType.HELP,
            confidence=IntentConfidence.HIGH,
            confidence_score=1.5,
            detected_by="rule",
        )
    with pytest.raises(ValidationError):
        DetectedIntent(
            intent_type=IntentType.HELP,
            confidence=IntentConfidence.HIGH,
            confidence_score=-0.1,
            detected_by="rule",
        )


def test_intent_pattern_defaults():
    pattern = IntentPattern(intent_type=IntentType.NOTE_CREATE, patterns=[r"create a note (?P<topic>.+)"])
    assert pattern.param_extractors == {}
    assert pattern.confidence_score == 0.95
