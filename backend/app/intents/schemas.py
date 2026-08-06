"""
Intent schemas for Cortex.

Intent = what the user wants to do (high-level action), detected before the
full LLM tool-calling loop runs (Milestone 1.8 = L1 rule-based tier only;
L2/L3 are Phase 7 work — see IntentDetectionService).

⚠️ 2026-08-06: `IntentType` values are grounded in the AI tools/commands
that actually exist today (`app/ai/tools/__init__.py`'s 15 registered
tools, `app/commands/handlers/`'s 6 registered commands) — not invented
categories. No NOTE_DELETE/SCHEDULE_DELETE: no AI tool exposes delete yet
(see 06_TOOL_MIGRATION.md), so there's no natural-language path to reach
them, and a pattern for an unreachable intent would be untestable noise.
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """Known intent types, each corresponding to a real tool (and, where
    one exists, the command it wraps — see `suggested_command` on
    DetectedIntent)."""
    # Note intents
    NOTE_CREATE = "note.create"        # tool: create_note
    NOTE_UPDATE = "note.update"        # tool: update_note
    NOTE_SEARCH = "note.search"        # tool: search_notes

    # Schedule intents
    SCHEDULE_CREATE = "schedule.create"    # tool: create_schedule (reminders are schedules with a reminder config, not a separate command)
    SCHEDULE_UPDATE = "schedule.update"    # tool: update_schedule
    SCHEDULE_QUERY = "schedule.query"      # tool: get_schedules

    # Knowledge intents
    KNOWLEDGE_SEARCH = "knowledge.search"  # tool: search_knowledge
    WEB_SEARCH = "web.search"              # tool: web_search

    # Meta intents
    ACTION_REVERT = "action.revert"    # tool: revert_action — NOT a registered CommandRegistry command name;
                                        # revert goes through CommandRegistry.revert_command(action_id, ctx) directly.
    HELP = "help"

    UNKNOWN = "unknown"


class IntentConfidence(str, Enum):
    """Confidence level in intent detection."""
    HIGH = "high"      # >= 0.9 - high enough to use directly
    MEDIUM = "medium"  # 0.6-0.9 - should confirm with user
    LOW = "low"        # < 0.6 - fall back to full LLM tool-calling loop


class DetectedIntent(BaseModel):
    """Result of intent detection."""
    intent_type: IntentType
    confidence: IntentConfidence
    confidence_score: float = Field(..., ge=0.0, le=1.0)

    params: dict[str, Any] = Field(default_factory=dict, description="Extracted parameters (domain-specific)")

    detected_by: str = Field(..., description="rule or fallback")
    pattern_matched: Optional[str] = Field(None, description="Regex pattern that matched (if rule-based)")

    suggested_command: Optional[str] = Field(
        None, description="CommandRegistry command name this intent maps to, if any (note.create/note.update/"
                           "schedule.create/schedule.update only — search/query/revert/help aren't CommandRegistry "
                           "commands)."
    )
    requires_confirmation: bool = Field(default=False)


class IntentPattern(BaseModel):
    """A set of regex patterns (one language mix) mapped to an intent."""
    intent_type: IntentType
    patterns: list[str] = Field(..., description="Regex patterns, tried in order")
    param_extractors: dict[str, str] = Field(
        default_factory=dict, description="param name -> named capture group name"
    )
    confidence_score: float = Field(default=0.95, description="Confidence assigned when any pattern matches")
