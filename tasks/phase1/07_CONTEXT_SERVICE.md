# Milestone 1.7: Context Service

**Timeline:** 3-4 ngày  
**Dependencies:** None (có thể song song với 1.4-1.6)  
**Effort:** Medium  

---

## 🎯 Mục tiêu

Thay thế việc mỗi component tự build context dict riêng (context pills, runtime context) bằng một service trung tâm — nền tảng cho "Cortex hiểu người dùng đang ở đâu".

**Hiện trạng:**
- Context được build ad-hoc ở nhiều nơi (AgentService, ConversationService)
- Không có filtering theo relevance → gửi toàn bộ context vào LLM
- Không có unified model → mỗi nơi tự parse context dict

**Mục tiêu:**
- Một service tập trung build context
- Context filtering theo relevance
- Unified context model
- Giảm token usage bằng cách chỉ gửi context liên quan

---

## 📋 Tasks

### Task 1.7.1: Define Unified Context Model

**Output:** `backend/app/context/schemas.py`

```python
"""
Context schemas for Cortex.

Context represents "what the user is doing right now" and includes:
- Runtime info (time, timezone, URL)
- Current view/object (note, schedule, etc.)
- Active workspace
- Recent activity
- Goals/tasks (Phase 2)
"""

from pydantic import BaseModel, Field
from typing import Optional, Any
from uuid import UUID
from datetime import datetime
from enum import Enum


class ViewType(str, Enum):
    """Type of view user is currently in."""
    GLOBAL_HOME = "global_home"
    WORKSPACE = "workspace"
    NOTE = "note"
    SCHEDULE = "schedule"
    CALENDAR = "calendar"
    CONVERSATION = "conversation"
    KNOWLEDGE = "knowledge"
    UNKNOWN = "unknown"


class RuntimeContext(BaseModel):
    """
    Runtime information about user's current state.
    
    Provided by frontend with each request.
    """
    current_time: datetime = Field(default_factory=datetime.utcnow)
    timezone: str = Field(default="UTC", description="User's timezone (e.g., 'America/New_York')")
    url: Optional[str] = Field(None, description="Current page URL")
    view_type: ViewType = Field(default=ViewType.UNKNOWN)
    
    # Device info (optional)
    device_type: Optional[str] = Field(None, description="desktop, mobile, tablet")
    screen_size: Optional[str] = Field(None, description="e.g., '1920x1080'")


class CurrentObject(BaseModel):
    """
    Object user is currently viewing/editing.
    
    Examples:
    - Viewing a note → {type: "note", id: "..."}
    - Editing a schedule → {type: "schedule", id: "..."}
    """
    type: str = Field(..., description="Object type: note, schedule, workspace, etc.")
    id: UUID = Field(..., description="Object ID")
    title: Optional[str] = Field(None, description="Object title (if available)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class ContextPill(BaseModel):
    """
    Context pill: user-provided or system-generated context snippet.
    
    Examples:
    - "I'm working on project X"
    - "This is for my CS class"
    - System: "User has 3 overdue tasks"
    """
    text: str
    source: str = Field(default="user", description="user, system, or agent")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    relevance_score: Optional[float] = Field(None, description="0-1, how relevant to current intent")


class WorkspaceContext(BaseModel):
    """Context about active workspace."""
    workspace_id: UUID
    workspace_name: str
    role: str = Field(..., description="viewer, editor, or admin")
    member_count: int = 0


class ConversationContext(BaseModel):
    """Context about current conversation."""
    conversation_id: UUID
    message_count: int
    recent_topics: list[str] = Field(default_factory=list, description="Topics discussed recently")
    last_tool_used: Optional[str] = None


class UnifiedContext(BaseModel):
    """
    Unified context model.
    
    Contains everything Cortex knows about "what user is doing right now".
    """
    # Runtime
    runtime: RuntimeContext
    
    # Current state
    current_object: Optional[CurrentObject] = None
    workspace: Optional[WorkspaceContext] = None
    conversation: Optional[ConversationContext] = None
    
    # User-provided context
    pills: list[ContextPill] = Field(default_factory=list)
    
    # Recent activity (for relevance)
    recent_notes: list[dict] = Field(default_factory=list, description="Recently accessed notes")
    recent_schedules: list[dict] = Field(default_factory=list, description="Upcoming schedules")
    
    # Goals/tasks (Phase 2)
    active_goals: list[dict] = Field(default_factory=list, description="User's active goals")
    overdue_tasks: list[dict] = Field(default_factory=list, description="Overdue tasks")
    
    def to_llm_string(self, max_tokens: int = 1000) -> str:
        """
        Convert context to string for LLM prompt.
        
        Args:
            max_tokens: Approximate token budget for context
        
        Returns:
            Formatted context string
        """
        parts = []
        
        # Runtime info
        parts.append(f"Current time: {self.runtime.current_time.strftime('%Y-%m-%d %H:%M %Z')}")
        if self.runtime.url:
            parts.append(f"Current page: {self.runtime.url}")
        
        # Current object
        if self.current_object:
            parts.append(f"Viewing: {self.current_object.type} - {self.current_object.title or self.current_object.id}")
        
        # Workspace
        if self.workspace:
            parts.append(f"Workspace: {self.workspace.workspace_name}")
        
        # Pills (most important)
        if self.pills:
            sorted_pills = sorted(
                self.pills,
                key=lambda p: p.relevance_score or 0,
                reverse=True
            )
            pills_text = "\n".join([f"- {p.text}" for p in sorted_pills[:3]])
            parts.append(f"Context:\n{pills_text}")
        
        # Recent activity (if space allows)
        if self.recent_schedules:
            upcoming = self.recent_schedules[:3]
            schedules_text = "\n".join([
                f"- {s.get('title')} at {s.get('start_time')}"
                for s in upcoming
            ])
            parts.append(f"Upcoming:\n{schedules_text}")
        
        return "\n\n".join(parts)
```

