"""
Tests for tool_call_counts reset per turn (Bước 1 fix).

Verifies that the counter resets at the start of each turn,
so cumulative calls across turns don't trigger MAX_SAME_TOOL_CALLS.

Run: python -m pytest test_tool_call_counts.py -v
"""

from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.ai.agents.agent_service import AgentService
from app.ai.agents.provider_types import (
    ToolCall,
    ProviderResponse,
)
from app.ai.agents.tool_registry import ToolRegistry


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
def mock_store():
    store = AsyncMock()
    conv_id = uuid4()
    conv = MagicMock()
    conv.id = conv_id
    conv.total_token_count = 0
    conv.message_count = 0
    conv.summary = None
    store.get_or_create_conversation = AsyncMock(return_value=conv)
    store.get_conversation_by_id = AsyncMock(return_value=conv)
    store.get_recent_messages = AsyncMock(return_value=[])
    store.save_message = AsyncMock()
    store.increment_message_count = AsyncMock()
    store.update_conversation_timestamp = AsyncMock()
    store.increment_token_count = AsyncMock()
    return store


@pytest.fixture
def service_with_registry(mock_user, mock_db):
    service = AgentService(user=mock_user, db=mock_db)
    registry = ToolRegistry()
    async def fake_handler(args, ctx):
        return {"result": "ok"}
    registry.register("test_tool", "A test tool", {"type": "object", "properties": {}}, fake_handler)
    service.registry = registry
    return service


@pytest.mark.asyncio
async def test_tool_call_counts_resets_between_turns(mock_store, service_with_registry):
    """Turn 1 uses 15 calls of tool_x, turn 2 uses 6 calls -> no break (each < 20)."""
    service = service_with_registry
    service.store = mock_store

    turn_count = [0]
    generate_returns = [
        ("model", ProviderResponse(tool_calls=[ToolCall(id=f"tc_{i}", name="test_tool", args={"query": str(i)}) for i in range(15)])),
        ("model", ProviderResponse(tool_calls=[ToolCall(id=f"tc_{i}", name="test_tool", args={"query": str(i)}) for i in range(6)])),
        ("model", ProviderResponse(content="Final answer")),
    ]

    async def mock_generate(messages, config, tools=None):
        idx = turn_count[0]
        turn_count[0] += 1
        return generate_returns[idx]

    with patch("app.ai.agents.agent_service._model_client") as mock_mc:
        mock_mc.generate = mock_generate

        result = await service.handle(message="test")

    assert "reply" in result
    assert result["reply"] != (
        "I wasn't able to find the information you requested. "
        "Could you provide more details?"
    ), "MAX_SAME_TOOL_CALLS triggered incorrectly across turns"
    assert turn_count[0] == 3, (
        f"Expected 3 turns (15 calls + 6 calls + final), got {turn_count[0]}"
    )


@pytest.mark.asyncio
async def test_tool_call_counts_breaks_within_same_turn(mock_store, service_with_registry):
    """Single turn with >20 calls of same tool still breaks."""
    service = service_with_registry
    service.store = mock_store

    turn_count = [0]

    async def mock_generate(messages, config, tools=None):
        turn_count[0] += 1
        if turn_count[0] == 1:
            calls = [
                ToolCall(id=f"tc_{i}", name="test_tool", args={"query": str(i)})
                for i in range(21)
            ]
            return ("model", ProviderResponse(tool_calls=calls))
        return ("model", ProviderResponse(content="Final answer"))

    with patch("app.ai.agents.agent_service._model_client") as mock_mc:
        mock_mc.generate = mock_generate

        result = await service.handle(message="test")

    assert "reply" in result
    assert "wasn't able to find" in result["reply"], (
        f"Expected MAX_SAME_TOOL_CALLS message, got: {result['reply']}"
    )
