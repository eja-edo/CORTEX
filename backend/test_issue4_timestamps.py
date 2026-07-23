"""
Tests for Issue 4: propagate `created_at` timestamps through the Message
dataclass, baked into content at construction time (provider-agnostic).

Verifies:
- Message dataclass accepts created_at
- _format_timestamp helper
- _build_history_contents bakes timestamp into message content
- OpenAI provider does NOT add its own timestamp (prevents double-baking)
- Current-turn messages get datetime.utcnow()
"""
import os
import asyncio
from datetime import datetime
from unittest.mock import patch, MagicMock

os.environ.setdefault(
    'ASYNC_DATABASE_URL',
    'postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db'
)


async def test_message_dataclass_accepts_created_at():
    """Message dataclass accepts an optional created_at field."""
    from app.ai.agents.provider_types import Message, ToolCall, ToolResult
    ts = datetime(2026, 7, 23, 10, 0, 0)

    m1 = Message(role="user", content="hi", created_at=ts)
    assert m1.created_at == ts

    m2 = Message(role="assistant", content="hello", created_at=ts)
    assert m2.created_at == ts

    m3 = Message(role="assistant", tool_calls=[ToolCall(id="c1", name="f", args={})], created_at=ts)
    assert m3.created_at == ts

    m4 = Message(role="tool", tool_result=ToolResult(tool_call_id="c1", name="f", content={}), created_at=ts)
    assert m4.created_at == ts

    m5 = Message(role="user", content="no ts")
    assert m5.created_at is None


async def test_message_created_at_defaults_to_none():
    """When omitted, created_at defaults to None (backward compatible)."""
    from app.ai.agents.provider_types import Message
    m = Message(role="user", content="test")
    assert m.created_at is None


async def test_format_timestamp():
    """_format_timestamp produces correct output."""
    from app.ai.agents.agent_service import _format_timestamp
    ts = datetime(2026, 7, 23, 14, 30, 0)

    result = _format_timestamp(ts)
    assert result == "[2026-07-23 14:30:00 UTC] "

    result_none = _format_timestamp(None)
    assert result_none == ""


async def test_build_history_contents_bakes_timestamp_into_content():
    """_build_history_contents bakes created_at into content string."""
    from app.ai.agents.agent_service import _build_history_contents

    class FakeRecord:
        def __init__(self, role, content, created_at=None, **kw):
            self.role = role
            self.content = content
            self.created_at = created_at
            for k, v in kw.items():
                setattr(self, k, v)

    ts = datetime(2026, 7, 23, 10, 0, 0)
    records = [
        FakeRecord(role="user", content="Hello", created_at=ts),
        FakeRecord(role="assistant", content="Hi there", created_at=datetime(2026, 7, 23, 10, 0, 5)),
    ]

    result = _build_history_contents(records)
    assert len(result) == 2
    assert "[2026-07-23 10:00:00 UTC] " in result[0].content
    assert "Hello" in result[0].content
    assert "[2026-07-23 10:00:05 UTC] " in result[1].content
    assert "Hi there" in result[1].content


async def test_build_history_contents_handles_no_timestamp():
    """When DB record lacks created_at, no timestamp prefix is added."""
    from app.ai.agents.agent_service import _build_history_contents

    class FakeRecord:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    records = [
        FakeRecord(role="user", content="Hello"),
        FakeRecord(role="assistant", content="Hi"),
    ]
    result = _build_history_contents(records)
    assert all("[2026" not in (m.content or "") for m in result)


async def test_openai_provider_does_not_double_bake_timestamp():
    """OpenAI provider does not add its own timestamp (baked at construction)."""
    from app.ai.agents.openai_provider import OpenAIProvider
    from app.ai.agents.provider_types import Message, GenerationConfig
    provider = OpenAIProvider()
    config = GenerationConfig()

    # Content already has timestamp baked in
    msgs = [
        Message(role="user", content="[2026-07-23 14:30:00 UTC] hi"),
        Message(role="assistant", content="[2026-07-23 14:30:05 UTC] hello"),
    ]
    result = provider._messages_to_openai(msgs, config)
    assert result[0]["content"] == "[2026-07-23 14:30:00 UTC] hi"
    assert result[1]["content"] == "[2026-07-23 14:30:05 UTC] hello"
    # Verify no double timestamp
    assert result[0]["content"].count("UTC") == 1


