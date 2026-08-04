# Milestone 1.8: Intent Detection Layer

**Timeline:** 3-4 ngày  
**Dependencies:** 1.7 (Context Service - để cung cấp context cho intent detection)  
**Effort:** Medium  

---

## 🎯 Mục tiêu

Bắt đầu tách "hiểu ý định" ra khỏi "thực thi", chuẩn bị cho AI Routing (L0–L3) ở Phase 7.

**Hiện trạng:**
- Mọi request đều đi qua LLM tool-calling loop (expensive, slow)
- Không có phân loại intent trước khi xử lý
- Intent rõ ràng (như "remind me...") vẫn phải qua full LLM reasoning

**Mục tiêu:**
- **L1 (Rule-based):** Classify intent rõ ràng bằng regex/pattern matching
- **L2 (LLM fallback):** Các intent phức tạp vẫn dùng LLM hiện tại
- Tách module riêng để dễ mở rộng sang L0 (deterministic) và L3 (reasoning) sau này
- Đo được % requests được xử lý bằng L1 (không cần LLM)

---

## 📋 Tasks

### Task 1.8.1: Define Intent Schema

**Output:** `backend/app/intents/schemas.py`

```python
"""
Intent schemas for Cortex.

Intent = what user wants to do (high-level action).
"""

from pydantic import BaseModel, Field
from typing import Optional, Any
from enum import Enum


class IntentType(str, Enum):
    """
    Known intent types.
    
    These map to commands or tool sequences.
    """
    # Note intents
    NOTE_CREATE = "note.create"
    NOTE_UPDATE = "note.update"
    NOTE_SEARCH = "note.search"
    NOTE_DELETE = "note.delete"
    
    # Schedule intents
    SCHEDULE_CREATE = "schedule.create"
    SCHEDULE_UPDATE = "schedule.update"
    SCHEDULE_QUERY = "schedule.query"
    REMINDER_CREATE = "reminder.create"
    
    # Knowledge intents
    KNOWLEDGE_SEARCH = "knowledge.search"
    WEB_SEARCH = "web.search"
    
    # Meta intents
    ACTION_REVERT = "action.revert"
    HELP = "help"
    
    # Unknown
    UNKNOWN = "unknown"


class IntentConfidence(str, Enum):
    """Confidence level in intent detection."""
    HIGH = "high"      # > 0.9 - Can execute directly
    MEDIUM = "medium"  # 0.6-0.9 - Should confirm with user
    LOW = "low"        # < 0.6 - Fallback to LLM


class DetectedIntent(BaseModel):
    """
    Result of intent detection.
    
    Contains:
    - Intent type
    - Confidence score
    - Extracted parameters (if any)
    - Detection method (rule, pattern, LLM)
    """
    intent_type: IntentType
    confidence: IntentConfidence
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    
    # Extracted parameters (domain-specific)
    params: dict[str, Any] = Field(default_factory=dict)
    
    # Metadata
    detected_by: str = Field(..., description="rule, pattern, llm")
    pattern_matched: Optional[str] = Field(None, description="Regex pattern that matched (if rule-based)")
    
    # Suggestions
    suggested_command: Optional[str] = Field(None, description="Command to execute")
    requires_confirmation: bool = Field(default=False)


class IntentPattern(BaseModel):
    """
    Pattern for rule-based intent detection.
    
    Maps regex patterns to intents.
    """
    intent_type: IntentType
    patterns: list[str] = Field(..., description="Regex patterns")
    param_extractors: dict[str, str] = Field(
        default_factory=dict,
        description="Named capture groups to extract params"
    )
    confidence_score: float = Field(default=0.95, description="Confidence if pattern matches")
    
    class Config:
        json_schema_extra = {
            "example": {
                "intent_type": "reminder.create",
                "patterns": [
                    r"remind me (?:to )?(?P<task>.+?) (?:at|on) (?P<time>.+)",
                    r"set (?:a )?reminder (?:to )?(?P<task>.+?) (?:for )?(?P<time>.+)"
                ],
                "param_extractors": {
                    "task": "task",
                    "time": "time"
                },
                "confidence_score": 0.95
            }
        }
```

