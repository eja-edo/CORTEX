"""
Unit tests for _validate_contents_ordering and _build_history_contents.

Run: python -m pytest test_validate_contents_ordering.py -v
"""

from types import SimpleNamespace
from uuid import uuid4

from app.ai.agents.provider_types import Message, ToolCall, ToolResult
from app.ai.agents.agent_service import (
    _validate_contents_ordering,
    _build_history_contents,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_tool_call(id: str, name: str, args: dict | None = None) -> ToolCall:
    return ToolCall(id=id, name=name, args=args or {})


def _make_tool_result(tool_call_id: str, name: str, content: dict | None = None) -> ToolResult:
    return ToolResult(tool_call_id=tool_call_id, name=name, content=content or {})


def _fake_record(role: str, **kwargs) -> SimpleNamespace:
    """Create a fake DB record-like object mimicking AgentMessage attributes."""
    return SimpleNamespace(
        role=role,
        content=kwargs.get("content"),
        tool_name=kwargs.get("tool_name"),
        tool_input=kwargs.get("tool_input"),
        tool_output=kwargs.get("tool_output"),
        tool_call_id=kwargs.get("tool_call_id"),
        turn_id=kwargs.get("turn_id"),
        context=kwargs.get("context"),
    )


# ══════════════════════════════════════════════════════════════════════════
# _validate_contents_ordering tests
# ══════════════════════════════════════════════════════════════════════════

class TestValidateContentsOrdering:

    def test_empty_messages(self):
        valid, msg = _validate_contents_ordering([])
        assert valid is True

    def test_single_user(self):
        valid, msg = _validate_contents_ordering([Message(role="user", content="hi")])
        assert valid is True

    def test_user_then_assistant(self):
        messages = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is True

    def test_single_tool_call_valid(self):
        """assistant(tc1) → tool(r1): valid"""
        messages = [
            Message(role="user", content="search"),
            Message(
                role="assistant",
                tool_calls=[_make_tool_call("web_1", "web_search")],
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("web_1", "web_search"),
            ),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is True, f"Expected valid, got: {msg}"

    def test_parallel_tool_calls_valid(self):
        """assistant(tc1, tc2, tc3) → tool(r1) → tool(r2) → tool(r3): valid"""
        messages = [
            Message(role="user", content="search"),
            Message(
                role="assistant",
                tool_calls=[
                    _make_tool_call("web_1", "web_search"),
                    _make_tool_call("web_2", "web_search"),
                    _make_tool_call("note_1", "search_notes"),
                ],
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("web_1", "web_search"),
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("web_2", "web_search"),
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("note_1", "search_notes"),
            ),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is True, f"Expected valid, got: {msg}"

    def test_tool_result_wrong_id_rejected(self):
        """tool result với tool_call_id không khớp → FAIL"""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                tool_calls=[_make_tool_call("tc_1", "web_search")],
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("wrong_id", "web_search"),
            ),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is False
        assert "not among pending" in msg

    def test_duplicate_tool_call_id_rejected(self):
        """assistant với 2 tool_calls trùng id → FAIL ngay"""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                tool_calls=[
                    _make_tool_call("dup_id", "web_search"),
                    _make_tool_call("dup_id", "search_notes"),
                ],
            ),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is False
        assert "Duplicate" in msg

    def test_tool_without_assistant_rejected(self):
        """tool message đầu tiên (sau user) → FAIL"""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="tool",
                tool_result=_make_tool_result("tc_1", "web_search"),
            ),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is False
        assert "without preceding" in msg

    def test_dangling_tool_calls_intermediate_state_allowed(self):
        """assistant(tc1) là message cuối → PASS (intermediate state trước khi exec tool)"""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                tool_calls=[_make_tool_call("tc_1", "web_search")],
            ),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is True, f"Expected PASS for intermediate state, got: {msg}"

    def test_dangling_tool_calls_rejected_at_final_state(self):
        """assistant(tc1,tc2) → tool(r1) kết thúc, thiếu tc2 → FAIL (tool là msg cuối)"""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                tool_calls=[
                    _make_tool_call("tc_1", "web_search"),
                    _make_tool_call("tc_2", "search_notes"),
                ],
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("tc_1", "web_search"),
            ),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is False
        assert "Unresolved" in msg

    def test_dangling_tool_calls_assistant_text_instead_of_tool_result(self):
        """assistant(tc1,tc2) → ... → assistant(text) trước khi tool kết thúc → FAIL"""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                tool_calls=[
                    _make_tool_call("tc_1", "web_search"),
                    _make_tool_call("tc_2", "search_notes"),
                ],
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("tc_1", "web_search"),
            ),
            Message(role="assistant", content="I'll get back to you"),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is False
        assert "before pending" in msg

    def test_consecutive_user_still_rejected(self):
        """user → user: vẫn FAIL (alternation thật)"""
        messages = [
            Message(role="user", content="hi"),
            Message(role="user", content="hello again"),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is False
        assert "Role violation" in msg

    def test_consecutive_assistant_still_rejected(self):
        """assistant → assistant: vẫn FAIL"""
        messages = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
            Message(role="assistant", content="world"),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is False
        assert "Role violation" in msg

    def test_tool_then_non_tool_before_all_resolved(self):
        """assistant(tc1, tc2) → tool(r1) → assistant(text) → FAIL (tc2 chưa resolve)"""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                tool_calls=[
                    _make_tool_call("tc_1", "web_search"),
                    _make_tool_call("tc_2", "search_notes"),
                ],
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("tc_1", "web_search"),
            ),
            Message(role="assistant", content="interrupting before tc_2 resolved"),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is False
        assert "before pending" in msg

    def test_full_conversation_with_parallel_tools(self):
        """user → assistant(parallel) → tool*N → assistant(text): valid"""
        messages = [
            Message(role="user", content="search"),
            Message(
                role="assistant",
                tool_calls=[
                    _make_tool_call("tc_1", "web_search", {"q": "a"}),
                    _make_tool_call("tc_2", "web_search", {"q": "b"}),
                ],
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("tc_1", "web_search", {"result": "a"}),
            ),
            Message(
                role="tool",
                tool_result=_make_tool_result("tc_2", "web_search", {"result": "b"}),
            ),
            Message(role="assistant", content="Here are the results"),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is True, f"Expected valid, got: {msg}"

    def test_multi_turn_with_parallel(self):
        """user → assistant(parallel) → tool*3 → assistant → user → assistant(parallel) → tool*2 → assistant"""
        messages = [
            Message(role="user", content="first"),
            Message(
                role="assistant",
                tool_calls=[_make_tool_call("a", "t1"), _make_tool_call("b", "t2")],
            ),
            Message(role="tool", tool_result=_make_tool_result("a", "t1")),
            Message(role="tool", tool_result=_make_tool_result("b", "t2")),
            Message(role="assistant", content="done first turn"),
            Message(role="user", content="again"),
            Message(
                role="assistant",
                tool_calls=[_make_tool_call("c", "t3")],
            ),
            Message(role="tool", tool_result=_make_tool_result("c", "t3")),
            Message(role="assistant", content="done second turn"),
        ]
        valid, msg = _validate_contents_ordering(messages)
        assert valid is True, f"Expected valid, got: {msg}"


# ══════════════════════════════════════════════════════════════════════════
# _build_history_contents tests
# ══════════════════════════════════════════════════════════════════════════

class TestBuildHistoryContents:

    def test_empty_records(self):
        result = _build_history_contents([])
        assert result == []

    def test_leading_non_user_stripped(self):
        records = [
            _fake_record("tool", tool_name="web_search", tool_input={}, tool_output={}),
            _fake_record("user", content="hi"),
        ]
        result = _build_history_contents(records)
        assert len(result) == 1
        assert result[0].role == "user"

    def test_single_user(self):
        records = [_fake_record("user", content="hello")]
        result = _build_history_contents(records)
        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].content == "hello"

    def test_user_assistant_alternation(self):
        records = [
            _fake_record("user", content="hi"),
            _fake_record("assistant", content="hello"),
        ]
        result = _build_history_contents(records)
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"

    def test_single_tool_pair(self):
        records = [
            _fake_record("user", content="search notes"),
            _fake_record("tool", tool_name="search_notes", tool_input={"q": "python"}, tool_output={"count": 2}),
        ]
        result = _build_history_contents(records)
        # 1 user + 1 assistant(tool_calls) + 1 tool = 3 messages
        assert len(result) == 3
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert result[1].tool_calls is not None
        assert len(result[1].tool_calls) == 1
        assert result[1].tool_calls[0].name == "search_notes"
        assert result[2].role == "tool"
        assert result[2].tool_result is not None
        assert result[2].tool_result.name == "search_notes"

    def test_groups_parallel_tools_by_turn_id(self):
        turn = uuid4()
        records = [
            _fake_record("user", content="search"),
            _fake_record(
                "tool", turn_id=turn,
                tool_name="web_search", tool_input={"q": "a"}, tool_output={"r": "a"},
                tool_call_id="tc_1",
            ),
            _fake_record(
                "tool", turn_id=turn,
                tool_name="web_search", tool_input={"q": "b"}, tool_output={"r": "b"},
                tool_call_id="tc_2",
            ),
            _fake_record(
                "tool", turn_id=turn,
                tool_name="search_notes", tool_input={"q": "python"}, tool_output={"count": 2},
                tool_call_id="tc_3",
            ),
        ]
        result = _build_history_contents(records)
        # user + 1 assistant(3 tool_calls) + 3 tool = 5 messages
        assert len(result) == 5
        assert result[0].role == "user"
        # assistant message should have ALL 3 tool_calls grouped
        assert result[1].role == "assistant"
        assert result[1].tool_calls is not None
        assert len(result[1].tool_calls) == 3
        tc_names = [tc.name for tc in result[1].tool_calls]
        assert tc_names == ["web_search", "web_search", "search_notes"]
        # 3 tool messages follow
        assert result[2].role == "tool"
        assert result[3].role == "tool"
        assert result[4].role == "tool"
        assert result[4].tool_result.name == "search_notes"

    def test_legacy_records_no_turn_id_grouped(self):
        """Data cũ (không có turn_id) — các tool record liên tiếp vẫn group được"""
        records = [
            _fake_record("user", content="search"),
            _fake_record(
                "tool",
                tool_name="web_search", tool_input={"q": "a"}, tool_output={"r": "a"},
            ),
            _fake_record(
                "tool",
                tool_name="web_search", tool_input={"q": "b"}, tool_output={"r": "b"},
            ),
        ]
        result = _build_history_contents(records)
        # 1 user + 1 assistant(2 tool_calls) + 2 tool = 4 messages
        assert len(result) == 4
        assert result[1].role == "assistant"
        assert len(result[1].tool_calls) == 2
        # Fallback: mỗi tool_call_id được đặt là "{tool_name}_{idx}"
        assert result[1].tool_calls[0].id == "web_search_0"
        assert result[1].tool_calls[1].id == "web_search_1"
        assert result[2].tool_result.tool_call_id == "web_search_0"
        assert result[3].tool_result.tool_call_id == "web_search_1"

    def test_mixed_turn_id_fallback(self):
        """Legacy record (không turn_id) rồi tới record mới (có turn_id) — tách riêng"""
        records = [
            _fake_record("user", content="hi"),
            _fake_record(
                "tool",
                tool_name="old_search", tool_input={"q": "old"}, tool_output={"r": "old"},
            ),
            _fake_record(
                "tool", turn_id=uuid4(),
                tool_name="new_search", tool_input={"q": "new"}, tool_output={"r": "new"},
                tool_call_id="tc_new",
            ),
        ]
        result = _build_history_contents(records)
        # user + assistant(1) + tool + assistant(1) + tool = 5
        assert len(result) == 5
        # First group: legacy tools
        assert result[1].role == "assistant"
        assert len(result[1].tool_calls) == 1
        assert result[1].tool_calls[0].name == "old_search"
        # Second group: new tool with turn_id
        assert result[3].role == "assistant"
        assert len(result[3].tool_calls) == 1
        assert result[3].tool_calls[0].id == "tc_new"

    def test_multiple_turns_parallel(self):
        """user → assistant(tc1,tc2) → tool(r1) → tool(r2) → assistant(text) → user → assistant(tc3) → tool(r3)"""
        t1 = uuid4()
        t2 = uuid4()
        records = [
            _fake_record("user", content="first"),
            _fake_record("tool", turn_id=t1, tool_name="s1", tool_input={"q": "a"}, tool_output={"r": "a"}, tool_call_id="a"),
            _fake_record("tool", turn_id=t1, tool_name="s2", tool_input={"q": "b"}, tool_output={"r": "b"}, tool_call_id="b"),
            _fake_record("assistant", content="first done"),
            _fake_record("user", content="again"),
            _fake_record("tool", turn_id=t2, tool_name="s3", tool_input={"q": "c"}, tool_output={"r": "c"}, tool_call_id="c"),
        ]
        result = _build_history_contents(records)
        # user + assistant(tc1,tc2) + tool(r1) + tool(r2) + assistant(text) + user + assistant(tc3) + tool(r3)
        assert len(result) == 8
        assert result[1].role == "assistant"
        assert len(result[1].tool_calls) == 2  # parallel: s1 + s2
        assert result[5].role == "user"
        assert result[6].role == "assistant"
        assert len(result[6].tool_calls) == 1  # single: s3

    def test_end_to_end_replay_original_crash_log(self):
        """Replay lại sequence gây crash gốc: 2x web_search + 1x search_notes trong 1 turn"""
        turn = uuid4()
        records = [
            _fake_record("user", content="AI phát triển ảnh hưởng đến các ngành nghề"),
            _fake_record(
                "tool", turn_id=turn,
                tool_name="web_search", tool_input={"q": "AI phát triển ảnh hưởng đến các ngành nghề 2025 2026"},
                tool_output={"result": "ok"}, tool_call_id="call_web1",
            ),
            _fake_record(
                "tool", turn_id=turn,
                tool_name="web_search", tool_input={"q": "AI impact on industries jobs 2025 2026 trends"},
                tool_output={"result": "ok"}, tool_call_id="call_web2",
            ),
            _fake_record(
                "tool", turn_id=turn,
                tool_name="search_notes", tool_input={"q": "AI ảnh hưởng ngành nghề"},
                tool_output={"count": 2}, tool_call_id="call_notes1",
            ),
        ]
        # Bước 1: build history
        built = _build_history_contents(records)
        # Verify: 1 user + 1 assistant(3 tool_calls) + 3 tool = 5 messages
        assert len(built) == 5
        assert built[1].role == "assistant"
        assert len(built[1].tool_calls) == 3
        # Bước 2: validate — đây là bước crash cũ
        valid, msg = _validate_contents_ordering(built)
        assert valid is True, (
            f"CRASH REPLAY FAILED: {msg}\n"
            f"Built messages:\n" + "\n".join(
                f"  [{i}] role={m.role} tc={[t.name for t in (m.tool_calls or [])]} tr={m.tool_result.name if m.tool_result else None}"
                for i, m in enumerate(built)
            )
        )