**Checklist:**
- [ ] RuntimeContext model
- [ ] CurrentObject model
- [ ] ContextPill model
- [ ] WorkspaceContext model
- [ ] ConversationContext model
- [ ] UnifiedContext model
- [ ] `to_llm_string()` method với token budget
- [ ] Documentation

---

### Task 1.7.2: Implement ContextService

**Output:** `backend/app/context/context_service.py`

```python
"""
ContextService: Central context building and filtering.

Replaces scattered context building logic in AgentService/ConversationService.
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.context.schemas import (
    UnifiedContext,
    RuntimeContext,
    CurrentObject,
    ContextPill,
    WorkspaceContext,
    ConversationContext,
    ViewType
)
from app.models import Note, Schedule, Workspace, WorkspaceMember
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ContextService:
    """
    Central service for building and filtering context.
    
    Responsibilities:
    - Aggregate context from multiple sources
    - Filter by relevance to current intent
    - Format for LLM consumption
    - Track token usage
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def build_context(
        self,
        user_id: UUID,
        workspace_id: Optional[UUID] = None,
        conversation_id: Optional[UUID] = None,
        runtime_context: Optional[dict] = None,
        intent: Optional[str] = None
    ) -> UnifiedContext:
        """
        Build unified context for user.
        
        Args:
            user_id: User ID
            workspace_id: Current workspace (if any)
            conversation_id: Current conversation (if any)
            runtime_context: Runtime info from frontend
            intent: Detected user intent (for filtering)
        
        Returns:
            UnifiedContext with all relevant information
        """
        # Parse runtime context
        runtime = self._parse_runtime_context(runtime_context or {})
        
        # Build components
        current_object = await self._get_current_object(runtime_context or {})
        workspace = await self._get_workspace_context(workspace_id, user_id) if workspace_id else None
        conversation = await self._get_conversation_context(conversation_id) if conversation_id else None
        pills = self._extract_pills(runtime_context or {})
        
        # Recent activity
        recent_notes = await self._get_recent_notes(user_id, limit=5)
        recent_schedules = await self._get_upcoming_schedules(user_id, limit=5)
        
        # Build unified context
        context = UnifiedContext(
            runtime=runtime,
            current_object=current_object,
            workspace=workspace,
            conversation=conversation,
            pills=pills,
            recent_notes=recent_notes,
            recent_schedules=recent_schedules
        )
        
        # Filter by relevance (if intent provided)
        if intent:
            context = self._filter_by_relevance(context, intent)
        
        logger.debug(
            f"Context built for user {user_id}",
            extra={
                "user_id": str(user_id),
                "workspace_id": str(workspace_id) if workspace_id else None,
                "pills_count": len(context.pills),
                "recent_notes_count": len(context.recent_notes),
                "recent_schedules_count": len(context.recent_schedules)
            }
        )
        
        return context
    
    def _parse_runtime_context(self, raw: dict) -> RuntimeContext:
        """Parse runtime context from frontend."""
        return RuntimeContext(
            current_time=datetime.fromisoformat(raw.get("time")) if raw.get("time") else datetime.utcnow(),
            timezone=raw.get("timezone", "UTC"),
            url=raw.get("url"),
            view_type=ViewType(raw.get("view", "unknown")),
            device_type=raw.get("device"),
            screen_size=raw.get("screen")
        )
    
    async def _get_current_object(self, raw: dict) -> Optional[CurrentObject]:
        """Extract current object from runtime context."""
        obj = raw.get("current_object")
        if not obj:
            return None
        
        return CurrentObject(
            type=obj.get("type"),
            id=UUID(obj.get("id")),
            title=obj.get("title"),
            metadata=obj.get("metadata", {})
        )
    
    async def _get_workspace_context(
        self,
        workspace_id: UUID,
        user_id: UUID
    ) -> Optional[WorkspaceContext]:
        """Get workspace context."""
        # Fetch workspace
        stmt = select(Workspace).where(Workspace.id == workspace_id)
        result = await self.db.execute(stmt)
        workspace = result.scalar_one_or_none()
        
        if not workspace:
            return None
        
        # Get user's role
        member_stmt = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id
        )
        member_result = await self.db.execute(member_stmt)
        member = member_result.scalar_one_or_none()
        
        if not member:
            return None
        
        # Count members
        count_stmt = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id
        )
        count_result = await self.db.execute(count_stmt)
        member_count = len(count_result.scalars().all())
        
        return WorkspaceContext(
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            role=member.role.value,
            member_count=member_count
        )
    
    async def _get_conversation_context(
        self,
        conversation_id: UUID
    ) -> Optional[ConversationContext]:
        """Get conversation context."""
        # TODO: Query conversation metadata
        # For now, return basic context
        return ConversationContext(
            conversation_id=conversation_id,
            message_count=0,  # Will be filled by ConversationStore
            recent_topics=[],
            last_tool_used=None
        )
    
    def _extract_pills(self, raw: dict) -> list[ContextPill]:
        """Extract context pills from raw context."""
        pills_data = raw.get("pills", [])
        
        pills = []
        for pill_data in pills_data:
            pill = ContextPill(
                text=pill_data.get("text", ""),
                source=pill_data.get("source", "user"),
                timestamp=datetime.fromisoformat(pill_data["timestamp"]) if pill_data.get("timestamp") else datetime.utcnow()
            )
            pills.append(pill)
        
        return pills
    
    async def _get_recent_notes(self, user_id: UUID, limit: int = 5) -> list[dict]:
        """Get recently accessed notes."""
        stmt = (
            select(Note)
            .where(
                Note.user_id == user_id,
                Note.is_deleted == False
            )
            .order_by(Note.updated_at.desc())
            .limit(limit)
        )
        
        result = await self.db.execute(stmt)
        notes = result.scalars().all()
        
        return [
            {
                "id": str(note.id),
                "title": note.title,
                "updated_at": note.updated_at.isoformat() if note.updated_at else None
            }
            for note in notes
        ]
    
    async def _get_upcoming_schedules(self, user_id: UUID, limit: int = 5) -> list[dict]:
        """Get upcoming schedules."""
        now = datetime.utcnow()
        future = now + timedelta(days=7)
        
        stmt = (
            select(Schedule)
            .where(
                Schedule.user_id == user_id,
                Schedule.start_time >= now,
                Schedule.start_time <= future,
                Schedule.is_completed == False
            )
            .order_by(Schedule.start_time.asc())
            .limit(limit)
        )
        
        result = await self.db.execute(stmt)
        schedules = result.scalars().all()
        
        return [
            {
                "id": str(schedule.id),
                "title": schedule.title,
                "start_time": schedule.start_time.isoformat(),
                "type": schedule.type.value
            }
            for schedule in schedules
        ]
    
    def _filter_by_relevance(self, context: UnifiedContext, intent: str) -> UnifiedContext:
        """
        Filter context by relevance to intent.
        
        Examples:
        - Intent: "schedule" → keep recent_schedules, drop recent_notes
        - Intent: "note" → keep recent_notes, drop recent_schedules
        - Intent: "general" → keep everything
        """
        # Simple keyword-based filtering
        intent_lower = intent.lower()
        
        if "schedule" in intent_lower or "calendar" in intent_lower or "remind" in intent_lower:
            # Schedule-related intent: prioritize schedule context
            context.recent_notes = []  # Drop notes
        
        elif "note" in intent_lower or "write" in intent_lower or "document" in intent_lower:
            # Note-related intent: prioritize note context
            context.recent_schedules = []  # Drop schedules
        
        # Assign relevance scores to pills based on intent
        for pill in context.pills:
            pill.relevance_score = self._calculate_pill_relevance(pill.text, intent)
        
        logger.debug(
            f"Context filtered for intent: {intent}",
            extra={
                "intent": intent,
                "pills_count": len(context.pills),
                "notes_count": len(context.recent_notes),
                "schedules_count": len(context.recent_schedules)
            }
        )
        
        return context
    
    def _calculate_pill_relevance(self, pill_text: str, intent: str) -> float:
        """
        Calculate relevance score (0-1) of pill to intent.
        
        Simple keyword overlap for now.
        TODO: Use semantic similarity (embeddings) in Phase 2.
        """
        pill_lower = pill_text.lower()
        intent_lower = intent.lower()
        
        # Simple keyword matching
        intent_words = set(intent_lower.split())
        pill_words = set(pill_lower.split())
        
        if not intent_words:
            return 0.5  # Neutral
        
        overlap = len(intent_words & pill_words)
        score = overlap / len(intent_words)
        
        return min(score, 1.0)
```

