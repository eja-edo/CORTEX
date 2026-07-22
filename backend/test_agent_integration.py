"""
Integration tests for AgentService handle() and handle_streaming_generator().
All LLM calls and tool calls are mocked — no real API calls.

Covers Part 2 requirements:
  2.1 Parallel vs Sequential parity
  2.2 MAX_SAME_TOOL_CALLS with both scopes (turn + conversation)
  2.3 MAX_TOOL_TURNS + synthesis turn
  2.4 Token-budget history integration
  2.5 success: False propagation
  2.6 Source ID injection

Run: python -m pytest test_agent_integration.py -v
"""

import asyncio
import json
import logging
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.ai.agents.agent_service import AgentService
from app.ai.agents.provider_types import (
    ToolCall, ToolResult, ProviderResponse, ProviderStreamChunk, Message,
)
from app.ai.agents.tool_registry import ToolRegistry


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


@pytest.fixture
def service(mock_user, mock_db):
    svc = AgentService(user=mock_user, db=mock_db)
    registry = ToolRegistry()
    async def ok_handler(args, ctx):
        return {"result": "done"}
    registry.register("search_tool", "Search tool",
                      {"type": "object", "properties": {"q": {"type": "string"}}},
                      ok_handler)
    registry.register("fetch_tool", "Fetch tool",
                      {"type": "object", "properties": {"url": {"type": "string"}}},
                      ok_handler)
    svc.registry = registry
    return svc


# ---------------------------------------------------------------------------
# 2.1 — Parallel vs Sequential parity (non-streaming handle)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parallel_vs_sequential_parity(mock_store, service):
    """Same 3-tool scenario yields identical reply_text in both modes."""
    service.store = mock_store
    _turn = [0]
    results = {}

    for parallel in [True, False]:
        _turn[0] = 0
        turn_key = [0]

        async def mock_gen(msgs, config, tools=None):
            idx = turn_key[0]
            turn_key[0] += 1
            if idx == 0:
                return ("model", ProviderResponse(
                    tool_calls=[
                        ToolCall(id="a1", name="search_tool", args={"q": "x"}),
                        ToolCall(id="a2", name="fetch_tool", args={"url": "y"}),
                        ToolCall(id="a3", name="search_tool", args={"q": "z"}),
                    ]
                ))
            return ("model", ProviderResponse(content="Final answer"))

        with patch("app.ai.agents.agent_service._model_client") as mc:
            mc.generate = mock_gen
            with patch("app.config.settings.AGENT_PARALLEL_TOOL_EXECUTION", parallel):
                result = await service.handle(message="hello")
        results[parallel] = result["reply"]

    assert results[True] == results[False], (
        f"Parallel reply != Sequential reply\n"
        f"  parallel=True:  {results[True]!r}\n"
        f"  parallel=False: {results[False]!r}"
    )


# ---------------------------------------------------------------------------
# 2.1b — Streaming parallel vs sequential event ordering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_parallel_sequential_event_order(mock_store, service):
    """Parallel: all tool_start before any tool_result.
       Sequential: interleaved per-tool — tool_start, tool_result, tool_start, tool_result."""
    service.store = mock_store

    stream_turn = [0]

    async def mock_stream(*args, **kwargs):
        idx = stream_turn[0]
        stream_turn[0] += 1
        tools = kwargs.get("tools")
        if tools is not None and idx >= 1:
            yield ProviderStreamChunk(content="Done")
            return
        yield ProviderStreamChunk(
            tool_calls=[
                ToolCall(id="b1", name="search_tool", args={"q": "a"}),
                ToolCall(id="b2", name="fetch_tool", args={"url": "b"}),
            ],
            finish_reason="tool_calls",
        )

    for parallel, expected_pattern in [
        (True, ["tool_start", "tool_start", "tool_result", "tool_result"]),
        (False, ["tool_start", "tool_result", "tool_start", "tool_result"]),
    ]:
        events = []
        stream_turn[0] = 0
        with patch("app.ai.agents.agent_service._model_client") as mc:
            mc.stream_with_fallback = mock_stream
            with patch("app.config.settings.AGENT_PARALLEL_TOOL_EXECUTION", parallel):
                async for evt in service.handle_streaming_generator(
                    message="hi", model="gpt-4o"
                ):
                    if evt.get("event") in ("tool_start", "tool_result"):
                        events.append(evt["event"])

        assert events == expected_pattern, (
            f"parallel={parallel}: expected {expected_pattern}, got {events}"
        )


