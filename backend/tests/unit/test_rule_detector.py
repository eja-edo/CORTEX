"""Unit tests for Milestone 1.8 — RuleBasedDetector (L1 intent detection).

Cases mirror real user phrasings (EN + VI) for every IntentType the detector
supports, plus negative/ambiguous cases that must NOT match (so they fall
through to the unchanged L2 tool-calling loop).
"""

import pytest

from app.intents.rule_detector import RuleBasedDetector
from app.intents.schemas import IntentConfidence, IntentType


@pytest.fixture(scope="module")
def detector():
    return RuleBasedDetector()


# --- HELP ---

@pytest.mark.parametrize("message", [
    "help",
    "Help me",
    "what can you do?",
    "how do i use this?",
    "trợ giúp",
    "giúp tôi",
    "giúp đỡ",
    "bạn làm được gì",
    "bạn có thể làm gì?",
])
def test_help(detector, message):
    result = detector.detect(message)
    assert result is not None
    assert result.intent_type == IntentType.HELP


# --- ACTION_REVERT ---

@pytest.mark.parametrize("message", [
    "undo that",
    "revert it",
    "cancel the last action",
    "cancel the last change",
    "go back",
    "i changed my mind",
    "hoàn tác",
    "huỷ đó",
    "hủy cái đó",
    "hoàn tác hành động vừa rồi",
])
def test_action_revert(detector, message):
    result = detector.detect(message)
    assert result is not None
    assert result.intent_type == IntentType.ACTION_REVERT
    assert result.suggested_command is None  # revert bypasses CommandRegistry.execute()


# --- NOTE_CREATE ---

@pytest.mark.parametrize("message,expected_topic", [
    ("create a note about the meeting", "the meeting"),
    ("make a note on project ideas", "project ideas"),
    ("write a note for tomorrow's tasks", "tomorrow's tasks"),
    ("take note buy milk", "buy milk"),
    ("jot down a note remember to call mom", "remember to call mom"),
    ("note to self: renew passport", "renew passport"),
    ("tạo ghi chú về dự án mới", "dự án mới"),
    ("viết cho tôi 1 ghi chú về cuộc họp", "cuộc họp"),
    ("ghi chú lại: mua sữa", "mua sữa"),
])
def test_note_create(detector, message, expected_topic):
    result = detector.detect(message)
    assert result is not None
    assert result.intent_type == IntentType.NOTE_CREATE
    assert result.suggested_command == "note.create"
    assert result.params.get("topic") == expected_topic


# --- NOTE_SEARCH ---

@pytest.mark.parametrize("message", [
    "find my notes about python",
    "search notes on machine learning",
    "look for notes about the budget",
    "do i have any notes about taxes",
    "where did i write about the api design",
    "tìm ghi chú về python",
    "tìm kiếm note có machine learning",
    "tôi có ghi chú nào về taxes không?",
])
def test_note_search(detector, message):
    result = detector.detect(message)
    assert result is not None
    assert result.intent_type == IntentType.NOTE_SEARCH
    assert result.suggested_command is None  # search isn't a CommandRegistry command


# --- SCHEDULE_CREATE (incl. reminder phrasing) ---

@pytest.mark.parametrize("message", [
    "remind me to buy milk at 5pm",
    "remind me to call mom tomorrow",       # bare relative-day, no preposition (bug #1 fix)
    "remind me to submit the report today",
    "set a reminder to water the plants at 8am",
    "schedule a meeting with the team next monday",
    "create an event for the birthday party",
    "book a meeting room for friday",
    "nhắc tôi mua sữa lúc 5 giờ chiều",
    "nhắc tôi gọi điện vào ngày mai",
    "tạo lịch họp nhóm dự án",
    "đặt cuộc hẹn với bác sĩ",
])
def test_schedule_create(detector, message):
    result = detector.detect(message)
    assert result is not None
    assert result.intent_type == IntentType.SCHEDULE_CREATE
    assert result.suggested_command == "schedule.create"


# --- SCHEDULE_QUERY ---

@pytest.mark.parametrize("message", [
    "what's on my schedule today",
    "what is on my schedule today",        # expanded contraction (bug #2 fix)
    "what's on my calendar tomorrow",
    "show my events for this week",
    "list my meetings",
    "do i have any meetings today",
    "do i have any appointments tomorrow",
    "lịch của tôi hôm nay có gì?",          # separate timeframe + suffix segments (bug #3 fix)
    "lịch hôm nay có gì",
    "lịch của tôi",
    "tôi có lịch gì hôm nay không?",
    "tôi có cuộc hẹn gì ngày mai không",
])
def test_schedule_query(detector, message):
    result = detector.detect(message)
    assert result is not None
    assert result.intent_type == IntentType.SCHEDULE_QUERY
    assert result.suggested_command is None  # query isn't a CommandRegistry command


# --- KNOWLEDGE_SEARCH ---

@pytest.mark.parametrize("message", [
    "search my knowledge base for kubernetes",
    "search knowledge for react hooks",
    "tìm trong kiến thức của tôi về docker",
    "tìm tài liệu về golang",
])
def test_knowledge_search(detector, message):
    result = detector.detect(message)
    assert result is not None
    assert result.intent_type == IntentType.KNOWLEDGE_SEARCH


# --- WEB_SEARCH (broadest catch-all, tried last) ---

@pytest.mark.parametrize("message", [
    "search for the weather in hanoi",
    "google the capital of france",
    "look up python asyncio docs",
    "who is the president of vietnam",
    "tìm kiếm giá vàng hôm nay",
    "tra cứu mã bưu điện",
])
def test_web_search(detector, message):
    result = detector.detect(message)
    assert result is not None
    assert result.intent_type == IntentType.WEB_SEARCH


# --- Negative cases: must NOT match anything (fall through to L2) ---

@pytest.mark.parametrize("message", [
    "hello",
    "thanks!",
    "ok",
    "that's interesting, tell me more",
    "why is the sky blue",
    "xin chào",
    "cảm ơn bạn",
    "",
    "   ",
])
def test_no_match(detector, message):
    assert detector.detect(message) is None


# --- Confidence / requires_confirmation wiring ---

def test_high_confidence_does_not_require_confirmation(detector):
    result = detector.detect("help")
    assert result.confidence == IntentConfidence.HIGH
    assert result.requires_confirmation is False


def test_medium_confidence_requires_confirmation(detector):
    result = detector.detect("search my knowledge base for kubernetes")
    assert result.confidence == IntentConfidence.MEDIUM
    assert result.requires_confirmation is True