async def test_message_full_text_bakes_timestamp():
    """_message_full_text bakes timestamp into content."""
    from app.ai.agents.agent_service import _message_full_text

    class FakeMsg:
        content = "Hello"
        context = None
        created_at = datetime(2026, 7, 23, 10, 0, 0)

    result = _message_full_text(FakeMsg())
    assert "[2026-07-23 10:00:00 UTC] " in result
    assert "Hello" in result


async def test_get_message_created_at_safe():
    """_get_message_created_at safely handles edge cases."""
    from app.ai.agents.agent_service import _get_message_created_at

    class Good:
        created_at = datetime(2026, 1, 1)

    class Bad:
        pass

    class ExceptionRaiser:
        @property
        def created_at(self):
            raise RuntimeError("boom")

    assert _get_message_created_at(Good()) == datetime(2026, 1, 1)
    assert _get_message_created_at(Bad()) is None
    assert _get_message_created_at(ExceptionRaiser()) is None


async def test_build_history_contents_tool_messages_get_created_at():
    """Tool messages in _build_history_contents get created_at set on Message.

    Unlike user/assistant roles (timestamp baked into content text), tool
    messages carry created_at as a property on the Message dataclass so
    downstream code can access it if needed.
    """
    from app.ai.agents.agent_service import _build_history_contents
    from app.ai.agents.provider_types import Message

    class FakeRecord:
        def __init__(self, role, content=None, created_at=None, tool_name=None, tool_input=None, tool_output=None, tool_call_id=None, turn_id=None):
            self.role = role
            self.content = content
            self.created_at = created_at
            self.tool_name = tool_name
            self.tool_input = tool_input
            self.tool_output = tool_output
            self.tool_call_id = tool_call_id
            self.turn_id = turn_id

    ts = datetime(2026, 7, 23, 12, 0, 0)
    records = [
        FakeRecord(role="user", content="get weather", created_at=ts),
        FakeRecord(role="assistant", content="", created_at=ts, tool_name="get_weather", tool_call_id="call1", turn_id="t1"),
        FakeRecord(role="tool", created_at=ts, tool_name="get_weather", tool_input={"city": "Hanoi"}, tool_output={"temp": 30}, tool_call_id="call1", turn_id="t1"),
    ]

    result = _build_history_contents(records)
    # Should produce: user msg, assistant (tool_calls), tool (tool_result)
    assert len(result) == 3
    # User msg has timestamp baked into content
    assert "[2026-07-23" in result[0].content
    # Tool msg has created_at set
    assert result[2].role == "tool"
    assert result[2].created_at == ts
    assert result[2].tool_result is not None
    assert result[2].tool_result.name == "get_weather"
    assert result[2].tool_result.content == {"temp": 30}


async def test_current_user_message_bakes_timestamp():
    """Current-turn user message has timestamp baked into content."""
    from app.ai.agents.agent_service import _format_timestamp
    now = datetime.utcnow()
    result = _format_timestamp(now) + "user text"
    assert result.startswith("[")
    assert result.endswith(" UTC] user text")
    assert "user text" in result


async def main():
    await test_message_dataclass_accepts_created_at()
    print("✓ test_message_dataclass_accepts_created_at")
    await test_message_created_at_defaults_to_none()
    print("✓ test_message_created_at_defaults_to_none")
    await test_format_timestamp()
    print("✓ test_format_timestamp")
    await test_build_history_contents_bakes_timestamp_into_content()
    print("✓ test_build_history_contents_bakes_timestamp_into_content")
    await test_build_history_contents_handles_no_timestamp()
    print("✓ test_build_history_contents_handles_no_timestamp")
    await test_openai_provider_does_not_double_bake_timestamp()
    print("✓ test_openai_provider_does_not_double_bake_timestamp")
    await test_message_full_text_bakes_timestamp()
    print("✓ test_message_full_text_bakes_timestamp")
    await test_get_message_created_at_safe()
    print("✓ test_get_message_created_at_safe")
    await test_build_history_contents_tool_messages_get_created_at()
    print("✓ test_build_history_contents_tool_messages_get_created_at")
    await test_current_user_message_bakes_timestamp()
    print("✓ test_current_user_message_bakes_timestamp")
    print("All Issue-4 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