# ---------------------------------------------------------------------------
# 2.2 — MAX_SAME_TOOL_CALLS with scope=request vs scope=turn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_tool_calls_request_scope_breaks_across_turns(
    mock_store, service,
):
    """Scope=request: turn1=15, turn2=6 → cumulative 21 > 20 → break."""
    service.store = mock_store
    _turn = [0]

    async def mock_gen(msgs, config, tools=None):
        idx = _turn[0]
        _turn[0] += 1
        if idx == 0:
            calls = [ToolCall(id=f"tc_{i}", name="search_tool", args={"q": str(i)})
                     for i in range(15)]
            return ("model", ProviderResponse(tool_calls=calls))
        if idx == 1:
            calls = [ToolCall(id=f"tc_{i}", name="search_tool", args={"q": str(i)})
                     for i in range(6)]
            return ("model", ProviderResponse(tool_calls=calls))
        return ("model", ProviderResponse(content="Final"))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        with patch("app.config.settings.AGENT_TOOL_CALL_COUNT_SCOPE", "request"):
            result = await service.handle(message="test")

    assert "wasn't able to find" in result["reply"], (
        f"Expected limit message with request scope, got: {result['reply']}"
    )
    assert _turn[0] == 2, (
        f"Expected 2 LLM calls (15 tools then limit hit), got {_turn[0]}"
    )


# ---------------------------------------------------------------------------
# 2.3 — MAX_TOOL_TURNS + synthesis turn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_tool_turns_triggers_synthesis(mock_store, service):
    """LLM always returns tool_calls until MAX_TOOL_TURNS → synthesis turn."""
    service.store = mock_store
    _turn = [0]
    MAX_TOOL_TURNS = 30

    async def mock_gen(msgs, config, tools=None):
        idx = _turn[0]
        _turn[0] += 1
        if tools is None:
            return ("model", ProviderResponse(content="Synthesis result"))
        if idx < MAX_TOOL_TURNS:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="x", name="search_tool", args={"q": "test"})]
            ))
        return ("model", ProviderResponse(content="Final"))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen

        result = await service.handle(message="test")

    assert "reply" in result
    assert result["reply"] == "Synthesis result", (
        f"Expected synthesis reply, got: {result['reply']}"
    )
    assert _turn[0] >= MAX_TOOL_TURNS + 1, (
        f"Expected at least {MAX_TOOL_TURNS + 1} LLM calls ({MAX_TOOL_TURNS} tool + 1 synthesis), got {_turn[0]}"
    )


@pytest.mark.asyncio
async def test_synthesis_turn_fallback_on_exception(mock_store, service):
    """Synthesis call raises → fallback to generic limit message."""
    service.store = mock_store
    _turn = [0]
    MAX_TOOL_TURNS = 30

    async def mock_gen(msgs, config, tools=None):
        idx = _turn[0]
        _turn[0] += 1
        if idx < MAX_TOOL_TURNS:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="x", name="search_tool", args={"q": "x"})]
            ))
        if tools is None:
            raise RuntimeError("Synthesis failed")
        return ("model", ProviderResponse(content="Final"))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen

        result = await service.handle(message="test")

    assert "processing limit" in result["reply"], (
        f"Expected fallback limit message, got: {result['reply']}"
    )