**Checklist:**
- [ ] ContextService class
- [ ] `build_context()` method
- [ ] Runtime context parsing
- [ ] Current object extraction
- [ ] Workspace context fetching
- [ ] Conversation context fetching
- [ ] Pills extraction
- [ ] Recent activity fetching
- [ ] Relevance filtering
- [ ] Documentation

---

### Task 1.7.3: Integrate with AgentService

**File:** `backend/app/ai/agents/agent_service.py`

**Changes:**

```python
from app.context.context_service import ContextService
from app.context.schemas import UnifiedContext

class AgentService:
    # ... existing code ...
    
    async def handle(
        self,
        message: str,
        conversation_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        context: Optional[dict] = None
    ) -> dict:
        """Handle chat message."""
        # ... existing conversation setup ...
        
        # NEW: Build unified context
        context_service = ContextService(self.db)
        unified_context = await context_service.build_context(
            user_id=self.user.id,
            workspace_id=workspace_id,
            conversation_id=conv.id,
            runtime_context=context,
            intent=None  # Will be set by intent detection in 1.8
        )
        
        # Use unified context in system prompt
        context_string = unified_context.to_llm_string(max_tokens=1000)
        
        system_prompt = await self.conversation_service.build_system_prompt(
            conv,
            message,
            context_string,  # Instead of raw context dict
            summarizer,
            SYSTEM_PROMPT
        )
        
        # ... rest of existing logic ...
```

