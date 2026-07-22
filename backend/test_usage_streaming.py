"""
Tests for OpenAIProvider.generate_stream usage-yield fix.

Scenarios:
1. Usage-only chunk after finish_reason → yielded exactly ONCE (after loop)
2. Usage on finish_reason chunk → yielded on that chunk, NOT after loop
3. Usage on both finish_reason AND final usage-only → yielded twice (once per chunk)
4. No usage → nothing yielded after loop
5. Multiple usage-only chunks at end → only the last accumulated value yielded

Run: python -m pytest test_usage_streaming.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import pytest

from app.ai.agents.openai_provider import OpenAIProvider
from app.ai.agents.provider_types import GenerationConfig


def _make_chunk(choices=None, usage=None):
    """Create a mock OpenAI chunk."""
    return SimpleNamespace(choices=choices, usage=usage)


def _make_choice(delta=None, finish_reason=None):
    return SimpleNamespace(delta=delta, finish_reason=finish_reason)


def _make_delta(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


def _make_usage(prompt_tokens=10, completion_tokens=5, total_tokens=15):
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


@pytest.fixture
def provider():
    return OpenAIProvider()


@pytest.fixture
def config():
    return GenerationConfig(system_instruction="test")


def _collect_chunks(stream):
    """Collect async generator into list."""
    return list(stream)


@pytest.mark.asyncio
async def test_usage_only_chunk_yielded_after_loop(provider, config):
    """
    Scenario: finish_reason chunk without usage, then a separate usage-only chunk.
    Expected: final chunk yields usage once.
    """
    chunks = [
        _make_chunk(
            choices=[_make_choice(delta=_make_delta(content="Hello"), finish_reason="stop")],
        ),
        _make_chunk(usage=_make_usage(10, 5, 15)),
    ]

    mock_stream = AsyncMock()
    mock_stream.__aiter__.return_value = iter(chunks)

    with patch("app.ai.agents.openai_provider._get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_stream
        mock_get_client.return_value = mock_client

        collected = []
        async for chunk in provider.generate_stream(
            "gpt-4o", [], config, tools=None
        ):
            collected.append(chunk)

    usage_chunks = [c for c in collected if c.usage is not None]
    assert len(usage_chunks) == 1, (
        f"Expected exactly 1 chunk with usage, got {len(usage_chunks)}"
    )
    assert usage_chunks[0].usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


@pytest.mark.asyncio
async def test_usage_on_finish_reason_not_doubled(provider, config):
    """
    Scenario: usage attached to the same chunk as finish_reason.
    Expected: usage yielded once with that chunk, NOT again after the loop.
    """
    chunks = [
        _make_chunk(
            choices=[_make_choice(delta=_make_delta(content="Hi"), finish_reason="stop")],
            usage=_make_usage(20, 10, 30),
        ),
    ]

    mock_stream = AsyncMock()
    mock_stream.__aiter__.return_value = iter(chunks)

    with patch("app.ai.agents.openai_provider._get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_stream
        mock_get_client.return_value = mock_client

        collected = []
        async for chunk in provider.generate_stream(
            "gpt-4o", [], config, tools=None
        ):
            collected.append(chunk)

    usage_chunks = [c for c in collected if c.usage is not None]
    assert len(usage_chunks) == 1, (
        f"Expected exactly 1 chunk with usage (not doubled), got {len(usage_chunks)}"
    )
    assert usage_chunks[0].usage == {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}
    assert usage_chunks[0].content == "Hi"
    assert usage_chunks[0].finish_reason == "stop"


@pytest.mark.asyncio
async def test_no_usage_yields_nothing_after_loop(provider, config):
    """No usage at all → no usage chunk after loop."""
    chunks = [
        _make_chunk(
            choices=[_make_choice(delta=_make_delta(content="A"), finish_reason="stop")],
        ),
    ]

    mock_stream = AsyncMock()
    mock_stream.__aiter__.return_value = iter(chunks)

    with patch("app.ai.agents.openai_provider._get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_stream
        mock_get_client.return_value = mock_client

        collected = []
        async for chunk in provider.generate_stream(
            "gpt-4o", [], config, tools=None
        ):
            collected.append(chunk)

    usage_chunks = [c for c in collected if c.usage is not None]
    assert len(usage_chunks) == 0, (
        f"Expected 0 usage chunks, got {len(usage_chunks)}"
    )


@pytest.mark.asyncio
async def test_multiple_usage_only_chunks_accumulate(provider, config):
    """
    Multiple usage-only chunks at end accumulate; only the last value yielded.
    """
    chunks = [
        _make_chunk(
            choices=[_make_choice(delta=_make_delta(content="B"), finish_reason="stop")],
            usage=_make_usage(5, 2, 7),
        ),
        _make_chunk(usage=_make_usage(10, 5, 15)),
        _make_chunk(usage=_make_usage(10, 8, 18)),
    ]

    mock_stream = AsyncMock()
    mock_stream.__aiter__.return_value = iter(chunks)

    with patch("app.ai.agents.openai_provider._get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_stream
        mock_get_client.return_value = mock_client

        collected = []
        async for chunk in provider.generate_stream(
            "gpt-4o", [], config, tools=None
        ):
            collected.append(chunk)

    usage_chunks = [c for c in collected if c.usage is not None]
    assert len(usage_chunks) == 2, (
        f"Expected 2 usage chunks (first + final), got {len(usage_chunks)}"
    )
    assert usage_chunks[0].usage == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    assert usage_chunks[1].usage == {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}


@pytest.mark.asyncio
async def test_tool_call_with_finish_reason_usage_not_doubled(provider, config):
    """
    Scenario: tool call with finish_reason="tool_calls" + usage on same chunk.
    Expected: usage yielded once with the tool-call chunk, not doubled.
    """
    chunks = [
        _make_chunk(
            choices=[_make_choice(
                delta=_make_delta(tool_calls=[SimpleNamespace(
                    index=0,
                    id="call_1",
                    function=SimpleNamespace(name="search", arguments='{"q":"test"}'),
                )]),
                finish_reason="tool_calls",
            )],
            usage=_make_usage(30, 15, 45),
        ),
    ]

    mock_stream = AsyncMock()
    mock_stream.__aiter__.return_value = iter(chunks)

    with patch("app.ai.agents.openai_provider._get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_stream
        mock_get_client.return_value = mock_client

        collected = []
        async for chunk in provider.generate_stream(
            "gpt-4o", [], config, tools=None
        ):
            collected.append(chunk)

    usage_chunks = [c for c in collected if c.usage is not None]
    assert len(usage_chunks) == 1, (
        f"Expected exactly 1 chunk with usage (tool_calls case), got {len(usage_chunks)}"
    )
    assert usage_chunks[0].usage == {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45}
    assert usage_chunks[0].finish_reason == "tool_calls"
