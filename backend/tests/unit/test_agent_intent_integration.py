"""Unit tests for Milestone 1.8 — AgentService._detect_intent wiring.

_detect_intent is self-contained (only touches the module-level intent
service singleton, not self.db/self.user), so it's exercised directly via
AgentService.__new__() — no DB session, no live LLM call needed, same
pattern used for Milestone 1.7's context-building tests.
"""

import pytest

from app.ai.agents.agent_service import AgentService
from app.intents.intent_service import reset_intent_service


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_intent_service()
    yield
    reset_intent_service()


def _bare_agent_service() -> AgentService:
    return AgentService.__new__(AgentService)


def test_detect_intent_returns_intent_value_on_match():
    service = _bare_agent_service()
    result = service._detect_intent("remind me to call mom tomorrow")
    assert result == "schedule.create"


def test_detect_intent_returns_none_on_no_match():
    service = _bare_agent_service()
    result = service._detect_intent("just a regular chat message")
    assert result is None


def test_detect_intent_returns_none_for_empty_message():
    service = _bare_agent_service()
    assert service._detect_intent("") is None


def test_detect_intent_updates_service_stats():
    service = _bare_agent_service()
    service._detect_intent("help")

    from app.intents.intent_service import get_intent_service
    stats = get_intent_service().get_stats()
    assert stats["total_detections"] == 1
    assert stats["l1_hits"] == 1
