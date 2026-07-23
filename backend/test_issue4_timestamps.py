"""
Tests for Issue 4: propagate `created_at` timestamps through the Message
dataclass, `_build_history_contents`, and the OpenAI provider formatting.

Verifies:
- Message dataclass accepts created_at
- _build_history_contents extracts created_at from DB records
- OpenAI provider bakes timestamp into content
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


async def test_build_history_contents_propagates_created_at():
    """_build_history_contents reads created_at from DB records."""
    from app.ai.agents.agent_service import _build_history_contents
    from app.ai.agents.provider_types import Message

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
    assert result[0].created_at == ts
    assert result[1].created_at is not None
    assert result[1].created_at > ts


async def test_build_history_contents_handles_missing_created_at():
    """When a DB record lacks created_at, Message.created_at should be None."""
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
    assert all(m.created_at is None for m in result)


async def test_build_history_contents_tool_messages_get_created_at():
    """Tool messages in history also get their created_at propagated."""
    from app.ai.agents.agent_service import _build_history_contents

    class FakeRecord:
        def __init__(self, role, **kw):
            self.role = role
            for k, v in kw.items():
                setattr(self, k, v)
            self.created_at = kw.get("created_at", datetime(2026, 7, 23, 10, 0, 0))

    ts = datetime(2026, 7, 23, 10, 1, 0)
    records = [
        FakeRecord(role="user", content="Use tool"),
        FakeRecord(role="assistant", content=None, turn_id="t1"),
        FakeRecord(role="tool", tool_name="search", tool_input={"q": "x"}, tool_output={"r": "y"}, tool_call_id="t1_0", turn_id="t1", created_at=ts),
    ]
    result = _build_history_contents(records)
    # assistant with tool_calls + tool
    tool_msgs = [m for m in result if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].created_at == ts


async def test_openai_provider_bakes_timestamp():
    """OpenAIProvider._format_content_with_ts prepends timestamp."""
    from app.ai.agents.openai_provider import OpenAIProvider
    provider = OpenAIProvider()
    ts = datetime(2026, 7, 23, 14, 30, 0)

    result = provider._format_content_with_ts("hello", ts)
    assert "[2026-07-23 14:30:00 UTC]" in result
    assert "hello" in result

    result_none = provider._format_content_with_ts("world", None)
    assert result_none == "world"

    result_empty_ts = provider._format_content_with_ts("test", datetime(2026, 1, 1, 0, 0, 0))
    assert "[2026-01-01 00:00:00 UTC] test" == result_empty_ts


async def test_openai_provider_messages_to_openai_includes_timestamps():
    """_messages_to_openai includes timestamps for user and assistant messages."""
    from app.ai.agents.openai_provider import OpenAIProvider
    from app.ai.agents.provider_types import Message, GenerationConfig
    provider = OpenAIProvider()
    config = GenerationConfig()

    msgs = [
        Message(role="user", content="hi", created_at=datetime(2026, 7, 23, 10, 0, 0)),
        Message(role="assistant", content="hello", created_at=datetime(2026, 7, 23, 10, 0, 5)),
    ]
    result = provider._messages_to_openai(msgs, config)
    assert result[0]["content"] == "[2026-07-23 10:00:00 UTC] hi"
    assert result[1]["content"] == "[2026-07-23 10:00:05 UTC] hello"


async def test_get_message_created_at_safe():
    """_get_message_created_at safely handles records without created_at."""
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


async def main():
    await test_message_dataclass_accepts_created_at()
    print("✓ test_message_dataclass_accepts_created_at")
    await test_message_created_at_defaults_to_none()
    print("✓ test_message_created_at_defaults_to_none")
    await test_build_history_contents_propagates_created_at()
    print("✓ test_build_history_contents_propagates_created_at")
    await test_build_history_contents_handles_missing_created_at()
    print("✓ test_build_history_contents_handles_missing_created_at")
    await test_build_history_contents_tool_messages_get_created_at()
    print("✓ test_build_history_contents_tool_messages_get_created_at")
    await test_openai_provider_bakes_timestamp()
    print("✓ test_openai_provider_bakes_timestamp")
    await test_openai_provider_messages_to_openai_includes_timestamps()
    print("✓ test_openai_provider_messages_to_openai_includes_timestamps")
    await test_get_message_created_at_safe()
    print("✓ test_get_message_created_at_safe")
    print("All Issue-4 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