**Checklist:**
- [ ] IntentType enum with common intents
- [ ] IntentConfidence enum (HIGH/MEDIUM/LOW)
- [ ] DetectedIntent model
- [ ] IntentPattern model for rule-based detection
- [ ] Documentation with examples

---

### Task 1.8.2: Implement Rule-Based Intent Detector (L1)

**Output:** `backend/app/intents/rule_detector.py`

```python
"""
Rule-based intent detector (L1).

Uses regex patterns to detect clear intents without LLM.
Fast, deterministic, no cost.
"""

import re
from typing import Optional
from app.intents.schemas import (
    IntentType,
    IntentConfidence,
    DetectedIntent,
    IntentPattern
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RuleBasedDetector:
    """
    L1 Intent Detector: Rule-based pattern matching.
    
    For clear, unambiguous intents like:
    - "remind me to X at Y"
    - "create a note about X"
    - "what's on my schedule today"
    """
    
    def __init__(self):
        self.patterns = self._load_patterns()
    
    def _load_patterns(self) -> list[IntentPattern]:
        """
        Load intent patterns.
        
        TODO: Load from config file or database for easy updates.
        """
        return [
            # Reminder patterns
            IntentPattern(
                intent_type=IntentType.REMINDER_CREATE,
                patterns=[
                    r"remind me (?:to )?(?P<task>.+?) (?:at|on|in) (?P<time>.+)",
                    r"set (?:a )?reminder (?:to )?(?P<task>.+?) (?:for|at|on) (?P<time>.+)",
                    r"don'?t let me forget (?:to )?(?P<task>.+?) (?:at|on) (?P<time>.+)"
                ],
                param_extractors={"task": "task", "time": "time"},
                confidence_score=0.95
            ),
            
            # Note creation patterns
            IntentPattern(
                intent_type=IntentType.NOTE_CREATE,
                patterns=[
                    r"(?:create|make|write) (?:a )?note (?:about|on|for) (?P<topic>.+)",
                    r"(?:take|jot down) (?:a )?note:? (?P<content>.+)",
                    r"note to self:? (?P<content>.+)"
                ],
                param_extractors={"topic": "topic", "content": "content"},
                confidence_score=0.9
            ),
            
            # Schedule query patterns
            IntentPattern(
                intent_type=IntentType.SCHEDULE_QUERY,
                patterns=[
                    r"what'?s on my (?:schedule|calendar) (?P<timeframe>today|tomorrow|this week)?",
                    r"(?:show|list|what are) my (?:events|meetings|appointments) (?:for )?(?P<timeframe>.+)?",
                    r"do I have (?:any )(?:meetings|events|appointments) (?P<timeframe>today|tomorrow)?"
                ],
                param_extractors={"timeframe": "timeframe"},
                confidence_score=0.95
            ),
            
            # Schedule creation patterns
            IntentPattern(
                intent_type=IntentType.SCHEDULE_CREATE,
                patterns=[
                    r"(?:schedule|create|add) (?:a )?(?:meeting|event|appointment) (?:for|at|on) (?P<time>.+?) (?:called|titled|about) (?P<title>.+)",
                    r"(?:book|block) (?:time )?(?:for|at) (?P<time>.+?) (?:for|to) (?P<title>.+)"
                ],
                param_extractors={"time": "time", "title": "title"},
                confidence_score=0.9
            ),
            
            # Note search patterns
            IntentPattern(
                intent_type=IntentType.NOTE_SEARCH,
                patterns=[
                    r"(?:find|search|look for) (?:my )?notes? (?:about|on|for) (?P<query>.+)",
                    r"do I have (?:any )?notes? (?:about|on) (?P<query>.+)",
                    r"where did I write (?:about )?(?P<query>.+)"
                ],
                param_extractors={"query": "query"},
                confidence_score=0.9
            ),
            
            # Web search patterns
            IntentPattern(
                intent_type=IntentType.WEB_SEARCH,
                patterns=[
                    r"(?:search|google|look up) (?:for )?(?P<query>.+)",
                    r"what is (?P<query>.+)\??",
                    r"who is (?P<query>.+)\??",
                    r"how (?:do I|to) (?P<query>.+)\??"
                ],
                param_extractors={"query": "query"},
                confidence_score=0.85
            ),
            
            # Revert patterns
            IntentPattern(
                intent_type=IntentType.ACTION_REVERT,
                patterns=[
                    r"(?:undo|revert|cancel) (?:that|the last (?:action|change))",
                    r"go back",
                    r"I changed my mind"
                ],
                param_extractors={},
                confidence_score=0.9
            ),
            
            # Help patterns
            IntentPattern(
                intent_type=IntentType.HELP,
                patterns=[
                    r"(?:help|what can you do|how do I use this)",
                    r"show me (?:the )?(?:commands|features|capabilities)"
                ],
                param_extractors={},
                confidence_score=0.95
            )
        ]
    
    def detect(self, message: str) -> Optional[DetectedIntent]:
        """
        Detect intent from message using rule-based patterns.
        
        Args:
            message: User message
        
        Returns:
            DetectedIntent if pattern matches, None otherwise
        """
        message_lower = message.lower().strip()
        
        for pattern_def in self.patterns:
            for pattern in pattern_def.patterns:
                match = re.match(pattern, message_lower, re.IGNORECASE)
                
                if match:
                    # Extract parameters
                    params = {}
                    for param_name, group_name in pattern_def.param_extractors.items():
                        try:
                            params[param_name] = match.group(group_name).strip()
                        except (IndexError, AttributeError):
                            pass
                    
                    # Determine confidence level
                    score = pattern_def.confidence_score
                    if score >= 0.9:
                        confidence = IntentConfidence.HIGH
                    elif score >= 0.7:
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
                        suggested_command=self._map_intent_to_command(pattern_def.intent_type),
                        requires_confirmation=(confidence != IntentConfidence.HIGH)
                    )
                    
                    logger.info(
                        f"Intent detected (rule-based): {detected.intent_type.value}",
                        extra={
                            "intent": detected.intent_type.value,
                            "confidence": detected.confidence_score,
                            "pattern": pattern,
                            "params": params
                        }
                    )
                    
                    return detected
        
        # No pattern matched
        return None
    
    def _map_intent_to_command(self, intent_type: IntentType) -> Optional[str]:
        """Map intent type to command name."""
        mapping = {
            IntentType.NOTE_CREATE: "note.create",
            IntentType.NOTE_UPDATE: "note.update",
            IntentType.NOTE_DELETE: "note.delete",
            IntentType.SCHEDULE_CREATE: "schedule.create",
            IntentType.SCHEDULE_UPDATE: "schedule.update",
            IntentType.ACTION_REVERT: "action.revert"
        }
        return mapping.get(intent_type)
```