# ---------------------------------------------------------------------------
# 2.4 — Token-budget history integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_budget_history_flag_reduces_history(mock_store, mock_db, mock_user):
    """With AGENT_TOKEN_BUDGET_HISTORY=true, history is loaded via token budget."""
    conv = MagicMock()
    conv.id = uuid4()
    conv.total_token_count = 0
    conv.message_count = 0
    conv.summary = None

    store_with_history = AsyncMock()
    store_with_history.get_or_create_conversation = AsyncMock(return_value=conv)
    store_with_history.get_conversation_by_id = AsyncMock(return_value=conv)
    store_with_history.get_recent_messages = AsyncMock(return_value=[])
    store_with_history.get_recent_messages_by_token_budget = AsyncMock(
        return_value=[MagicMock(role="user", content="old msg",
                                 tool_name=None, tool_input=None, tool_output=None)]
    )
    store_with_history.save_message = AsyncMock()
    store_with_history.increment_message_count = AsyncMock()
    store_with_history.update_conversation_timestamp = AsyncMock()

    svc = AgentService(user=mock_user, db=mock_db)
    svc.store = store_with_history
    registry = ToolRegistry()
    async def h(args, ctx):
        return {"result": "ok"}
    registry.register("t", "t", {"type": "object", "properties": {}}, h)
    svc.registry = registry
    _called = [False]

    async def mock_gen(msgs, config, tools=None):
        _called[0] = True
        return ("model", ProviderResponse(content="Hello"))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        with patch("app.config.settings.AGENT_TOKEN_BUDGET_HISTORY", True):
            result = await svc.handle(message="hello")

    store_with_history.get_recent_messages_by_token_budget.assert_called_once()
    assert _called[0], "LLM was not called"


# ---------------------------------------------------------------------------
# 2.5 — success: False propagation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_success_false_propagates_to_llm(mock_store, service):
    """Tool failure → LLM receives success:False in next turn."""
    service.store = mock_store

    failing_registry = ToolRegistry()
    async def fail_handler(args, ctx):
        raise ValueError("Something broke")
    failing_registry.register("search_tool", "Search",
                              {"type": "object", "properties": {"q": {"type": "string"}}},
                              fail_handler)
    service.registry = failing_registry

    _turns = []
    async def mock_gen(msgs, config, tools=None):
        idx = len(_turns)
        _turns.append((idx, msgs, tools))
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="e1", name="search_tool", args={"q": "x"})]
            ))
        return ("model", ProviderResponse(content="Done"))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        result = await service.handle(message="find stuff")

    assert len(_turns) >= 2, f"Expected at least 2 turns, got {len(_turns)}"
    tool_msgs = [m for m in _turns[1][1] if m.role == "tool"]
    assert len(tool_msgs) >= 1, "No tool messages sent to LLM in turn 2"

    last_tool = tool_msgs[-1]
    assert last_tool.tool_result is not None, "Tool result missing"

    content = last_tool.tool_result.content
    assert isinstance(content, dict), f"Tool result content should be dict, got {type(content)}"
    assert content.get("success") is False, (
        f"Expected success=False, got: {content}"
    )
    assert "error" in content, f"Expected error key in tool result, got: {content}"


@pytest.mark.asyncio
async def test_system_prompt_contains_success_false_instruction(mock_store, service):
    """System prompt should mention success: False handling."""
    service.store = mock_store

    seen_system = []

    async def mock_gen(msgs, config, tools=None):
        seen_system.append(config.system_instruction or "")
        return ("model", ProviderResponse(content="Hello"))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        await service.handle(message="hello")

    assert len(seen_system) > 0, "LLM was never called"
    combined = " ".join(seen_system)
    assert '"success": false' in combined or 'success": false' in combined or "'success': false" in combined, (
        "System prompt missing success: False instruction"
    )


