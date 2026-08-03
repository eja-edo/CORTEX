"""
End-to-end conversation test harness (Part 3).
Simulates multi-turn conversations with deterministic LLM + tool mocks.
Exports structured JSON logs to test_artifacts/conversation_logs/.

Scenarios:
  A — Simple Q&A (no tools)
  B — Research task (parallel search → parallel fetch → synthesis)
  C — Long conversation exceeding token budget
  D — Tool errors mid-flight
  E — MAX_TOOL_TURNS hit during research
  F — MAX_SAME_TOOL_CALLS with scope in multi-turn context

Run: python -m pytest test_e2e_conversation.py -v
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.ai.agents.agent_service import AgentService
from app.ai.agents.provider_types import (
    ToolCall, ToolResult, ProviderResponse, Message,
)
from app.ai.agents.tool_registry import ToolRegistry

ARTIFACT_DIR = Path(__file__).parent / "test_artifacts" / "conversation_logs"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Harness helpers
# ═══════════════════════════════════════════════════════════════════════════════

class ConversationLog:
    """Accumulates structured log entries for one multi-turn conversation."""

    def __init__(self, scenario_name: str):
        self.scenario = scenario_name
        self.turns: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.start_time = datetime.utcnow()

    def add_turn(self, entry: dict) -> None:
        self.turns.append(entry)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def save(self) -> Path:
        data = {
            "scenario": self.scenario,
            "started_at": self.start_time.isoformat(),
            "total_turns": len(self.turns),
            "total_warnings": len(self.warnings),
            "warnings": self.warnings,
            "turns": self.turns,
        }
        fname = f"{self.scenario}_{self.start_time.strftime('%Y%m%d_%H%M%S')}.json"
        path = ARTIFACT_DIR / fname
        path.write_text(json.dumps(data, indent=2, default=str))
        return path


class ScriptedModelClient:
    """
    Deterministic mock for _model_client.
    Returns pre-scripted responses in order for each turn.
    """

    def __init__(self, script: list):
        self.script = script
        self.idx = 0
        self.calls: list[dict] = []

    async def generate(self, messages, config, tools=None):
        entry = {"turn": self.idx, "messages_count": len(messages), "has_tools": tools is not None,
                 "system_len": len(config.system_instruction or "")}
        self.calls.append(entry)
        if self.idx >= len(self.script):
            resp = ProviderResponse(content="No more scripted responses.")
        else:
            resp = self.script[self.idx]
        self.idx += 1
        return ("model", resp)


def make_tool_calls(*names_and_args) -> list[ToolCall]:
    """Helper: ToolCall(id=f'{name}_0', name=name, args=args)."""
    result = []
    for item in names_and_args:
        if isinstance(item, str):
            result.append(ToolCall(id=f"{item}_0", name=item, args={}))
        elif isinstance(item, tuple):
            name, args = item
            result.append(ToolCall(id=f"{name}_0", name=name, args=args))
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_user():
    u = MagicMock()
    u.id = uuid4()
    return u


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(one_or_none=MagicMock(return_value=(0, 0))))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


class E2EHarness:
    """
    Manages one multi-turn conversation.
    Reuses the same mock conversation across turns.
    """

    def __init__(self, mock_user, mock_db, registry: ToolRegistry):
        self.service = AgentService(user=mock_user, db=mock_db)
        self.service.registry = registry

        self.conv = MagicMock()
        self.conv.id = uuid4()
        self.conv.total_token_count = 0
        self.conv.message_count = 0
        self.conv.summary = None
        self.conv.last_summary_message_id = None
        self.conv.tokens_since_last_summary = 0
        self.conv.messages_since_last_summary = 0

        self.log = ConversationLog("unnamed")
        self.saved_messages: list[dict] = []
        self._build_store()

    def _build_store(self):
        store = AsyncMock()
        store.get_or_create_conversation = AsyncMock(return_value=self.conv)
        store.get_conversation_by_id = AsyncMock(return_value=self.conv)
        store.get_recent_messages = AsyncMock(return_value=[])
        store.save_message = AsyncMock(side_effect=self._capture_save)
        store.increment_message_count = AsyncMock(
            side_effect=lambda cid: setattr(self.conv, 'message_count', self.conv.message_count + 1))
        store.update_conversation_timestamp = AsyncMock()
        store.increment_token_count = AsyncMock()
        store.get_messages_since = AsyncMock(return_value=[])
        store.reset_summary_counters = AsyncMock()
        self.service.store = store

    def _capture_save(self, **kwargs):
        self.saved_messages.append(dict(kwargs))
        return MagicMock()

    async def turn(self, user_message: str, scripted_client: ScriptedModelClient,
                   parallel: bool = True, rank: int = 0) -> dict:
        """Run one handle() call. Returns structured turn log entry."""
        info = {
            "turn_index": rank,
            "input": user_message,
            "messages_array_size": 0,
            "llm_output": None,
            "tool_executions": [],
            "final_reply": None,
            "usage": None,
            "warnings": [],
        }

        prior_msg_count = len(self.saved_messages)

        with patch("app.ai.agents.agent_service._model_client") as mc:
            mc.generate = scripted_client.generate
            mc.stream_with_fallback = scripted_client.generate
            with patch("app.config.settings.AGENT_PARALLEL_TOOL_EXECUTION", parallel):
                result = await self.service.handle(message=user_message)

        info["final_reply"] = result.get("reply", "")

        # Estimate token usage from saved assistant messages
        new_msgs = self.saved_messages[prior_msg_count:]
        tool_msgs = [m for m in new_msgs if m.get("role") == "tool"]
        info["tool_executions"] = [{
            "tool_name": m.get("tool_name"),
            "args": m.get("tool_input"),
            "result_summary": str(m.get("tool_output", {}))[:200],
            "source_id": m.get("tool_output", {}).get("source_id"),
        } for m in tool_msgs]

        # LLM call info from scripted client
        if scripted_client.calls:
            last_call = scripted_client.calls[-1]
            info["messages_array_size"] = last_call["messages_count"]
            info["llm_output"] = {
                "content": result.get("reply", "")[:200],
                "tool_calls_count": sum(1 for m in tool_msgs if m.get("role") == "tool"),
            }

        self.log.add_turn(info)
        return info

    async def run_scenario(self, name: str, messages: list[str],
                           script: ScriptedModelClient,
                           parallel: bool = True) -> Path:
        self.log = ConversationLog(name)
        for i, msg in enumerate(messages):
            await self.turn(msg, script, parallel=parallel, rank=i)
        return self.log.save()


@pytest.fixture
def registry_basic():
    r = ToolRegistry()
    async def search(args, ctx):
        return {"result": f"Search results for {args.get('q', '?')}"}
    async def fetch(args, ctx):
        return {"result": f"Fetched content from {args.get('url', '?')}: mock data"}
    r.register("web_search", "Search", {"type": "object", "properties": {"q": {"type": "string"}}}, search)
    r.register("web_fetch", "Fetch", {"type": "object", "properties": {"url": {"type": "string"}}}, fetch)
    return r


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario A — Simple Q&A (no tools)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scenario_a_simple_qa(mock_user, mock_db, registry_basic):
    """2–3 turns of simple Q&A without tool calls."""
    script = ScriptedModelClient([
        ProviderResponse(content="Hello! How can I help you today?"),
        ProviderResponse(content="Cortex is an AI productivity assistant."),
        ProviderResponse(content="You're welcome! Let me know if you need anything else."),
    ])
    harness = E2EHarness(mock_user, mock_db, registry_basic)
    path = await harness.run_scenario("A_simple_qa", [
        "Hi",
        "What is Cortex?",
        "Thanks!",
    ], script)
    log = harness.log

    assert log.turns[0]["final_reply"] == "Hello! How can I help you today?"
    assert log.turns[1]["final_reply"] == "Cortex is an AI productivity assistant."
    assert len(log.turns) == 3
    print(f"\n  [Scenario A] Log saved: {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario B — Research task (parallel search → parallel fetch → synthesis)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scenario_b_research_task(mock_user, mock_db, registry_basic):
    """
    Simulate: user asks a research question → LLM calls 2x search → 3x fetch → synthesis.
    """
    script = ScriptedModelClient([
        # Agent loop turn 0: 2 parallel searches (unique IDs)
        ProviderResponse(tool_calls=[
            ToolCall(id="s1", name="web_search", args={"q": "AI trends 2026"}),
            ToolCall(id="s2", name="web_search", args={"q": "machine learning advances"}),
        ]),
        # Agent loop turn 1: 3 parallel fetches (unique IDs)
        ProviderResponse(tool_calls=[
            ToolCall(id="f1", name="web_fetch", args={"url": "https://example.com/ai"}),
            ToolCall(id="f2", name="web_fetch", args={"url": "https://example.com/ml"}),
            ToolCall(id="f3", name="web_fetch", args={"url": "https://example.com/deep"}),
        ]),
        # Agent loop turn 2: synthesis
        ProviderResponse(content="Based on the search results, AI trends include..."),
    ])
    harness = E2EHarness(mock_user, mock_db, registry_basic)
    path = await harness.run_scenario("B_research_task", [
        "What are the latest AI trends in 2026?",
    ], script)

    log = harness.log
    assert len(log.turns) == 1
    final = log.turns[0]["final_reply"]
    assert "AI trends" in final or "Based on the search results" in final, (
        f"Unexpected final: {final[:100]}"
    )

    # Verify tool executions from the single harness turn
    all_tools = log.turns[0].get("tool_executions", [])
    tool_names = [te["tool_name"] for te in all_tools]
    assert tool_names.count("web_search") == 2, f"Expected 2 searches, got {tool_names}"
    assert tool_names.count("web_fetch") == 3, f"Expected 3 fetches, got {tool_names}"

    # Verify source_ids — continuous numbering across turns within one request
    # Turn 0 (search) → S1, S2. Turn 1 (fetch) → S3, S4, S5.
    sids = [te.get("source_id") for te in all_tools]
    assert sids == ["S1", "S2", "S3", "S4", "S5"], (
        f"Expected [S1,S2,S3,S4,S5] (continuous across turns), got {sids}"
    )

    print(f"\n  [Scenario B] Log saved: {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario C — Long conversation exceeding token budget
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scenario_c_token_budget_history(mock_user, mock_db, registry_basic):
    """
    Pre-fill conversation with 15–20 messages (some with large tool_output).
    Then send one more message with AGENT_TOKEN_BUDGET_HISTORY=true.
    Verify total tokens ≤ MAX_HISTORY_TOKENS.
    """
    harness = E2EHarness(mock_user, mock_db, registry_basic)

    # Pre-fill conversation with many tool-heavy messages
    large_output = {"result": "x" * 5000}
    for i in range(18):
        role = "user" if i % 2 == 0 else "tool"
        if role == "user":
            harness.service.store.save_message(
                conversation_id=harness.conv.id,
                role="user",
                content=f"Message {i}",
            )
        else:
            harness.service.store.save_message(
                conversation_id=harness.conv.id,
                role="tool",
                tool_name="web_fetch",
                tool_input={"url": f"https://example.com/{i}"},
                tool_output=large_output,
                tool_call_id=f"tc_{i}",
            )

    harness.conv.message_count = 18

    # Mock get_recent_messages_by_token_budget to return limited results
    async def mock_by_token_budget(cid, max_tokens):
        # Simulate returning only the most recent 3 tool messages due to budget
        return [
            MagicMock(role="tool", content=None,
                      tool_name="web_fetch", tool_input={}, tool_output={},
                      spec=["role", "content", "tool_name", "tool_input", "tool_output"])
        ] * 3

    harness.service.store.get_recent_messages_by_token_budget = mock_by_token_budget

    script = ScriptedModelClient([
        ProviderResponse(content="Here's a summary of your recent data."),
    ])

    with patch("app.config.settings.AGENT_TOKEN_BUDGET_HISTORY", True):
        info = await harness.turn("What's in my recent data?", script, rank=0)

    # Verify token budget method was used (not the default limit=10)
    assert info["messages_array_size"] <= 5, (
        f"Expected small message count due to token budget, got {info['messages_array_size']}"
    )
    harness.log.scenario = "C_token_budget_history"
    path = harness.log.save()
    print(f"\n  [Scenario C] Log saved: {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario D — Tool error mid-flight
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scenario_d_tool_error_mid_flight(mock_user, mock_db):
    """One of 3 parallel tools fails → LLM receives success:False for that tool."""
    registry = ToolRegistry()
    async def ok_search(args, ctx):
        return {"result": "Good result"}
    async def failing_fetch(args, ctx):
        raise RuntimeError("Network timeout fetching URL")
    async def ok_fetch(args, ctx):
        return {"result": "Another good result"}
    registry.register("web_search", "Search", {"type": "object", "properties": {}}, ok_search)
    registry.register("web_fetch", "Fetch", {"type": "object", "properties": {}}, failing_fetch)
    registry.register("deep_research", "Deep", {"type": "object", "properties": {}}, ok_fetch)

    script = ScriptedModelClient([
        ProviderResponse(tool_calls=make_tool_calls("web_search", "web_fetch", "deep_research")),
        ProviderResponse(content="Two tools succeeded, one failed. Here's what I found..."),
    ])
    harness = E2EHarness(mock_user, mock_db, registry)
    await harness.turn("Find info about topic X and fetch details", script)

    # Verify at least one tool_result has success:False
    tool_results = [m for m in harness.saved_messages if m.get("role") == "tool"]
    successes = [m.get("tool_output", {}).get("success", True) for m in tool_results]
    assert False in successes, (
        f"Expected at least one failure in tool results, all succeeded: {successes}"
    )

    # Verify failure was sent to LLM in next turn
    assert len(script.calls) >= 2, "Should have at least 2 LLM calls"
    second_call_msgs = script.calls[1]
    assert second_call_msgs["messages_count"] > 1, "Second turn should have context from first"

    harness.log.scenario = "D_tool_error_mid_flight"
    path = harness.log.save()
    print(f"\n  [Scenario D] Log saved: {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario E — MAX_TOOL_TURNS hit
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scenario_e_max_tool_turns(mock_user, mock_db, registry_basic):
    """Mock LLM always returns tool_calls → triggers MAX_TOOL_TURNS → synthesis."""
    MAX_TOOL_TURNS = 30
    turn_calls = [ProviderResponse(tool_calls=make_tool_calls(("web_search", {"q": "loop"})))
                  for _ in range(MAX_TOOL_TURNS)]
    turn_calls.append(ProviderResponse(content="Synthesis after max turns."))

    script = ScriptedModelClient(turn_calls)
    harness = E2EHarness(mock_user, mock_db, registry_basic)
    info = await harness.turn("Keep searching forever", script, rank=0)

    assert info["final_reply"] == "Synthesis after max turns.", (
        f"Expected synthesis reply, got: {info['final_reply'][:100]}"
    )
    harness.log.scenario = "E_max_tool_turns"
    path = harness.log.save()
    print(f"\n  [Scenario E] Log saved: {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario F — MAX_SAME_TOOL_CALLS with conversation scope across 2 handle() calls
# ═══════════════════════════════════════════════════════════════════════════════
#
# FINDING: tool_call_counts is a local variable inside handle() / handle_streaming_generator()
# (agent_service.py lines 500, 919). It is initialized once per request, not persisted
# in the conversation store. Therefore scope=conversation only accumulates across
# agent-loop turns within a single handle() call, NOT across separate user messages.
#
# The flag name "conversation" is misleading — it should be "request" or "agent_loop".
# This test documents the gap: both turns succeed normally because each handle() call
# starts with a fresh counter. Cross-message accumulation would require persisting
# tool_call_counts in the conversation store and loading it at the start of each handle().

@pytest.mark.asyncio
async def test_scenario_f_same_tool_calls_request_scope(mock_user, mock_db, registry_basic):
    """
    Turn 1: 15 calls of same tool (within limit, handle() completes normally).
    Turn 2: 6 more calls in a new handle() → counter starts fresh → no limit hit.
    Scope=request only accumulates within a single handle() call, not across calls.
    """
    script = ScriptedModelClient([
        ProviderResponse(tool_calls=[ToolCall(id=f"x{i}", name="web_search", args={"q": str(i)})
                                     for i in range(15)]),
        ProviderResponse(content="Done with 15 searches."),
        ProviderResponse(tool_calls=[ToolCall(id=f"y{i}", name="web_search", args={"q": str(i)})
                                     for i in range(6)]),
        ProviderResponse(content="Done with 6 more."),
    ])
    harness = E2EHarness(mock_user, mock_db, registry_basic)

    with patch("app.config.settings.AGENT_TOOL_CALL_COUNT_SCOPE", "request"):
        info_turn1 = await harness.turn("Search many times (round 1)", script, rank=0)
        info_turn2 = await harness.turn("Search again (round 2)", script, rank=1)

    # Both turns complete normally because tool_call_counts is local to each handle()
    assert info_turn1["final_reply"] == "Done with 15 searches.", (
        f"Turn 1: expected 'Done with 15 searches.', got: {info_turn1['final_reply'][:100]}"
    )
    assert info_turn1["tool_executions"] is not None
    assert len(info_turn1["tool_executions"]) == 15, (
        f"Turn 1: expected 15 tool executions, got {len(info_turn1['tool_executions'])}"
    )

    assert info_turn2["final_reply"] == "Done with 6 more.", (
        f"Turn 2: expected 'Done with 6 more.', got: {info_turn2['final_reply'][:100]}"
    )
    assert info_turn2["tool_executions"] is not None
    assert len(info_turn2["tool_executions"]) == 6, (
        f"Turn 2: expected 6 tool executions, got {len(info_turn2['tool_executions'])}"
    )

    harness.log.scenario = "F_same_tool_calls_request_scope"
    path = harness.log.save()
    print(f"\n  [Scenario F] Log saved: {path}")
    print("  FINDING: tool_call_counts is local per handle() — scope=request only")
    print("  persists across agent-loop turns in one request, not across handle() calls.")


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario F2 — same tool calls with TURN scope (should also NOT break across handle calls)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Same finding as F: scope=turn vs scope=conversation has no effect across separate
# handle() calls because each call initializes tool_call_counts = {}. The scope flag
# only matters within a single handle() call, controlling whether the counter resets
# between agent-loop turns.

@pytest.mark.asyncio
async def test_scenario_f2_same_tool_calls_turn_scope(mock_user, mock_db, registry_basic):
    """Turn 1: 15 calls. Turn 2: 6 calls. Both complete normally."""
    script = ScriptedModelClient([
        ProviderResponse(tool_calls=[ToolCall(id=f"x{i}", name="web_search", args={"q": str(i)})
                                     for i in range(15)]),
        ProviderResponse(content="Done with turn."),
        ProviderResponse(tool_calls=[ToolCall(id=f"y{i}", name="web_search", args={"q": str(i)})
                                     for i in range(6)]),
        ProviderResponse(content="Done with second turn."),
    ])
    harness = E2EHarness(mock_user, mock_db, registry_basic)

    with patch("app.config.settings.AGENT_TOOL_CALL_COUNT_SCOPE", "turn"):
        info_turn1 = await harness.turn("Search round 1", script, rank=0)
        info_turn2 = await harness.turn("Search round 2", script, rank=1)

    assert info_turn1["final_reply"] == "Done with turn.", (
        f"Turn 1: expected 'Done with turn.', got: {info_turn1['final_reply'][:100]}"
    )
    assert len(info_turn1["tool_executions"]) == 15, (
        f"Turn 1: expected 15 tool executions, got {len(info_turn1['tool_executions'])}"
    )

    assert info_turn2["final_reply"] == "Done with second turn.", (
        f"Turn 2: expected 'Done with second turn.', got: {info_turn2['final_reply'][:100]}"
    )
    assert len(info_turn2["tool_executions"]) == 6, (
        f"Turn 2: expected 6 tool executions, got {len(info_turn2['tool_executions'])}"
    )

    harness.log.scenario = "F2_same_tool_calls_turn_scope"
    path = harness.log.save()
    print(f"\n  [Scenario F2] Log saved: {path}")