**Checklist:**
- [ ] RuleBasedDetector class
- [ ] Pattern definitions for 8+ intent types
- [ ] Regex matching with named capture groups
- [ ] Parameter extraction
- [ ] Confidence scoring
- [ ] Intent → Command mapping
- [ ] Logging for debugging
- [ ] Documentation

---

### Task 1.8.3: Implement Intent Detection Service

**Output:** `backend/app/intents/intent_service.py`

```python
"""
Intent Detection Service.

Orchestrates L1 (rule-based) and L2 (LLM) intent detection.
"""

from typing import Optional
from app.intents.schemas import DetectedIntent, IntentType, IntentConfidence
from app.intents.rule_detector import RuleBasedDetector
from app.utils.logger import get_logger

logger = get_logger(__name__)


class IntentDetectionService:
    """
    Multi-tier intent detection.
    
    Tiers:
    - L1: Rule-based (fast, deterministic, no cost)
    - L2: LLM-based (flexible, handles ambiguity, costs tokens)
    
    Flow:
      User message → L1 (rules) → if no match → L2 (LLM) → Intent
    """
    
    def __init__(self):
        self.rule_detector = RuleBasedDetector()
        self._stats = {
            "total_detections": 0,
            "l1_hits": 0,
            "l2_fallbacks": 0
        }
    
    async def detect_intent(
        self,
        message: str,
        context: Optional[dict] = None
    ) -> DetectedIntent:
        """
        Detect user intent from message.
        
        Args:
            message: User message
            context: Optional context for better detection
        
        Returns:
            DetectedIntent with confidence score
        """
        self._stats["total_detections"] += 1
        
        # Try L1: Rule-based detection
        l1_result = self.rule_detector.detect(message)
        
        if l1_result and l1_result.confidence == IntentConfidence.HIGH:
            # High confidence rule match - use it
            self._stats["l1_hits"] += 1
            
            logger.info(
                f"Intent detected by L1: {l1_result.intent_type.value}",
                extra={
                    "intent": l1_result.intent_type.value,
                    "confidence": l1_result.confidence_score,
                    "detection_tier": "L1"
                }
            )
            
            return l1_result
        
        # L2: Fallback to LLM (not implemented in Phase 1)
        # For now, return UNKNOWN intent to let existing LLM tool-calling handle it
        self._stats["l2_fallbacks"] += 1
        
        logger.info(
            "No clear intent detected, falling back to LLM tool-calling",
            extra={"detection_tier": "L2_fallback"}
        )
        
        return DetectedIntent(
            intent_type=IntentType.UNKNOWN,
            confidence=IntentConfidence.LOW,
            confidence_score=0.0,
            params={},
            detected_by="fallback",
            requires_confirmation=False
        )
    
    def get_stats(self) -> dict:
        """Get detection statistics."""
        total = self._stats["total_detections"]
        if total == 0:
            return {**self._stats, "l1_hit_rate": 0.0}
        
        return {
            **self._stats,
            "l1_hit_rate": self._stats["l1_hits"] / total
        }


# Global singleton
_intent_service: Optional[IntentDetectionService] = None


def get_intent_service() -> IntentDetectionService:
    """Get global IntentDetectionService instance."""
    global _intent_service
    if _intent_service is None:
        _intent_service = IntentDetectionService()
    return _intent_service


def reset_intent_service():
    """Reset global service (for testing)."""
    global _intent_service
    _intent_service = None
```

