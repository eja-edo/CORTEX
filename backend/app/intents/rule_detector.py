"""
Rule-based intent detector (L1).

Fast, deterministic, no LLM cost. Only matches clear, unambiguous phrasings
at the START of the message (re.match, not re.search) — this is meant to be
conservative (few false positives), not exhaustive; anything it misses falls
through to the existing full LLM tool-calling loop unchanged (L2, Phase 1
scope: no behavior change, just a stats signal — see IntentDetectionService).

⚠️ 2026-08-06: patterns cover BOTH English and Vietnamese phrasings. The
existing tool-facing strings in this codebase (revert_action.py's messages,
etc.) are Vietnamese, so an English-only L1 layer would rarely fire on real
traffic and the whole milestone would be dead weight. Vietnamese patterns
here are intentionally simple/permissive (no full morphological parsing) —
matching common command phrasings, not general Vietnamese NLP.
"""

import re

from app.intents.schemas import DetectedIntent, IntentConfidence, IntentPattern, IntentType
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Maps IntentType -> CommandRegistry command name, for the ones that
# actually go through CommandRegistry.execute(). Search/query/revert/help
# aren't CommandRegistry commands (search/query are read-only tools; revert
# has its own CommandRegistry.revert_command() entrypoint) — see
# app/intents/schemas.py's IntentType docstring.
_INTENT_TO_COMMAND = {
    IntentType.NOTE_CREATE: "note.create",
    IntentType.NOTE_UPDATE: "note.update",
    IntentType.SCHEDULE_CREATE: "schedule.create",
    IntentType.SCHEDULE_UPDATE: "schedule.update",
}