**Checklist:**
- [ ] Import ContextService
- [ ] Build unified context in `handle()` method
- [ ] Convert context to LLM string
- [ ] Pass to system prompt builder
- [ ] Remove old context building logic
- [ ] Test: chat still works

---

### Task 1.7.4: Update ConversationService

**File:** `backend/app/ai/agents/conversation_service.py`

**Changes:**

```python
# Remove _inject_context_into_text function (replaced by ContextService)

def build_messages_from_history(
    self,
    recent_messages: list,
    message: str,
    context_string: str  # Changed from context: dict
) -> list[Message]:
    """Build messages with context."""
    messages = _build_history_contents(recent_messages)
    _trim_incomplete_tail(messages, "messages")
    
    # Inject context string
    current_text = message
    if context_string:
        current_text = f"{context_string}\n\n{message}"
    
    now = datetime.utcnow()
    messages.append(Message(
        role="user",
        content=_format_timestamp(now) + current_text,
        created_at=now
    ))
    
    return messages
```

**Checklist:**
- [ ] Update method signatures to accept context_string
- [ ] Remove old context injection logic
- [ ] Simplify context handling
- [ ] Test: conversation history works

---

### Task 1.7.5: Integration Tests

**Output:** `backend/tests/integration/test_context_service.py`

```python
import pytest
from uuid import uuid4
from datetime import datetime
from app.context.context_service import ContextService
from app.context.schemas import ViewType


@pytest.mark.asyncio
async def test_build_basic_context(async_db, test_user, test_workspace):
    """Test building basic context."""
    service = ContextService(async_db)
    
    context = await service.build_context(
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        runtime_context={
            "time": datetime.utcnow().isoformat(),
            "timezone": "America/New_York",
            "view": "workspace"
        }
    )
    
    assert context.runtime is not None
    assert context.runtime.timezone == "America/New_York"
    assert context.runtime.view_type == ViewType.WORKSPACE
    assert context.workspace is not None
    assert context.workspace.workspace_id == test_workspace.id


@pytest.mark.asyncio
async def test_context_with_pills(async_db, test_user):
    """Test context with user-provided pills."""
    service = ContextService(async_db)
    
    context = await service.build_context(
        user_id=test_user.id,
        runtime_context={
            "pills": [
                {"text": "Working on CS homework", "source": "user"},
                {"text": "Need to finish by Friday", "source": "user"}
            ]
        }
    )
    
    assert len(context.pills) == 2
    assert context.pills[0].text == "Working on CS homework"
    assert context.pills[1].text == "Need to finish by Friday"


@pytest.mark.asyncio
async def test_recent_activity(async_db, test_user, test_note, test_schedule):
    """Test fetching recent notes and schedules."""
    service = ContextService(async_db)
    
    context = await service.build_context(
        user_id=test_user.id
    )
    
    # Should include recent note
    assert len(context.recent_notes) > 0
    assert any(n["id"] == str(test_note.id) for n in context.recent_notes)
    
    # Should include upcoming schedule
    assert len(context.recent_schedules) > 0


@pytest.mark.asyncio
async def test_context_filtering_by_intent(async_db, test_user):
    """Test context filtering based on intent."""
    service = ContextService(async_db)
    
    # Build context with schedule intent
    context = await service.build_context(
        user_id=test_user.id,
        intent="schedule meeting"
    )
    
    # Should keep schedules, drop notes
    assert len(context.recent_schedules) > 0
    assert len(context.recent_notes) == 0


@pytest.mark.asyncio
async def test_context_to_llm_string(async_db, test_user, test_workspace):
    """Test converting context to LLM string."""
    service = ContextService(async_db)
    
    context = await service.build_context(
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        runtime_context={
            "pills": [
                {"text": "Working on project X", "source": "user"}
            ]
        }
    )
    
    llm_string = context.to_llm_string(max_tokens=500)
    
    assert "Current time:" in llm_string
    assert "Workspace:" in llm_string
    assert "Working on project X" in llm_string
```