**Checklist:**
- [ ] IntentDetectionService class
- [ ] L1 rule-based detection
- [ ] L2 LLM fallback (placeholder for now)
- [ ] Statistics tracking (L1 hit rate)
- [ ] Logging for monitoring
- [ ] Global singleton
- [ ] Documentation

---

### Task 1.8.4: Integrate with AgentService

**File:** `backend/app/ai/agents/agent_service.py`

**Changes:**

```python
from app.intents.intent_service import get_intent_service
from app.intents.schemas import IntentType, IntentConfidence

class AgentService:
    # ... existing code ...
    
    async def handle(
        self,
        message: str,
        conversation_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        context: Optional[dict] = None
    ) -> dict:
        """Handle chat message with intent detection."""
        
        # ... existing conversation setup ...
        
        # NEW: Detect intent (L1)
        intent_service = get_intent_service()
        detected_intent = await intent_service.detect_intent(message, context)
        
        logger.info(
            f"Intent detected: {detected_intent.intent_type.value}",
            extra={
                "intent": detected_intent.intent_type.value,
                "confidence": detected_intent.confidence.value,
                "detected_by": detected_intent.detected_by
            }
        )
        
        # If high-confidence intent detected, can optimize routing
        # For Phase 1: Just pass intent to ContextService for filtering
        context_service = ContextService(self.db)
        unified_context = await context_service.build_context(
            user_id=self.user.id,
            workspace_id=workspace_id,
            conversation_id=conv.id,
            runtime_context=context,
            intent=detected_intent.intent_type.value  # NEW: Pass intent for filtering
        )
        
        # Rest of existing logic continues as before
        # (LLM tool-calling loop handles execution)
        
        # ... existing tool-calling logic ...
```