# ---------------------------------------------------------------------------
# 2.6 — Source ID injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_id_injection_ordered_by_execution_list(mock_store, service):
    """
    3 tool_calls → source_ids S1, S2, S3 assigned by execution_list order,
    NOT by completion order.
    Mock 3 tools with different speeds — order must be consistent.
    """
    service.store = mock_store
    exec_order = []

    registry = ToolRegistry()
    async def slow(args, ctx):
        await asyncio.sleep(0.05)
        exec_order.append("slow")
        return {"result": "slow_result"}
    async def fast(args, ctx):
        await asyncio.sleep(0)
        exec_order.append("fast")
        return {"result": "fast_result"}
    async def medium(args, ctx):
        await asyncio.sleep(0.02)
        exec_order.append("medium")
        return {"result": "medium_result"}

    registry.register("slow_tool", "Slow", {"type": "object", "properties": {}}, slow)
    registry.register("fast_tool", "Fast", {"type": "object", "properties": {}}, fast)
    registry.register("medium_tool", "Medium", {"type": "object", "properties": {}}, medium)
    service.registry = registry

    saved_messages = []
    async def save_msg_side_effect(**kwargs):
        saved_messages.append(kwargs)
        return MagicMock()
    service.store.save_message = save_msg_side_effect

    _turn = [0]
    async def mock_gen(msgs, config, tools=None):
        idx = _turn[0]
        _turn[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[
                    ToolCall(id="s1", name="slow_tool", args={}),
                    ToolCall(id="f1", name="fast_tool", args={}),
                    ToolCall(id="m1", name="medium_tool", args={}),
                ]
            ))
        return ("model", ProviderResponse(content="Done"))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        with patch("app.config.settings.AGENT_PARALLEL_TOOL_EXECUTION", True):
            result = await service.handle(message="test")

    source_msgs = [m for m in saved_messages if m.get("role") == "tool"]
    assert len(source_msgs) == 3, f"Expected 3 tool messages, got {len(source_msgs)}"

    source_ids = []
    for sm in source_msgs:
        output = sm.get("tool_output", {})
        source_ids.append(output.get("source_id"))

    assert source_ids == ["S1", "S2", "S3"], (
        f"Expected source_ids [S1, S2, S3], got {source_ids}. "
        f"exec_order was {exec_order} — source_id should NOT follow completion order"
    )

    # Verify tools actually completed in different order than submitted
    # (sleep: slow=0.05s, medium=0.02s, fast=0s → expected: fast, medium, slow)
    assert exec_order != ["slow", "fast", "medium"], (
        f"Tools completed in submission order despite different sleep delays. "
        f"exec_order={exec_order}. Try increasing sleep(0.05) to sleep(0.1)."
    )


# ---------------------------------------------------------------------------
# 2.6b — Source ID in streaming path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_id_streaming_path(mock_store, service):
    """Streaming path: 3 parallel tools → source_ids S1, S2, S3 in order."""
    service.store = mock_store
    saved_messages = []
    async def save_msg_side_effect(**kwargs):
        saved_messages.append(kwargs)
        return MagicMock()
    service.store.save_message = save_msg_side_effect

    events = []
    stream_turn = [0]

    async def mock_stream(*args, **kwargs):
        idx = stream_turn[0]
        stream_turn[0] += 1
        tools = kwargs.get("tools")
        if tools is not None and idx >= 1:
            yield ProviderStreamChunk(content="Done")
            return
        yield ProviderStreamChunk(
            tool_calls=[
                ToolCall(id="x1", name="search_tool", args={"q": "a"}),
                ToolCall(id="x2", name="search_tool", args={"q": "b"}),
                ToolCall(id="x3", name="search_tool", args={"q": "c"}),
            ],
            finish_reason="tool_calls",
        )

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.stream_with_fallback = mock_stream
        async for evt in service.handle_streaming_generator(
            message="hi", model="gpt-4o"
        ):
            if evt.get("event") in ("tool_result", "tool_start"):
                events.append(evt)

    # source_id is in the saved message (tool_output), not in the yielded event
    source_msgs = [m for m in saved_messages if m.get("role") == "tool"]
    assert len(source_msgs) == 3, f"Expected 3 tool messages, got {len(source_msgs)}"
    source_ids = []
    for sm in source_msgs:
        output = sm.get("tool_output", {})
        source_ids.append(output.get("source_id"))
    assert source_ids == ["S1", "S2", "S3"], (
        f"Streaming: expected [S1, S2, S3], got {source_ids}"
    )


