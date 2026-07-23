"""
Tests for Issue 7: truncate large tool outputs before sending to the LLM.

Verifies that `_truncate_tool_output` correctly limits serialized tool
output to TOOL_OUTPUT_MAX_CHARS and that `_messages_to_openai` applies
the truncation.
"""
import os

os.environ.setdefault(
    'ASYNC_DATABASE_URL',
    'postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db'
)


async def test_small_tool_output_not_truncated():
    """Small tool outputs pass through unchanged."""
    from app.ai.agents.openai_provider import OpenAIProvider
    provider = OpenAIProvider()
    content = {"result": "success", "count": 42}
    result = provider._truncate_tool_output(content)
    import json
    assert result == json.dumps(content)
    assert "truncated" not in result


async def test_large_tool_output_truncated():
    """Large tool outputs are truncated with a note."""
    from app.ai.agents.openai_provider import OpenAIProvider, TOOL_OUTPUT_MAX_CHARS
    provider = OpenAIProvider()
    large = {"data": "x" * (TOOL_OUTPUT_MAX_CHARS + 200)}
    result = provider._truncate_tool_output(large)
    assert len(result) <= TOOL_OUTPUT_MAX_CHARS + 200
    assert "truncated" in result
    assert str(TOOL_OUTPUT_MAX_CHARS + 200 + len('{"data": ""}')) in result or \
           str(TOOL_OUTPUT_MAX_CHARS + 200) in result


async def test_truncation_applied_in_messages_to_openai():
    """_messages_to_openai applies truncation to tool results."""
    from app.ai.agents.openai_provider import OpenAIProvider, TOOL_OUTPUT_MAX_CHARS
    from app.ai.agents.provider_types import Message, ToolResult, GenerationConfig
    provider = OpenAIProvider()
    config = GenerationConfig()
    large = {"data": "x" * (TOOL_OUTPUT_MAX_CHARS + 200)}
    msgs = [
        Message(role="user", content="hi"),
        Message(role="assistant", tool_calls=[], created_at=None),
        Message(role="tool", tool_result=ToolResult(tool_call_id="c1", name="test", content=large)),
    ]
    result = provider._messages_to_openai(msgs, config)
    tool_msg = result[-1]
    assert tool_msg["role"] == "tool"
    assert "truncated" in tool_msg["content"]
    assert tool_msg["tool_call_id"] == "c1"


async def test_empty_tool_output():
    """Empty tool output is handled gracefully."""
    from app.ai.agents.openai_provider import OpenAIProvider
    provider = OpenAIProvider()
    result = provider._truncate_tool_output({})
    assert result == "{}"


async def test_tool_output_with_non_string_types():
    """Tool output with non-serializable types uses default=str."""
    from app.ai.agents.openai_provider import OpenAIProvider
    provider = OpenAIProvider()
    from datetime import datetime
    content = {"timestamp": datetime(2026, 7, 23, 10, 0, 0)}
    result = provider._truncate_tool_output(content)
    assert "2026-07-23" in result


async def main():
    import asyncio
    await test_small_tool_output_not_truncated()
    print("✓ test_small_tool_output_not_truncated")
    await test_large_tool_output_truncated()
    print("✓ test_large_tool_output_truncated")
    await test_truncation_applied_in_messages_to_openai()
    print("✓ test_truncation_applied_in_messages_to_openai")
    await test_empty_tool_output()
    print("✓ test_empty_tool_output")
    await test_tool_output_with_non_string_types()
    print("✓ test_tool_output_with_non_string_types")
    print("All Issue-7 tests passed.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
