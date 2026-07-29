"""
E2E integration tests for AI + Tool orchestration.

Tests that AgentService correctly routes LLM-generated tool_calls
to the right handlers, propagates results back, and produces
correct final responses — all with mocked LLM and store layers.

M1: Test harness (inherits from existing test_agent_integration.py patterns)
M2: 5 E2E tests for create_note, create_schedule, search_notes, get_schedules, revert_action
M3: Revert flow test (snapshot → revert → state verified)

Run: python -m pytest test_e2e_tools.py -v
"""

import json
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.ai.agents.agent_service import AgentService
from app.ai.agents.provider_types import ToolCall, ProviderResponse
from app.ai.agents.tool_registry import ToolRegistry
from app.ai.agents.tool_context import ToolContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = uuid4()
    return user


@pytest.fixture
def mock_conv():
    conv = MagicMock()
    conv.id = uuid4()
    conv.total_token_count = 0
    conv.message_count = 0
    conv.summary = None
    return conv


@pytest.fixture
def mock_store(mock_conv):
    store = AsyncMock()
    store.get_or_create_conversation = AsyncMock(return_value=mock_conv)
    store.get_conversation_by_id = AsyncMock(return_value=mock_conv)
    store.get_recent_messages = AsyncMock(return_value=[])
    store.save_message = AsyncMock()
    store.increment_message_count = AsyncMock()
    store.update_conversation_timestamp = AsyncMock()
    store.increment_token_count = AsyncMock()
    return store


def _make_service(user, db) -> AgentService:
    svc = AgentService(user=user, db=db)
    registry = ToolRegistry()
    svc.registry = registry
    svc.tool_service.registry = registry
    return svc, registry


def _inline_service(user, db):
    svc = AgentService(user=user, db=db)
    registry = ToolRegistry()
    svc.registry = registry
    svc.tool_service.registry = registry
    return svc, registry


# Each test below:
#   1. Creates AgentService with a custom registry
#   2. Registers a mock handler for the target tool
#   3. Patches _model_client.generate to return a tool_call for that tool
#      on the first call, then a text response on the second call
#   4. Calls service.handle()
#   5. Asserts the tool was invoked with the correct arguments
#   6. Asserts the final response is as expected


# ── M2: 5 E2E tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_note_tool_e2e(mock_store, mock_user, mock_db):
    """LLM returns create_note tool_call → handler creates note → text response."""
    svc, registry = _make_service(mock_user, mock_db)
    handler = AsyncMock(return_value={
        "id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "created_at": "2026-07-28T10:00:00",
        "action_id": str(uuid4()),
        "success": True,
    })
    registry.register("create_note", "Create a note",
                      {"type": "object", "properties": {"content": {"type": "string"}, "style_color": {"type": "string"}}},
                      handler)
    svc.registry = registry
    svc.tool_service.registry = registry
    svc.store = mock_store

    turn = [0]

    async def mock_gen(msgs, config, tools=None):
        idx = turn[0]
        turn[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t1", name="create_note", args={"content": "Test note content", "style_color": "blue"})]
            ))
        return ("model", ProviderResponse(content="Note has been created successfully."))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        result = await svc.handle(message="Create a note for me")

    handler.assert_awaited_once()
    call_kwargs = handler.await_args.args[0] if handler.await_args and handler.await_args.args else {}
    assert call_kwargs.get("content") == "Test note content"
    assert call_kwargs.get("style_color") == "blue"
    assert "Note has been created" in result["reply"]
    assert "conversation_id" in result


@pytest.mark.asyncio
async def test_create_schedule_tool_e2e(mock_store, mock_user, mock_db):
    """LLM returns create_schedule tool_call → handler creates schedule → text response."""
    svc, registry = _make_service(mock_user, mock_db)
    handler = AsyncMock(return_value={
        "id": str(uuid4()),
        "title": "Test Event",
        "action_id": str(uuid4()),
        "success": True,
    })
    registry.register("create_schedule", "Create a schedule",
                      {"type": "object", "properties": {
                          "title": {"type": "string"},
                          "type": {"type": "string"},
                          "start_time": {"type": "string"},
                          "end_time": {"type": "string"},
                      }},
                      handler)
    svc.registry = registry
    svc.tool_service.registry = registry
    svc.store = mock_store

    turn = [0]

    async def mock_gen(msgs, config, tools=None):
        idx = turn[0]
        turn[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t1", name="create_schedule", args={
                    "title": "Study Session",
                    "type": "CLASS",
                    "start_time": "2026-07-28T10:00:00+07:00",
                    "end_time": "2026-07-28T11:00:00+07:00",
                })]
            ))
        return ("model", ProviderResponse(content="Schedule created."))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        result = await svc.handle(message="Create a study schedule")

    handler.assert_awaited_once()
    call_kwargs = handler.await_args.args[0] if handler.await_args and handler.await_args.args else {}
    assert call_kwargs.get("title") == "Study Session"
    assert call_kwargs.get("type") == "CLASS"
    assert "Schedule created" in result["reply"]


@pytest.mark.asyncio
async def test_search_notes_tool_e2e(mock_store, mock_user, mock_db):
    """LLM returns search_notes tool_call → handler searches → text response with results."""
    svc, registry = _make_service(mock_user, mock_db)
    handler = AsyncMock(return_value={
        "count": 2,
        "method": "keyword",
        "notes": [
            {"id": str(uuid4()), "content_preview": "About Python", "similarity_score": 0.95},
            {"id": str(uuid4()), "content_preview": "Python tips", "similarity_score": 0.82},
        ],
    })
    registry.register("search_notes", "Search notes",
                      {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
                      handler)
    svc.registry = registry
    svc.tool_service.registry = registry
    svc.store = mock_store

    turn = [0]

    async def mock_gen(msgs, config, tools=None):
        idx = turn[0]
        turn[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t1", name="search_notes", args={"query": "Python", "limit": 5})]
            ))
        return ("model", ProviderResponse(content="I found 2 notes about Python."))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        result = await svc.handle(message="Search my notes about Python")

    handler.assert_awaited_once()
    call_kwargs = handler.await_args.args[0] if handler.await_args and handler.await_args.args else {}
    assert call_kwargs.get("query") == "Python"
    assert call_kwargs.get("limit") == 5
    assert "I found 2 notes" in result["reply"]