**Checklist:**
- [ ] Test basic context building
- [ ] Test context with pills
- [ ] Test recent activity fetching
- [ ] Test context filtering by intent
- [ ] Test to_llm_string conversion
- [ ] All tests pass

---

## ✅ Milestone 1.7 Definition of Done

- [x] Unified context model defined — `backend/app/context/schemas.py` (thiết kế lại bám theo shape context thật của frontend, không theo `RuntimeContext`/`ViewType`/`CurrentObject` tưởng tượng trong plan gốc — xem ghi chú dưới)
- [x] ContextService implemented — `backend/app/context/context_service.py`
- [x] Integration with AgentService — `AgentService._build_context_string()` helper, gọi từ cả `handle()` lẫn `handle_streaming_generator()`
- [x] Integration with ConversationService — `build_system_prompt()` nhận thêm `context_string` optional
- [x] Context filtering by relevance — `_filter_by_relevance()`, kích hoạt khi có `intent` (chuẩn bị sẵn cho Milestone 1.8)
- [x] Recent activity fetching — recent notes (loại trừ đã xoá) + upcoming schedules (7 ngày tới, loại trừ đã hoàn thành)
- [x] `to_llm_string()` — **không** có "token budget" param như plan (không cần thiết ở quy mô hiện tại: tối đa 5 note + 5 schedule, luôn ngắn); có `max_items` để giới hạn số lượng
- [x] Integration tests pass — `backend/tests/unit/test_context_schemas.py` (9 test) + `backend/tests/integration/test_context_service.py` (20 test) chạy với DB thật
- [ ] Token usage reduced (measure before/after) — chưa đo, cần bật trong môi trường có traffic thật để so sánh trước/sau
- [x] No regression in chat functionality — full suite 185/185 (trừ 7 lỗi pre-existing không liên quan), `agent_service.py`/`conversation_service.py` compile + import sạch