**Note:** In Phase 1, intent detection is primarily for:
1. Context filtering (already implemented in 1.7)
2. Gathering statistics (L1 hit rate)
3. Future optimization (Phase 7 will use intent to route to appropriate execution tier)

**Checklist:**
- [ ] Import IntentDetectionService
- [ ] Detect intent before context building
- [ ] Pass intent to ContextService for filtering
- [ ] Log intent detection results
- [ ] Existing tool-calling flow continues unchanged
- [ ] Test: chat works with intent detection

---

### Task 1.8.5: Add Intent Statistics Endpoint

**Output:** `backend/app/api/agent.py` (add new endpoint)

```python
from app.intents.intent_service import get_intent_service

@router.get("/agent/intent-stats")
async def get_intent_stats(
    current_user: User = Depends(get_current_active_user)
):
    """
    Get intent detection statistics.
    
    Shows how many requests are handled by L1 (rule-based) vs L2 (LLM).
    """
    intent_service = get_intent_service()
    stats = intent_service.get_stats()
    
    return {
        "stats": stats,
        "message": f"L1 hit rate: {stats['l1_hit_rate']:.1%}"
    }
```

**Checklist:**
- [ ] Add GET /agent/intent-stats endpoint
- [ ] Return L1/L2 statistics
- [ ] Requires authentication
- [ ] Documentation

---

### Task 1.8.6: Integration Tests

**Output:** `backend/tests/integration/test_intent_detection.py`

```python
import pytest
from app.intents.intent_service import IntentDetectionService, get_intent_service, reset_intent_service
from app.intents.schemas import IntentType, IntentConfidence


@pytest.fixture
def intent_service():
    """Fresh IntentDetectionService for each test."""
    reset_intent_service()
    return get_intent_service()


@pytest.mark.asyncio
async def test_detect_reminder_intent(intent_service):
    """Test detecting reminder intent."""
    result = await intent_service.detect_intent(
        "remind me to call John at 3pm"
    )
    
    assert result.intent_type == IntentType.REMINDER_CREATE
    assert result.confidence == IntentConfidence.HIGH
    assert result.detected_by == "rule"
    assert "task" in result.params
    assert "time" in result.params
    assert "call John" in result.params["task"]
    assert "3pm" in result.params["time"]


@pytest.mark.asyncio
async def test_detect_note_create_intent(intent_service):
    """Test detecting note creation intent."""
    result = await intent_service.detect_intent(
        "create a note about project planning"
    )
    
    assert result.intent_type == IntentType.NOTE_CREATE
    assert result.confidence == IntentConfidence.HIGH
    assert result.detected_by == "rule"
    assert "topic" in result.params
    assert "project planning" in result.params["topic"]


@pytest.mark.asyncio
async def test_detect_schedule_query_intent(intent_service):
    """Test detecting schedule query intent."""
    result = await intent_service.detect_intent(
        "what's on my schedule today"
    )
    
    assert result.intent_type == IntentType.SCHEDULE_QUERY
    assert result.confidence == IntentConfidence.HIGH
    assert result.params.get("timeframe") == "today"


@pytest.mark.asyncio
async def test_detect_web_search_intent(intent_service):
    """Test detecting web search intent."""
    result = await intent_service.detect_intent(
        "search for Python tutorials"
    )
    
    assert result.intent_type == IntentType.WEB_SEARCH
    assert result.detected_by == "rule"
    assert "query" in result.params


@pytest.mark.asyncio
async def test_unknown_intent_fallback(intent_service):
    """Test fallback for unclear intent."""
    result = await intent_service.detect_intent(
        "hmm, not sure what to do here"
    )
    
    assert result.intent_type == IntentType.UNKNOWN
    assert result.confidence == IntentConfidence.LOW
    assert result.detected_by == "fallback"


@pytest.mark.asyncio
async def test_intent_stats(intent_service):
    """Test statistics tracking."""
    # Detect some intents
    await intent_service.detect_intent("remind me to call at 3pm")  # L1 hit
    await intent_service.detect_intent("what's on my schedule")      # L1 hit
    await intent_service.detect_intent("unclear message here")       # L2 fallback
    
    stats = intent_service.get_stats()
    
    assert stats["total_detections"] == 3
    assert stats["l1_hits"] == 2
    assert stats["l2_fallbacks"] == 1
    assert stats["l1_hit_rate"] == 2/3


@pytest.mark.asyncio
async def test_case_insensitive_matching(intent_service):
    """Test that pattern matching is case-insensitive."""
    result1 = await intent_service.detect_intent("REMIND ME TO CALL")
    result2 = await intent_service.detect_intent("remind me to call")
    
    assert result1.intent_type == result2.intent_type
    assert result1.intent_type == IntentType.REMINDER_CREATE


@pytest.mark.asyncio
async def test_param_extraction(intent_service):
    """Test parameter extraction from patterns."""
    result = await intent_service.detect_intent(
        "schedule a meeting for tomorrow at 2pm called Sprint Planning"
    )
    
    assert result.intent_type == IntentType.SCHEDULE_CREATE
    assert "time" in result.params
    assert "title" in result.params
    assert "tomorrow at 2pm" in result.params["time"]
    assert "Sprint Planning" in result.params["title"]
```

