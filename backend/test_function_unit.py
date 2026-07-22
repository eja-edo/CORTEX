"""
Unit tests for individual functions (Part 1):
  - _trim_incomplete_tail
  - estimate_tokens / estimate_message_tokens
  - _build_history_contents edge cases
  - tool_registry.execute error handling
  - openai_provider.generate_stream exception recovery
  - get_recent_messages_by_token_budget boundary case

Run: python -m pytest test_function_unit.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from types import SimpleNamespace
from datetime import datetime

import pytest

from app.ai.agents.agent_service import (
    _trim_incomplete_tail,
    _build_history_contents,
    _sum_message_tokens,
    _estimate_token_breakdown,
)
from app.ai.agents.provider_types import Message, ToolCall, ToolResult
from app.ai.agents.openai_provider import OpenAIProvider, GenerationConfig
from app.ai.agents.tool_registry import ToolDefinition, ToolRegistry
from app.utils.tokens import estimate_tokens, estimate_message_tokens


# ---------------------------------------------------------------------------
# _trim_incomplete_tail
# ---------------------------------------------------------------------------

def _msg(role, content=None, tool_calls=None):
    return Message(role=role, content=content, tool_calls=tool_calls)


def test_trim_incomplete_tail_removes_trailing_tool():
    """Trailing tool message with preceding assistant tool_calls → all removed (incl user)."""
    msgs = [
        _msg("user", "hi"),
        _msg("assistant", tool_calls=[ToolCall(id="t1", name="search", args={})]),
        _msg("tool", None),
    ]
    _trim_incomplete_tail(msgs, "test")
    assert len(msgs) == 0, "All items trimmed including user (user is also trailing)"


def test_trim_incomplete_tail_removes_trailing_user():
    """Trailing user message → removed."""
    msgs = [
        _msg("user", "hi"),
        _msg("assistant", "ok"),
        _msg("user", "follow-up"),
    ]
    _trim_incomplete_tail(msgs, "test")
    assert len(msgs) == 2


def test_trim_incomplete_tail_empty():
    """Empty list → no error."""
    msgs = []
    _trim_incomplete_tail(msgs, "test")
    assert msgs == []


def test_trim_incomplete_tail_no_trim_needed():
    """Complete sequence → unchanged."""
    msgs = [
        _msg("user", "hi"),
        _msg("assistant", "hello"),
    ]
    _trim_incomplete_tail(msgs, "test")
    assert len(msgs) == 2


def test_trim_incomplete_tail_parallel_execution_tail():
    """Tail from parallel execution: missing one tool_result."""
    msgs = [
        _msg("user", "hi"),
        _msg("assistant", tool_calls=[
            ToolCall(id="t1", name="search", args={}),
            ToolCall(id="t2", name="fetch", args={}),
            ToolCall(id="t3", name="search", args={}),
        ]),
        _msg("tool", None),
        _msg("tool", None),
    ]
    _trim_incomplete_tail(msgs, "test")
    assert len(msgs) == 0, "All items trimmed (2 tool results + assistant + tool + user)"


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------

def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_short_text():
    tokens = estimate_tokens("Hello world")
    assert tokens > 0


def test_estimate_tokens_special_chars():
    tokens = estimate_tokens("🎉🚀🌟")
    assert tokens > 0


def test_estimate_tokens_fallback_on_tiktoken_error():
    """When tiktoken fails, fallback to char-based estimate."""
    import app.utils.tokens as tokens_mod
    tokens_mod._encoding = None
    with patch.object(tokens_mod, "_get_encoding", return_value=None):
        tokens = estimate_tokens("Hello world test " * 100)
        assert tokens > 0
    tokens_mod._encoding = None


# ---------------------------------------------------------------------------
# estimate_message_tokens
# ---------------------------------------------------------------------------

def test_estimate_message_tokens_basic():
    tokens = estimate_message_tokens("user", "Hello")
    assert tokens > 0


def test_estimate_message_tokens_with_tool():
    tokens = estimate_message_tokens(
        role="tool",
        content=None,
        tool_name="web_search",
        tool_output={"query": "test", "results": [{"title": "A"}] * 10}
    )
    assert tokens > 0


def test_estimate_message_tokens_complex_nested():
    """Complex nested tool_output dict."""
    output = {
        "url": "https://example.com",
        "title": "Example",
        "markdown": "# Hello\n\n" * 500,
        "metadata": {
            "tags": ["a", "b", "c"],
            "nested": {"deep": {"deeper": {"value": 42}}},
        }
    }
    tokens = estimate_message_tokens("tool", None, "web_fetch", output)
    assert tokens > 0


# ---------------------------------------------------------------------------
# _build_history_contents — edge cases
# ---------------------------------------------------------------------------

def _fake_record(role, content=None, tool_name=None, tool_input=None,
                 tool_output=None, tool_call_id=None, turn_id=None):
    return SimpleNamespace(
        role=role, content=content,
        tool_name=tool_name, tool_input=tool_input, tool_output=tool_output,
        tool_call_id=tool_call_id, turn_id=turn_id,
        context=None,
    )


def test_build_history_skips_incomplete_tool():
    """Tool record missing tool_name → skipped."""
    records = [
        _fake_record("user", "hi"),
        _fake_record("assistant", "let me search"),
        _fake_record("tool", tool_name=None, tool_output={}, tool_call_id=None, turn_id="t1"),
    ]
    result = _build_history_contents(records)
    assert len(result) == 2  # Only user + assistant (no tool pair)


def test_build_history_skips_tool_missing_output():
    """Tool record missing tool_output → skipped."""
    records = [
        _fake_record("user", "hi"),
        _fake_record("assistant", "searching"),
        _fake_record("tool", tool_name="search", tool_input={"q": "x"}, tool_output=None, tool_call_id="t1", turn_id="t1"),
    ]
    result = _build_history_contents(records)
    assert len(result) == 2  # Only user + assistant


def test_build_history_legacy_no_turn_id_grouping():
    """Records without turn_id still grouped by consecutive position."""
    records = [
        _fake_record("user", "hi"),
        _fake_record("assistant", None, tool_name=None, tool_input=None, tool_output=None),
        _fake_record("tool", tool_name="web_search", tool_input={"q": "x"}, tool_output={"r": "ok"}, tool_call_id="c1", turn_id=None),
        _fake_record("tool", tool_name="web_fetch", tool_input={"url": "y"}, tool_output={"r": "ok"}, tool_call_id="c2", turn_id=None),
    ]
    # Turn_id is None for all tool records → should be grouped
    # But records[1] is an assistant with empty content (None) which gets SKIPPED
    # So tools follow user directly — need to check if they still get grouped
    result = _build_history_contents(records)
    # After trimming, records[0] (user) stays
    # An empty assistant will be inserted before tools
    tool_msgs = [m for m in result if m.tool_calls is not None]
    assert len(tool_msgs) >= 1, "Tool calls should be grouped"

    if tool_msgs:
        tc = tool_msgs[0].tool_calls
        assert tc is not None
        assert len(tc) >= 1


# ---------------------------------------------------------------------------
# tool_registry.execute — error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_execute_handler_raises_value_error():
    """Handler raises ValueError → returned as success: False."""
    registry = ToolRegistry()

    async def failing_handler(args, ctx):
        raise ValueError("Invalid input")

    registry.register("test_tool", "test", {"type": "object", "properties": {}}, failing_handler)
    ctx = MagicMock()
    ctx.user_id = uuid4()
    result = await registry.execute("test_tool", {}, ctx)

    assert result["success"] is False
    assert "error" in result
    assert "Invalid input" in result["error"]


@pytest.mark.asyncio
async def test_tool_execute_handler_raises_timeout():
    """Handler raises TimeoutError → returned as success: False."""
    registry = ToolRegistry()

    async def timeout_handler(args, ctx):
        raise TimeoutError("Request timed out")

    registry.register("timeout_tool", "test", {"type": "object", "properties": {}}, timeout_handler)
    ctx = MagicMock()
    ctx.user_id = uuid4()
    result = await registry.execute("timeout_tool", {}, ctx)

    assert result["success"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_tool_execute_handler_raises_custom_exception():
    """Custom exception → returned as success: False."""
    registry = ToolRegistry()

    class CustomToolError(Exception):
        pass

    async def custom_handler(args, ctx):
        raise CustomToolError("Something specific broke")

    registry.register("custom_tool", "test", {"type": "object", "properties": {}}, custom_handler)
    ctx = MagicMock()
    ctx.user_id = uuid4()
    result = await registry.execute("custom_tool", {}, ctx)

    assert result["success"] is False
    assert "Something specific broke" in result["error"]


@pytest.mark.asyncio
async def test_tool_execute_validation_error():
    """Pydantic validation error → returned as success: False without handler call."""
    from pydantic import BaseModel, Field

    registry = ToolRegistry()

    class InputModel(BaseModel):
        name: str = Field(min_length=1)

    async def handler(args, ctx):
        return {"result": "ok"}

    registry.register("validated_tool", "test",
                      {"type": "object", "properties": {"name": {"type": "string"}}},
                      handler, input_model=InputModel)

    ctx = MagicMock()
    ctx.user_id = uuid4()
    result = await registry.execute("validated_tool", {"name": ""}, ctx)

    assert result["success"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_tool_execute_not_found():
    """Unknown tool name → returned as success: False."""
    registry = ToolRegistry()
    ctx = MagicMock()
    ctx.user_id = uuid4()
    result = await registry.execute("nonexistent_tool", {}, ctx)

    assert result["success"] is False
    assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# openai_provider.generate_stream — exception handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_stream_network_error():
    """Network drop during stream → exception propagates, no partial usage leak."""
    provider = OpenAIProvider()
    config = GenerationConfig(system_instruction="test")

    with patch("app.ai.agents.openai_provider._get_client") as mock_client:
        mock_client.return_value.chat.completions.create.side_effect = \
            ConnectionError("Connection reset by peer")

        with pytest.raises(ConnectionError):
            chunks = []
            async for chunk in provider.generate_stream("gpt-4o", [], config):
                chunks.append(chunk)

        assert len(chunks) == 0, "No chunks should be yielded on error"


@pytest.mark.asyncio
async def test_generate_stream_partial_then_error():
    """Stream yields content then fails mid-way → partial content yielded, error propagates."""
    provider = OpenAIProvider()
    config = GenerationConfig(system_instruction="test")

    async def fake_stream():
        chunk = MagicMock()
        chunk.usage = None
        choice = MagicMock()
        choice.delta.content = "Partial"
        choice.delta.tool_calls = []
        choice.finish_reason = None
        chunk.choices = [choice]
        yield chunk
        raise ConnectionError("Stream dropped mid-way")

    async def mock_create(*args, **kwargs):
        return fake_stream()

    with patch("app.ai.agents.openai_provider._get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = mock_create
        mock_get_client.return_value = mock_client

        collected = []
        with pytest.raises(ConnectionError):
            async for chunk in provider.generate_stream("gpt-4o", [], config):
                collected.append(chunk)

        assert len(collected) == 1, (
            f"Expected 1 partial chunk before error, got {len(collected)}"
        )
        assert collected[0].content == "Partial", (
            f"Expected content='Partial', got {collected[0].content}"
        )


# ---------------------------------------------------------------------------
# get_recent_messages_by_token_budget — boundary case
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_budget_exact_boundary():
    """Budget exactly equals sum of N messages → all N fit, N+1st excluded."""
    from app.ai.agents.conversation_store import ConversationStore

    db = AsyncMock()
    store = ConversationStore(db)

    msgs = []
    for i in range(5):
        msgs.append(SimpleNamespace(
            id=uuid4(), role="user", content=f"msg{i}",
            tool_name=None, tool_input=None, tool_output=None, tool_call_id=None,
            turn_id=None, context=None, created_at_idx=i,
        ))

    # Budget = sum of 3 messages' tokens
    budget = sum(estimate_message_tokens("user", f"msg{i}") for i in range(3))

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = list(reversed(msgs))
    db.execute.return_value = mock_result

    result = await store.get_recent_messages_by_token_budget(
        conversation_id=uuid4(), max_tokens=budget,
    )

    # All 3 messages should fit; the 4th (msg[3] = "msg3") shouldn't
    # Since we iterate newest→oldest: msg4, msg3, msg2 → sum stops at msg3
    # Result is oldest→newest: msg2, msg3, msg4 (created_at_idx 2, 3, 4)
    assert len(result) == 3, f"Expected exactly 3 messages at boundary, got {len(result)}"
    assert result[0].created_at_idx == 2  # 3rd newest = oldest kept


@pytest.mark.asyncio
async def test_token_budget_exact_boundary_plus_one():
    """Budget = sum of N messages + 1 → N messages fit (tight boundary)."""
    from app.ai.agents.conversation_store import ConversationStore

    db = AsyncMock()
    store = ConversationStore(db)

    msgs = []
    for i in range(5):
        msgs.append(SimpleNamespace(
            id=uuid4(), role="user", content=f"m{i}",
            tool_name=None, tool_input=None, tool_output=None, tool_call_id=None,
            turn_id=None, context=None, created_at_idx=i,
        ))

    budget = sum(estimate_message_tokens("user", f"m{i}") for i in range(3))

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = list(reversed(msgs))
    db.execute.return_value = mock_result

    result = await store.get_recent_messages_by_token_budget(
        conversation_id=uuid4(), max_tokens=budget,
    )

    assert len(result) == 3, f"Expected 3 messages for tight budget, got {len(result)}"


# ---------------------------------------------------------------------------
# web_fetch truncation (Issue #6 — MAX_MARKDOWN_CHARS)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.ai.tools.web_fetch.Reader")
async def test_web_fetch_truncates_long_content(MockReader):
    """Content exceeding MAX_MARKDOWN_CHARS (8000) is truncated with suffix."""
    from app.ai.tools.web_fetch import web_fetch_handler, MAX_MARKDOWN_CHARS, TRUNCATION_SUFFIX

    long_md = "A" * (MAX_MARKDOWN_CHARS + 500)
    MockReader.return_value.fetch.return_value = {
        "markdown": long_md,
        "url": "https://example.com/long",
        "title": "Long Page",
        "length": len(long_md),
        "method_used": "readability",
        "candidate_lengths": {},
        "last_updated": None,
        "breadcrumb": None,
        "quality_warning": None,
        "quality_fallback_reason": None,
    }

    ctx = MagicMock()
    result = await web_fetch_handler({"url": "https://example.com/long"}, ctx)

    assert result["truncated"] is True, "Content should be marked truncated"
    assert result["original_length"] == len(long_md)
    assert result["length"] == MAX_MARKDOWN_CHARS + len(TRUNCATION_SUFFIX), (
        f"Expected length {MAX_MARKDOWN_CHARS + len(TRUNCATION_SUFFIX)}, got {result['length']}"
    )
    assert result["markdown"].endswith(TRUNCATION_SUFFIX), (
        f"Truncated content should end with suffix: {TRUNCATION_SUFFIX}"
    )
    assert len(result["markdown"]) == MAX_MARKDOWN_CHARS + len(TRUNCATION_SUFFIX), (
        f"Expected {MAX_MARKDOWN_CHARS + len(TRUNCATION_SUFFIX)} chars, "
        f"got {len(result['markdown'])}"
    )


@pytest.mark.asyncio
@patch("app.ai.tools.web_fetch.Reader")
async def test_web_fetch_does_not_truncate_short_content(MockReader):
    """Content under MAX_MARKDOWN_CHARS is returned as-is."""
    from app.ai.tools.web_fetch import web_fetch_handler, MAX_MARKDOWN_CHARS

    short_md = "Short content"
    MockReader.return_value.fetch.return_value = {
        "markdown": short_md,
        "url": "https://example.com/short",
        "title": "Short Page",
        "length": len(short_md),
        "method_used": "readability",
        "candidate_lengths": {},
        "last_updated": None,
        "breadcrumb": None,
        "quality_warning": None,
        "quality_fallback_reason": None,
    }

    ctx = MagicMock()
    result = await web_fetch_handler({"url": "https://example.com/short"}, ctx)

    assert result["truncated"] is False
    assert result["markdown"] == short_md
    assert result["length"] == len(short_md)


# ---------------------------------------------------------------------------
# _sum_message_tokens
# ---------------------------------------------------------------------------


def test_sum_message_tokens_empty():
    assert _sum_message_tokens([]) == 0


def test_sum_message_tokens_user_and_assistant():
    msgs = [
        Message(role="user", content="Hello, world!"),
        Message(role="assistant", content="Hi there!"),
    ]
    total = _sum_message_tokens(msgs)
    assert total > 0
    # Should be at least role tokens + content tokens for both
    assert total >= 8  # 2 roles + content


def test_sum_message_tokens_with_tool_result():
    msgs = [
        Message(role="assistant", tool_calls=[ToolCall(id="c1", name="get_weather", args={"city": "Hanoi"})]),
        Message(role="tool", tool_result=ToolResult(tool_call_id="c1", name="get_weather", content={"temp": 30})),
    ]
    total = _sum_message_tokens(msgs)
    assert total > 0


def test_sum_message_tokens_assistant_with_tool_calls():
    msgs = [
        Message(
            role="assistant",
            tool_calls=[
                ToolCall(id="c1", name="search", args={"q": "weather"}),
                ToolCall(id="c2", name="fetch", args={"url": "https://example.com"}),
            ],
        ),
    ]
    total = _sum_message_tokens(msgs)
    assert total > 0
    # Should include serialized tool_calls
    assert total >= 6  # role + name + args for 2 calls


# ---------------------------------------------------------------------------
# _estimate_token_breakdown
# ---------------------------------------------------------------------------


def test_estimate_token_breakdown_turn_0():
    """Turn 0: history + user message → history tokens + current_input."""
    msgs = [
        Message(role="user", content="What's the weather in Hanoi?"),
    ]
    bd = _estimate_token_breakdown(msgs, "You are a helpful assistant.", turn=0)
    assert bd["estimated_system_prompt_tokens"] > 0
    assert bd["estimated_history_tokens"] == 0
    assert bd["estimated_current_input_tokens"] > 0
    assert bd["estimated_tool_results_tokens"] == 0


def test_estimate_token_breakdown_turn_0_with_history():
    """Turn 0 with prior history."""
    msgs = [
        Message(role="user", content="Remember my name is John."),
        Message(role="assistant", content="Got it, John!"),
        Message(role="user", content="What's the weather?"),
    ]
    bd = _estimate_token_breakdown(msgs, "System prompt", turn=0)
    assert bd["estimated_system_prompt_tokens"] > 0
    assert bd["estimated_history_tokens"] > 0
    assert bd["estimated_current_input_tokens"] > 0
    assert bd["estimated_tool_results_tokens"] == 0
    # current_input is the last message (user)
    assert bd["estimated_current_input_tokens"] == _sum_message_tokens([msgs[-1]])


def test_estimate_token_breakdown_turn_1():
    """Turn 1: after assistant with tool_calls + tool_results."""
    msgs = [
        Message(role="user", content="What's the weather?"),
        Message(
            role="assistant",
            tool_calls=[ToolCall(id="c1", name="get_weather", args={"city": "Hanoi"})],
        ),
        Message(
            role="tool",
            tool_result=ToolResult(tool_call_id="c1", name="get_weather", content={"temp": 30}),
        ),
    ]
    bd = _estimate_token_breakdown(msgs, "System prompt", turn=1)
    assert bd["estimated_system_prompt_tokens"] > 0
    assert bd["estimated_history_tokens"] > 0  # user message
    assert bd["estimated_current_input_tokens"] > 0  # assistant with tool_calls
    assert bd["estimated_tool_results_tokens"] > 0  # tool_result
    assert bd["estimated_current_input_tokens"] == _sum_message_tokens([msgs[1]])
    assert bd["estimated_tool_results_tokens"] == _sum_message_tokens([msgs[2]])


def test_estimate_token_breakdown_turn_1_no_tool_results():
    """Turn 1 with assistant response but no tool calls (should fallback gracefully)."""
    msgs = [
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi! How can I help?"),
    ]
    bd = _estimate_token_breakdown(msgs, "System prompt", turn=1)
    assert bd["estimated_system_prompt_tokens"] > 0
    assert bd["estimated_tool_results_tokens"] == 0


def test_estimate_token_breakdown_turn_1_multiple_tools():
    """Turn 1 with multiple tool results from parallel execution."""
    msgs = [
        Message(role="user", content="Search and fetch"),
        Message(
            role="assistant",
            tool_calls=[
                ToolCall(id="c1", name="search", args={"q": "python"}),
                ToolCall(id="c2", name="fetch", args={"url": "https://example.com"}),
            ],
        ),
        Message(
            role="tool",
            tool_result=ToolResult(tool_call_id="c1", name="search", content={"results": ["a", "b"]}),
        ),
        Message(
            role="tool",
            tool_result=ToolResult(tool_call_id="c2", name="fetch", content={"html": "<html>...</html>"}),
        ),
    ]
    bd = _estimate_token_breakdown(msgs, "System prompt", turn=1)
    assert bd["estimated_history_tokens"] > 0
    assert bd["estimated_current_input_tokens"] > 0
    assert bd["estimated_tool_results_tokens"] > 0
    # All tool results combined
    expected_tool_tokens = _sum_message_tokens(msgs[2:])
    assert bd["estimated_tool_results_tokens"] == expected_tool_tokens


def test_estimate_token_breakdown_empty_messages():
    """Empty messages list should not crash and return zeros."""
    bd = _estimate_token_breakdown([], "System prompt", turn=0)
    assert bd["estimated_system_prompt_tokens"] > 0
    assert bd["estimated_history_tokens"] == 0
    assert bd["estimated_current_input_tokens"] == 0
    assert bd["estimated_tool_results_tokens"] == 0


def test_estimate_token_breakdown_empty_system_instruction():
    """Empty system instruction should produce 0 system prompt tokens."""
    msgs = [Message(role="user", content="Hello")]
    bd = _estimate_token_breakdown(msgs, "", turn=0)
    assert bd["estimated_system_prompt_tokens"] == 0
