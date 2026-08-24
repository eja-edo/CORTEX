"""Unit tests for ModelClient's model selection.

Two regressions are pinned here, from opposite directions.

The catalogue was introduced because a user-selected `preferred_model`
used to be dropped whenever it wasn't the one default model, so choosing
a model in the UI did nothing.

Rotation was then removed because the opposite was true: a process-wide
cursor walked the catalogue, so consecutive turns in one conversation
were answered by different models and a chosen one was only a
preference. Every test below asserts the same property from a different
angle — **one request runs on exactly one model, and which one is
predictable from the request alone.**
"""

import pytest

from app.ai.agents.base_provider import LLMProvider
from app.ai.agents.model_client import ModelClient, get_default_models
from app.ai.agents.provider_types import GenerationConfig, Message, ProviderResponse, ProviderStreamChunk


class FakeProvider(LLMProvider):
    """Records which model each call was made with. Raises whatever
    `fail_with` holds, for the retry tests."""

    def __init__(self, fail_with: list[Exception] | None = None):
        self.generate_calls: list[str] = []
        self.stream_calls: list[str] = []
        self._fail_with = list(fail_with or [])

    def _maybe_fail(self):
        if self._fail_with:
            raise self._fail_with.pop(0)

    async def generate(self, model, messages, config, tools=None) -> ProviderResponse:
        self.generate_calls.append(model)
        self._maybe_fail()
        return ProviderResponse(content=f"reply-from-{model}")

    async def generate_stream(self, model, messages, config, tools=None):
        self.stream_calls.append(model)
        self._maybe_fail()
        yield ProviderStreamChunk(content=f"reply-from-{model}", finish_reason="stop")

    def get_model_key(self, model: str) -> str:
        return model

    def get_usage(self, response):
        return response.usage


CATALOG = ["model-a", "model-b", "model-c"]


def _client(provider: FakeProvider) -> ModelClient:
    return ModelClient(models=list(CATALOG), provider=provider)


@pytest.mark.asyncio
async def test_get_default_models_returns_full_catalogue():
    ids = get_default_models()
    assert len(ids) >= 1
    assert len(set(ids)) == len(ids)


@pytest.mark.asyncio
async def test_generate_uses_preferred_model_when_in_catalogue():
    provider = FakeProvider()
    client = _client(provider)

    model_used, response = await client.generate(
        [Message(role="user", content="hi")],
        GenerationConfig(),
        preferred_model="model-b",
    )

    assert model_used == "model-b"
    assert provider.generate_calls == ["model-b"]
    assert response.content == "reply-from-model-b"


@pytest.mark.asyncio
async def test_generate_ignores_preferred_model_not_in_catalogue():
    provider = FakeProvider()
    client = _client(provider)

    model_used, _ = await client.generate(
        [Message(role="user", content="hi")],
        GenerationConfig(),
        preferred_model="not-a-real-model",
    )

    assert model_used == CATALOG[0], "an unknown name falls back to the default, not to whatever is next in line"
    assert provider.generate_calls == [CATALOG[0]]


@pytest.mark.asyncio
async def test_stream_uses_preferred_model_when_in_catalogue():
    provider = FakeProvider()
    client = _client(provider)

    chunks = [
        chunk
        async for chunk in client.stream(
            [Message(role="user", content="hi")],
            GenerationConfig(),
            preferred_model="model-c",
        )
    ]

    assert provider.stream_calls == ["model-c"]
    assert chunks[-1].content == "reply-from-model-c"


@pytest.mark.asyncio
async def test_stream_ignores_unknown_preferred_model():
    provider = FakeProvider()
    client = _client(provider)

    async for _ in client.stream(
        [Message(role="user", content="hi")],
        GenerationConfig(),
        preferred_model="unknown-model",
    ):
        pass

    assert provider.stream_calls == [CATALOG[0]]


@pytest.mark.asyncio
async def test_repeated_requests_all_run_on_the_same_model():
    """The reason rotation was removed: consecutive turns in one
    conversation used to be answered by different models, so tone, format
    and capability shifted with nothing in the request explaining it."""
    provider = FakeProvider()
    client = _client(provider)

    for _ in range(5):
        await client.generate([Message(role="user", content="hi")], GenerationConfig())

    assert provider.generate_calls == [CATALOG[0]] * 5


@pytest.mark.asyncio
async def test_a_failing_model_is_not_swapped_for_another_one():
    """Failover belongs to the LLM service now. A model that errors is
    reported as an error, not quietly replaced — a quiet replacement is
    what made the answer's author unpredictable."""
    provider = FakeProvider(fail_with=[RuntimeError("500 upstream boom")] * 2)
    client = _client(provider)

    with pytest.raises(RuntimeError):
        await client.generate(
            [Message(role="user", content="hi")],
            GenerationConfig(),
            preferred_model="model-b",
        )

    assert set(provider.generate_calls) == {"model-b"}, "retried on itself, never on a sibling"


@pytest.mark.asyncio
async def test_a_transient_error_is_retried_on_the_same_model():
    provider = FakeProvider(fail_with=[RuntimeError("503 temporarily unavailable")])
    client = ModelClient(models=list(CATALOG), provider=provider, retry_delay=0)

    model_used, response = await client.generate(
        [Message(role="user", content="hi")],
        GenerationConfig(),
        preferred_model="model-b",
    )

    assert provider.generate_calls == ["model-b", "model-b"]
    assert model_used == "model-b"
    assert response.content == "reply-from-model-b"


@pytest.mark.asyncio
async def test_a_quota_error_is_not_retried():
    """A 429 says back off; an immediate second attempt is the one
    response guaranteed not to help."""
    provider = FakeProvider(fail_with=[RuntimeError("429 rate_limit exceeded")])
    client = ModelClient(models=list(CATALOG), provider=provider, retry_delay=0)

    with pytest.raises(RuntimeError):
        await client.generate([Message(role="user", content="hi")], GenerationConfig())

    assert provider.generate_calls == [CATALOG[0]]


@pytest.mark.asyncio
async def test_stream_retries_the_same_model_and_discards_the_partial_turn():
    """Buffering is what makes a retry safe: half an answer followed by a
    fresh start would otherwise reach the caller as one turn."""
    provider = FakeProvider(fail_with=[RuntimeError("500 upstream boom")])
    client = ModelClient(models=list(CATALOG), provider=provider, retry_delay=0)

    chunks = [
        chunk
        async for chunk in client.stream(
            [Message(role="user", content="hi")],
            GenerationConfig(),
            preferred_model="model-c",
        )
    ]

    assert provider.stream_calls == ["model-c", "model-c"]
    assert [c.content for c in chunks] == ["reply-from-model-c"]