class RuleBasedDetector:
    """L1 intent detector: regex pattern matching against the start of the message."""

    def __init__(self):
        self.patterns = self._load_patterns()

    def _load_patterns(self) -> list[IntentPattern]:
        return [
            # --- Meta: help ---
            IntentPattern(
                intent_type=IntentType.HELP,
                patterns=[
                    r"help\b",
                    r"what can you do\??",
                    r"how do i use this\??",
                    r"trợ giúp",
                    r"giúp (?:tôi|đỡ)",
                    r"bạn (?:làm được gì|có thể làm gì)",
                ],
                confidence_score=0.95,
            ),

            # --- Meta: revert ---
            IntentPattern(
                intent_type=IntentType.ACTION_REVERT,
                patterns=[
                    r"(?:undo|revert|cancel) (?:that|it|the last (?:action|change))",
                    r"go back$",
                    r"i changed my mind",
                    r"(?:hoàn tác|huỷ|hủy)(?: (?:đó|cái đó|hành động (?:vừa rồi|vừa xong)))?$",
                ],
                confidence_score=0.9,
            ),

            # --- Note: create ---
            IntentPattern(
                intent_type=IntentType.NOTE_CREATE,
                patterns=[
                    r"(?:create|make|write|take|jot down) (?:a |the )?note(?:s)?\s*(?:about|on|for)?\s*(?P<topic>.+)",
                    r"note to self:?\s*(?P<topic>.+)",
                    r"(?:tạo|viết|ghi)(?: cho tôi)? (?:một |1 )?(?:ghi chú|note)\s*(?:về|cho)?\s*(?P<topic>.+)",
                    r"ghi chú lại:?\s*(?P<topic>.+)",
                ],
                param_extractors={"topic": "topic"},
                confidence_score=0.9,
            ),

            # --- Note: search ---
            IntentPattern(
                intent_type=IntentType.NOTE_SEARCH,
                patterns=[
                    r"(?:find|search|look for) (?:my )?notes?\s*(?:about|on|for)?\s*(?P<query>.+)",
                    r"do i have (?:any )?notes?\s*(?:about|on)?\s*(?P<query>.+)",
                    r"where did i write (?:about )?(?P<query>.+)",
                    r"tìm(?: kiếm)? (?:ghi chú|note)\s*(?:về|có)?\s*(?P<query>.+)",
                    r"(?:tôi )?có (?:ghi chú|note) (?:nào )?(?:về )?(?P<query>.+) không\??",
                ],
                param_extractors={"query": "query"},
                confidence_score=0.9,
            ),

            # --- Schedule: create (includes reminder phrasing) ---
            IntentPattern(
                intent_type=IntentType.SCHEDULE_CREATE,
                patterns=[
                    # With an explicit preposition before the time ("at 3pm", "on Friday")...
                    r"remind me (?:to )?(?P<task>.+?) (?:at|on|in) (?P<time>.+)",
                    # ...or a bare relative-day word with no preposition ("... tomorrow").
                    r"remind me (?:to )?(?P<task>.+?) (?P<time>tomorrow|today|tonight|next week|this week)$",
                    r"set (?:a )?reminder (?:to )?(?P<task>.+?) (?:for|at|on) (?P<time>.+)",
                    r"(?:schedule|create|add|book) (?:a |an )?(?:meeting|event|appointment)\s+(?P<rest>.+)",
                    r"nhắc (?:tôi )?(?P<task>.+?) (?:lúc|vào) (?P<time>.+)",
                    r"(?:tạo|đặt|thêm) (?:lịch|cuộc hẹn|sự kiện)\s+(?P<rest>.+)",
                ],
                param_extractors={"task": "task", "time": "time", "rest": "rest"},
                confidence_score=0.9,
            ),

            # --- Schedule: query ---
            IntentPattern(
                intent_type=IntentType.SCHEDULE_QUERY,
                patterns=[
                    r"what(?:'s| is) on my (?:schedule|calendar)\s*(?P<timeframe>today|tomorrow|this week)?",
                    r"(?:show|list) my (?:events|meetings|appointments|schedule)\s*(?:for )?(?P<timeframe>.+)?",
                    r"do i have (?:any )?(?:meetings|events|appointments)\s*(?P<timeframe>today|tomorrow)?",
                    r"lịch(?: của tôi)?(?: hôm nay| ngày mai| tuần này)?(?: là gì| có gì)?\??$",
                    r"(?:tôi )?có (?:lịch|cuộc hẹn|sự kiện) (?:gì )?(?P<timeframe>hôm nay|ngày mai|tuần này)?\s*không\??",
                ],
                param_extractors={"timeframe": "timeframe"},
                confidence_score=0.9,
            ),

            # --- Knowledge search ---
            IntentPattern(
                intent_type=IntentType.KNOWLEDGE_SEARCH,
                patterns=[
                    r"search (?:my )?knowledge(?: base)?\s*(?:for)?\s*(?P<query>.+)",
                    r"tìm (?:trong )?(?:kiến thức|tài liệu) (?:của tôi )?(?:về )?(?P<query>.+)",
                ],
                param_extractors={"query": "query"},
                confidence_score=0.85,
            ),

            # --- Web search (broad catch-all, kept last: least specific) ---
            IntentPattern(
                intent_type=IntentType.WEB_SEARCH,
                patterns=[
                    r"(?:search|google|look up) (?:for )?(?P<query>.+)",
                    r"what is (?P<query>.+)\??$",
                    r"who is (?P<query>.+)\??$",
                    r"tìm kiếm (?P<query>.+)",
                    r"tra cứu (?P<query>.+)",
                ],
                param_extractors={"query": "query"},
                confidence_score=0.8,
            ),
        ]

    def detect(self, message: str) -> DetectedIntent | None:
        """Detect intent from a message. Returns None if no pattern matches
        (caller falls back to the unchanged full tool-calling loop)."""
        message_stripped = message.strip()
        message_lower = message_stripped.lower()

        for pattern_def in self.patterns:
            for pattern in pattern_def.patterns:
                match = re.match(pattern, message_lower, re.IGNORECASE | re.UNICODE)
                if not match:
                    continue

                params = {}
                for param_name, group_name in pattern_def.param_extractors.items():
                    try:
                        value = match.group(group_name)
                    except IndexError:
                        # This specific pattern doesn't define that named
                        # group (param_extractors lists the union of groups
                        # across all patterns for this intent, not every
                        # pattern's own groups).
                        continue
                    if value:
                        params[param_name] = value.strip()

                score = pattern_def.confidence_score
                if score >= 0.9:
                    confidence = IntentConfidence.HIGH
                elif score >= 0.6:
                    confidence = IntentConfidence.MEDIUM
                else:
                    confidence = IntentConfidence.LOW

                detected = DetectedIntent(
                    intent_type=pattern_def.intent_type,
                    confidence=confidence,
                    confidence_score=score,
                    params=params,
                    detected_by="rule",
                    pattern_matched=pattern,
                    suggested_command=_INTENT_TO_COMMAND.get(pattern_def.intent_type),
                    requires_confirmation=(confidence != IntentConfidence.HIGH),
                )

                logger.info(
                    f"Intent detected (rule-based): {detected.intent_type.value}",
                    extra={
                        "intent": detected.intent_type.value,
                        "confidence": detected.confidence_score,
                        "params": params,
                    },
                )
                return detected

        return None