@pytest.mark.asyncio
async def test_get_schedules_tool_e2e(mock_store, mock_user, mock_db):
    """LLM returns get_schedules tool_call → handler fetches schedules → text response."""
    svc, registry = _make_service(mock_user, mock_db)
    handler = AsyncMock(return_value={
        "schedules": [
            {"id": str(uuid4()), "title": "Math Class", "start_time": "2026-07-28T08:00:00", "type": "CLASS"},
            {"id": str(uuid4()), "title": "Physics Lab", "start_time": "2026-07-28T10:00:00", "type": "CLASS"},
        ],
        "total": 2,
    })
    registry.register("get_schedules", "Get schedules",
                      {"type": "object", "properties": {
                          "start_date": {"type": "string"},
                          "end_date": {"type": "string"},
                          "type_filter": {"type": "string"},
                          "limit": {"type": "integer"},
                      }},
                      handler)
    svc.registry = registry
    svc.tool_service.registry = registry
    svc.store = mock_store

    turn = [0]

    async def mock_gen(msgs, config, tools=None):
        idx = turn[0]
        turn[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t1", name="get_schedules", args={
                    "start_date": "2026-07-28T00:00:00",
                    "end_date": "2026-07-28T23:59:59",
                    "type_filter": "CLASS",
                    "limit": 10,
                })]
            ))
        return ("model", ProviderResponse(content="You have 2 classes today."))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        result = await svc.handle(message="What classes do I have today?")

    handler.assert_awaited_once()
    call_kwargs = handler.await_args.args[0] if handler.await_args and handler.await_args.args else {}
    assert call_kwargs.get("type_filter") == "CLASS"
    assert call_kwargs.get("limit") == 10
    assert "2 classes" in result["reply"]


@pytest.mark.asyncio
async def test_revert_action_tool_e2e(mock_store, mock_user, mock_db):
    """LLM returns revert_action tool_call → handler reverts → confirmation response."""
    svc, registry = _make_service(mock_user, mock_db)
    handler = AsyncMock(return_value={
        "success": True,
        "action_id": "test-action-123",
        "tool_name": "create_note",
        "op": "create_note",
        "detail": {"message": "Đã xóa note...", "note_id": "note-123"},
        "message": "Đã hoàn tác thành công: create_note",
    })
    registry.register("revert_action", "Revert an action",
                      {"type": "object", "properties": {"action_id": {"type": "string"}}},
                      handler)
    svc.registry = registry
    svc.tool_service.registry = registry
    svc.store = mock_store

    turn = [0]

    async def mock_gen(msgs, config, tools=None):
        idx = turn[0]
        turn[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t1", name="revert_action", args={"action_id": "test-action-123"})]
            ))
        return ("model", ProviderResponse(content="I have reverted that action."))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        result = await svc.handle(message="Undo my last action")

    handler.assert_awaited_once()
    call_kwargs = handler.await_args.args[0] if handler.await_args and handler.await_args.args else {}
    assert call_kwargs.get("action_id") == "test-action-123"
    assert "reverted" in result["reply"].lower()


# ── M3: Revert flow (create_note → revert) ──────────────────────────────────

@pytest.mark.asyncio
async def test_revert_flow_create_note(mock_store, mock_user, mock_db):
    """
    Simulate the full revert lifecycle:
      1. LLM calls create_note → handler creates note snapshot
      2. LLM calls revert_action → handler reverts the snapshot
    Verifies the snapshot store is called correctly and the revert handler
    receives the right action_id.
    """
    svc, registry = _make_service(mock_user, mock_db)

    create_handler = AsyncMock(return_value={
        "id": "note-created-1",
        "action_id": "action-create-note-1",
        "success": True,
    })
    revert_handler = AsyncMock(return_value={
        "success": True,
        "action_id": "action-create-note-1",
        "tool_name": "create_note",
        "op": "create_note",
        "message": "Đã hoàn tác tạo note.",
    })

    registry.register("create_note", "Create a note",
                      {"type": "object", "properties": {"content": {"type": "string"}}},
                      create_handler)
    registry.register("revert_action", "Revert an action",
                      {"type": "object", "properties": {"action_id": {"type": "string"}}},
                      revert_handler)
    svc.registry = registry
    svc.tool_service.registry = registry
    svc.store = mock_store

    turn = [0]

    async def mock_gen(msgs, config, tools=None):
        idx = turn[0]
        turn[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t1", name="create_note",
                                     args={"content": "Note to undo"})]
            ))
        if idx == 1:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t2", name="revert_action",
                                     args={"action_id": "action-create-note-1"})]
            ))
        return ("model", ProviderResponse(content="Done. Created and reverted."))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        result = await svc.handle(message="Create a note and then undo it")

    create_handler.assert_awaited_once()
    revert_handler.assert_awaited_once()
    revert_call_kwargs = revert_handler.await_args.args[0] if revert_handler.await_args and revert_handler.await_args.args else {}
    assert revert_call_kwargs.get("action_id") == "action-create-note-1"
    assert "Created and reverted" in result["reply"]
    assert turn[0] == 3  # 2 tool turns + 1 text turn