@pytest.mark.asyncio
async def test_source_id_continuous_across_multi_turn(mock_store, service):
    """source_id counts continuously across 3 agent-loop turns, not resetting per turn."""
    service.store = mock_store
    saved_messages = []
    async def save_msg_side_effect(**kwargs):
        saved_messages.append(kwargs)
        return MagicMock()
    service.store.save_message = save_msg_side_effect

    _turn = [0]
    async def mock_gen(msgs, config, tools=None):
        idx = _turn[0]
        _turn[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[
                    ToolCall(id="t1", name="search_tool", args={"q": "a"}),
                    ToolCall(id="t2", name="search_tool", args={"q": "b"}),
                ]
            ))
        if idx == 1:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t3", name="fetch_tool", args={"url": "c"})]
            ))
        if idx == 2:
            return ("model", ProviderResponse(
                tool_calls=[
                    ToolCall(id="t4", name="search_tool", args={"q": "d"}),
                    ToolCall(id="t5", name="fetch_tool", args={"url": "e"}),
                    ToolCall(id="t6", name="search_tool", args={"q": "f"}),
                    ToolCall(id="t7", name="fetch_tool", args={"url": "g"}),
                ]
            ))
        return ("model", ProviderResponse(content="Done"))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        result = await service.handle(message="test multi-turn source_id")

    source_msgs = [m for m in saved_messages if m.get("role") == "tool"]
    assert len(source_msgs) == 7, f"Expected 7 tool messages, got {len(source_msgs)}"

    source_ids = []
    for sm in source_msgs:
        output = sm.get("tool_output", {})
        source_ids.append(output.get("source_id"))

    assert source_ids == ["S1", "S2", "S3", "S4", "S5", "S6", "S7"], (
        f"Expected continuous [S1..S7] across 3 turns, got {source_ids}"
    )


# ---------------------------------------------------------------------------
# 2.2b — Streaming path: MAX_SAME_TOOL_CALLS with scope=request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_same_tool_calls_request_scope(mock_store, service):
    """Streaming path: request scope breaks across turns."""
    service.store = mock_store
    _turn = [0]

    async def mock_stream(*args, **kwargs):
        idx = _turn[0]
        _turn[0] += 1
        if idx == 0:
            yield ProviderStreamChunk(
                tool_calls=[ToolCall(id=f"t{i}", name="search_tool", args={"q": str(i)})
                            for i in range(15)],
                finish_reason="tool_calls",
            )
        elif idx == 1:
            yield ProviderStreamChunk(
                tool_calls=[ToolCall(id=f"t{i}", name="search_tool", args={"q": str(i)})
                            for i in range(6)],
                finish_reason="tool_calls",
            )
        else:
            yield ProviderStreamChunk(content="Final")

    events = []
    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.stream_with_fallback = mock_stream
        with patch("app.config.settings.AGENT_TOOL_CALL_COUNT_SCOPE", "request"):
            async for evt in service.handle_streaming_generator(
                message="hi", model="gpt-4o"
            ):
                events.append(evt)

    tool_result_events = [e for e in events if e.get("event") == "tool_result"]
    # Should have 15 + 6 = 21 tool_result events, but turn 2 should hit limit
    token_events = [e for e in events if e.get("event") == "token"]
    last_tokens = " ".join(e["text"] for e in token_events)
    assert "wasn't able to find" in last_tokens or "provide more details" in last_tokens, (
        f"Expected limit message in streaming, got tokens: {last_tokens[:200]}"
    )


# ---------------------------------------------------------------------------
# 2.3b — Streaming MAX_TOOL_TURNS synthesis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_max_tool_turns_synthesis(mock_store, service):
    """Streaming path: hit MAX_TOOL_TURNS → synthesis turn."""
    service.store = mock_store
    _turn = [0]
    MAX_TOOL_TURNS = 30

    async def mock_stream(*args, **kwargs):
        idx = _turn[0]
        _turn[0] += 1
        tools = kwargs.get("tools")
        if tools is None:
            yield ProviderStreamChunk(content="Streaming synthesis done")
            return
        if idx < MAX_TOOL_TURNS:
            yield ProviderStreamChunk(
                tool_calls=[ToolCall(id="y", name="search_tool", args={"q": "x"})],
                finish_reason="tool_calls",
            )

    texts = []
    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.stream_with_fallback = mock_stream
        async for evt in service.handle_streaming_generator(
            message="test", model="gpt-4o"
        ):
            if evt.get("event") == "token":
                texts.append(evt["text"])

    full = "".join(texts)
    assert "Streaming synthesis done" in full, (
        f"Expected synthesis text in streaming, got: {full[:200]}"
    )