**Status: hoàn thành 2026-08-06** (trừ đo lường token usage thực tế — cần môi trường production).

### Điều chỉnh quan trọng so với plan gốc

Đây là milestone rủi ro cao nhất trong Phase 1 vì đụng trực tiếp vào **pipeline chat AI đang chạy thật** (`agent_service.py` — 500+ dòng, gồm cả `handle()` không-streaming và `handle_streaming_generator()` streaming với tool-calling loop, retry, token budget). Quyết định thiết kế:

1. **KHÔNG thay thế `_inject_context_into_text`** (cơ chế inject `pills`/`page`/`runtime` vào từng message — cả tin nhắn hiện tại lẫn lịch sử — đồng thời cũng feed vào skill retrieval). Plan gốc muốn "ContextService thay thế logic build context rải rác" hoàn toàn, nhưng rewrite cơ chế này rủi ro rất cao (ảnh hưởng cả streaming lẫn non-streaming, cả lịch sử hội thoại, cả skill selection) so với giá trị mang lại. Thay vào đó, `ContextService` là **phụ trợ (additive)**: thêm phần thông tin hoàn toàn mới (workspace/recent notes/upcoming schedules — trước đây AI không hề biết trừ khi tự gọi tool tìm kiếm) vào system prompt, không đụng vào cơ chế pills/page/runtime hiện có.
2. **Không dùng `RuntimeContext`/`ViewType`/`CurrentObject`** như plan — frontend thực tế gửi `context: dict` tự do với 3 key `pills`/`page`/`runtime` (dict lồng nhau tuỳ ý, không có contract cố định). Ép vào Pydantic schema chặt sẽ vỡ với payload thật (ValidationError trên traffic thật). Giữ `page`/`runtime` là `dict` lỏng lẻo, dung sai (không phải dict thì trả `{}` thay vì raise).
3. **`to_llm_string()` không render `pills`/`page`/`runtime`** — chúng đã được đưa vào tin nhắn qua `_inject_context_into_text`; render lại trong system prompt sẽ trùng lặp thông tin, đi ngược mục tiêu giảm token của chính milestone này.
4. **Toàn bộ `ContextService`/helper integration được bọc try/except, không bao giờ raise** — nếu context enrichment lỗi, chat vẫn tiếp tục hoạt động bình thường (không có phần workspace/recent activity trong prompt), giống nguyên tắc "event publish failure không phá service" đã áp dụng xuyên suốt Phase 1.
5. Không viết test end-to-end gọi `AgentService.handle()` thật vì cần LLM call thật (tốn phí, non-deterministic, cần API key) — test trực tiếp `ContextService`, `build_system_prompt()`, và helper `_build_context_string()` (đều là string-building + DB, không gọi model).

---

## 📊 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Token reduction | 20-30% | Compare average prompt tokens before/after |
| Context build time | < 100ms | Measure ContextService.build_context() |
| Tests pass | 100% | All integration tests |
| Code coverage | > 80% | pytest --cov=app/context |

---

**Next Milestone:** [1.8 Intent Detection Layer](08_INTENT_DETECTION.md)