**Checklist:**
- [ ] Test reminder intent detection
- [ ] Test note creation intent
- [ ] Test schedule query intent
- [ ] Test web search intent
- [ ] Test unknown intent fallback
- [ ] Test statistics tracking
- [ ] Test case-insensitive matching
- [ ] Test parameter extraction
- [ ] All tests pass

---

## ✅ Milestone 1.8 Definition of Done

- [ ] Intent schemas defined
- [ ] Rule-based detector (L1) implemented with 8+ patterns
- [ ] IntentDetectionService implemented
- [ ] Integration with AgentService
- [ ] Intent statistics endpoint
- [ ] Integration tests pass
- [ ] L1 hit rate measurable (target: > 20% of requests)
- [ ] Documentation complete
- [ ] No regression in existing chat functionality

---

## 📊 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| L1 hit rate | > 20% | Intent stats endpoint |
| L1 detection speed | < 5ms | Measure rule_detector.detect() |
| Pattern coverage | 8+ intents | Count IntentPattern definitions |
| Tests pass | 100% | pytest tests/integration/test_intent_detection.py |

---

## 🎯 Future Extensions (Phase 7)

This milestone lays the groundwork for full AI Routing:

- **L0 (Deterministic):** Date calculations, conflict detection → No LLM needed
- **L1 (Rule-based):** Current implementation → Pattern matching
- **L2 (Fast LLM):** Small model for classification → Cost optimization
- **L3 (Reasoning):** Complex planning → Full reasoning model

In Phase 7, detected intent will route to appropriate execution tier instead of always using tool-calling loop.

---

## 📝 Monitoring

After deployment, monitor:

```bash
# Check L1 hit rate
curl http://localhost:8000/api/agent/intent-stats

# Check logs for intent detection
tail -f logs/app.log | grep "Intent detected"
```

Expected output:
```json
{
  "stats": {
    "total_detections": 1000,
    "l1_hits": 250,
    "l2_fallbacks": 750,
    "l1_hit_rate": 0.25
  },
  "message": "L1 hit rate: 25.0%"
}
```

---

**Phase 1 Complete!** 🎉

All 8 milestones finished:
- ✅ 1.1: Event Schema Design
- ✅ 1.2: Event Bus Implementation
- ✅ 1.3: Core Event Definitions
- ✅ 1.4: Command Schema Design
- ✅ 1.5: Command Registry
- ✅ 1.6: Tool→Command Migration
- ✅ 1.7: Context Service
- ✅ 1.8: Intent Detection Layer

**Next:** Phase 2 - Goals & Commitments