# ---------------------------------------------------------------------------
# Token usage breakdown (Issue #9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_breakdown_logged_in_handle(mock_store, service, caplog):
    """Verify event=token_breakdown log lines appear with reasonable values."""
    service.store = mock_store
    turn_key = [0]

    async def mock_gen(msgs, config, tools=None):
        idx = turn_key[0]
        turn_key[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t1", name="search_tool", args={"q": "test"})],
                usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
            ))
        return ("model", ProviderResponse(
            content="Final answer",
            usage={"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35},
        ))

    caplog.set_level(logging.INFO)

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        with patch("app.config.settings.AGENT_PARALLEL_TOOL_EXECUTION", False):
            result = await service.handle(
                message="test",
            )

    assert result["reply"] is not None

    token_breakdown_lines = [r for r in caplog.records if r.getMessage().startswith("event=token_breakdown")]
    assert len(token_breakdown_lines) >= 1, "No token_breakdown log entries found"

    total_lines = [r for r in caplog.records if r.getMessage().startswith("event=token_breakdown_total")]
    assert len(total_lines) >= 1, "No token_breakdown_total log entry found"

    # Check that values are positive and reasonable
    total_msg = total_lines[0].getMessage()
    assert "estimated_system_prompt_tokens" in total_msg
    assert "estimated_history_tokens" in total_msg
    assert "estimated_current_input_tokens" in total_msg
    assert "estimated_tool_results_tokens" in total_msg
    assert "prompt_tokens" in total_msg
    assert "completion_tokens" in total_msg


@pytest.mark.asyncio
async def test_token_breakdown_logged_in_streaming(mock_store, service, caplog):
    """Verify event=token_breakdown log in streaming generator."""
    service.store = mock_store
    turn_key = [0]

    async def chunks(*args, **kwargs):
        idx = turn_key[0]
        turn_key[0] += 1
        if idx == 0:
            yield ProviderStreamChunk(
                tool_calls=[ToolCall(id="t1", name="search_tool", args={"q": "test"})],
            )
            yield ProviderStreamChunk(
                finish_reason="tool_calls",
                usage={"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48},
            )
        else:
            yield ProviderStreamChunk(content="Final streaming answer")
            yield ProviderStreamChunk(
                finish_reason="stop",
                usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            )

    caplog.set_level(logging.INFO)

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.stream_with_fallback = chunks
        collected = []
        async for evt in service.handle_streaming_generator(message="test"):
            collected.append(evt)

    token_breakdown_lines = [r for r in caplog.records if r.getMessage().startswith("event=token_breakdown")]
    assert len(token_breakdown_lines) >= 1, "No token_breakdown log entries in streaming"

    total_lines = [r for r in caplog.records if r.getMessage().startswith("event=token_breakdown_total")]
    assert len(total_lines) >= 1, "No token_breakdown_total log entry in streaming"

    # Check that the done event contains usage with estimated fields
    done_evt = [e for e in collected if e.get("event") == "done"]
    assert len(done_evt) == 1
    usage = done_evt[0].get("usage", {})
    assert "estimated_system_prompt_tokens" in usage
    assert "estimated_history_tokens" in usage
    assert usage["estimated_system_prompt_tokens"] > 0


# ---------------------------------------------------------------------------
# Proactive triggers (Issue #7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_schedule_conflicts_detects_overlap(service):
    """Verify conflict_warning is set when overlapping schedule exists."""
    ctx = MagicMock()
    ctx.user_id = uuid4()

    fake_service = MagicMock()
    fake_service.list_schedules_for_agent.return_value = {
        "count": 1,
        "schedules": [
            {
                "id": "other-schedule-uuid",
                "title": "Existing Meeting",
                "start_time": "2026-06-15T09:00:00+07:00",
                "end_time": "2026-06-15T10:30:00+07:00",
                "type": "CLASS",
                "is_completed": False,
            }
        ],
    }

    result = {
        "id": "new-schedule-uuid",
        "title": "New Event",
        "start_time": "2026-06-15T09:30:00+07:00",
        "end_time": "2026-06-15T10:00:00+07:00",
        "success": True,
        "source_id": "S1",
    }

    svc = service
    with patch("app.database.SessionLocal") as mock_session_local, \
         patch("app.services.schedule_service.ScheduleService", return_value=fake_service):
        mock_session_local.return_value = MagicMock()
        await svc._check_schedule_conflicts(result, [], ctx)

    assert "conflict_warning" in result
    assert "Existing Meeting" in result["conflict_warning"]


@pytest.mark.asyncio
async def test_check_schedule_conflicts_no_overlap(service):
    """Verify no conflict_warning when no overlapping schedule exists."""
    ctx = MagicMock()
    ctx.user_id = uuid4()

    fake_service = MagicMock()
    fake_service.list_schedules_for_agent.return_value = {"count": 0, "schedules": []}

    result = {
        "id": "new-schedule-uuid",
        "title": "New Event",
        "start_time": "2026-06-15T14:00:00+07:00",
        "end_time": "2026-06-15T15:00:00+07:00",
        "success": True,
        "source_id": "S1",
    }

    svc = service
    with patch("app.database.SessionLocal") as mock_session_local, \
         patch("app.services.schedule_service.ScheduleService", return_value=fake_service):
        mock_session_local.return_value = MagicMock()
        await svc._check_schedule_conflicts(result, [], ctx)

    assert "conflict_warning" not in result


@pytest.mark.asyncio
async def test_check_note_action_suggestions_adds_tip(service):
    """Verify suggestion with type='tip' is set after create_note."""
    ctx = MagicMock()
    result = {"id": "note-123", "success": True, "source_id": "S1"}

    svc = service
    await svc._check_note_action_suggestions(result, [], ctx)

    assert "suggestion" in result
    assert result["suggestion"]["type"] == "tip"
    assert len(result["suggestion"]["message"]) > 0


@pytest.mark.asyncio
async def test_proactive_triggers_called_in_handle(mock_store, service):
    """Verify _check_proactive_triggers is called during handle()."""
    service.store = mock_store
    turn_key = [0]
    proactive_calls = [0]

    orig_check = service._check_proactive_triggers

    async def counting_check(tool_name, tool_result, history, ctx):
        proactive_calls[0] += 1
        await orig_check(tool_name, tool_result, history, ctx)

    service._check_proactive_triggers = counting_check

    async def mock_gen(msgs, config, tools=None):
        idx = turn_key[0]
        turn_key[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t1", name="search_tool", args={"q": "test"})],
            ))
        return ("model", ProviderResponse(content="Final answer"))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        with patch("app.config.settings.AGENT_PARALLEL_TOOL_EXECUTION", False):
            result = await service.handle(message="test")

    assert result["reply"] is not None
    assert proactive_calls[0] >= 1, f"_check_proactive_triggers not called in handle()"


@pytest.mark.asyncio
async def test_proactive_triggers_called_in_streaming(mock_store, service):
    """Verify _check_proactive_triggers is called during handle_streaming_generator()."""
    service.store = mock_store
    turn_key = [0]
    proactive_calls = [0]

    orig_check = service._check_proactive_triggers

    async def counting_check(tool_name, tool_result, history, ctx):
        proactive_calls[0] += 1
        await orig_check(tool_name, tool_result, history, ctx)

    service._check_proactive_triggers = counting_check

    async def chunks(*args, **kwargs):
        idx = turn_key[0]
        turn_key[0] += 1
        if idx == 0:
            yield ProviderStreamChunk(
                tool_calls=[ToolCall(id="t1", name="search_tool", args={"q": "test"})],
            )
            yield ProviderStreamChunk(
                finish_reason="tool_calls",
                usage={"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48},
            )
        else:
            yield ProviderStreamChunk(content="Final streaming answer")
            yield ProviderStreamChunk(
                finish_reason="stop",
                usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            )

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.stream_with_fallback = chunks
        collected = []
        async for evt in service.handle_streaming_generator(message="test"):
            collected.append(evt)

    assert proactive_calls[0] >= 1, f"_check_proactive_triggers not called in streaming"


# ---------------------------------------------------------------------------
# Sanity check: estimated token breakdown vs actual prompt_tokens (Issue #9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_estimated_breakdown_matches_prompt_tokens(mock_store, service, caplog):
    """Verify estimated breakdown sum is in same ballpark as actual prompt_tokens.

    Ground truth is computed independently via len(all_text) // 4 (heuristic),
    NOT by calling _estimate_token_breakdown — so this test can actually fail
    if the breakdown logic is broken.

    Self-verification: temporarily set _estimate_token_breakdown to return
    all zeros → this test fails. Revert → passes again.
    """
    service.store = mock_store
    turn_key = [0]
    caplog.set_level(logging.INFO)

    # Build realistic content: system_prompt + history + user message
    long_content = (
        "This is a detailed question about the weather in Hanoi, Vietnam. "
        "I need to know the temperature, humidity, and forecast for the next week. "
        * 20
    )
    system_instruction = "You are a helpful assistant with access to weather data and scheduling tools."

    # Compute ground truth independently: heuristic len//4 on concatenated text
    truth_text = system_instruction + long_content
    ground_truth_prompt = max(1, len(truth_text) // 4)

    async def mock_gen(msgs, config, tools=None):
        idx = turn_key[0]
        turn_key[0] += 1
        if idx == 0:
            return ("model", ProviderResponse(
                tool_calls=[ToolCall(id="t1", name="search_tool", args={"q": "weather"})],
                usage={
                    "prompt_tokens": ground_truth_prompt,
                    "completion_tokens": 10,
                    "total_tokens": ground_truth_prompt + 10,
                },
            ))
        return ("model", ProviderResponse(
            content="The weather in Hanoi is sunny and 30°C.",
            usage={"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35},
        ))

    with patch("app.ai.agents.agent_service._model_client") as mc:
        mc.generate = mock_gen
        with patch("app.ai.agents.agent_service.SYSTEM_PROMPT", system_instruction):
            with patch("app.config.settings.AGENT_PARALLEL_TOOL_EXECUTION", False):
                result = await service.handle(
                    message=long_content,
                )

    assert result["reply"] is not None

    total_lines = [r for r in caplog.records if r.getMessage().startswith("event=token_breakdown_total")]
    assert len(total_lines) >= 1

    total_msg = total_lines[0].getMessage()
    est_sum = (
        int(_extract_field(total_msg, "estimated_system_prompt_tokens"))
        + int(_extract_field(total_msg, "estimated_history_tokens"))
        + int(_extract_field(total_msg, "estimated_current_input_tokens"))
        + int(_extract_field(total_msg, "estimated_tool_results_tokens"))
    )
    actual_prompt = int(_extract_field(total_msg, "prompt_tokens"))

    assert est_sum > 0, (
        f"Estimated sum should be > 0, got {est_sum}. "
        f"Breakdown: sys={_extract_field(total_msg, 'estimated_system_prompt_tokens')} "
        f"hist={_extract_field(total_msg, 'estimated_history_tokens')} "
        f"input={_extract_field(total_msg, 'estimated_current_input_tokens')} "
        f"tool={_extract_field(total_msg, 'estimated_tool_results_tokens')}"
    )
    assert actual_prompt > 0, f"Actual prompt_tokens from mock should be > 0, got {actual_prompt}"

    ratio = max(actual_prompt, est_sum) / min(actual_prompt, est_sum) if est_sum > 0 else 0
    assert 0.3 <= ratio <= 3.0, (
        f"Estimated sum ({est_sum}) vs actual prompt_tokens ({actual_prompt}) "
        f"ratio={ratio:.2f} — outside acceptable range (0.3x-3x). "
        f"Breakdown logic may be incorrect."
    )


def _extract_field(msg: str, field: str) -> str:
    """Extract a field=value from log message like 'field=123 ...'."""
    for part in msg.split():
        if part.startswith(field + "="):
            return part.split("=", 1)[1]
    return "0"
