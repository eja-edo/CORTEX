"""Unit tests for ModelClient's model-catalogue wiring and selection.

Covers the regression this catalogue was introduced to fix: ModelClient
used to be constructed from a single-model default (settings.OPENAI_DEFAULT_MODEL),
so a user-selected `preferred_model` was silently dropped whenever it wasn't
that one model — `preferred_model not in self._models` was always true for
any catalogue entry other than the default.
"""

import pytest

from app.ai.agents.base_provider import LLMProvider
from app.ai.agents.model_catalog import ModelSpec, ModelLimits
from app.ai.agents.model_client import ModelClient, get_default_models
from app.ai.agents.provider_types import GenerationConfig, Message, ProviderResponse, ProviderStreamChunk


class FakeProvider(LLMProvider):
    """Records which model each call was made with; never raises."""

    def __init__(self):
        self.generate_calls: list[str] = []
        self.stream_calls: list[str] = []

    async def generate(self, model, messages, config, tools=None) -> ProviderResponse:
        self.generate_calls.append(model)
        return ProviderResponse(content=f"reply-from-{model}")

    async def generate_stream(self, model, messages, config, tools=None):
        self.stream_calls.append(model)
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

    assert model_used in CATALOG
    assert provider.generate_calls == [model_used]


@pytest.mark.asyncio
async def test_stream_with_fallback_uses_preferred_model_when_in_catalogue():
    provider = FakeProvider()
    client = _client(provider)

    chunks = [
        chunk
        async for chunk in client.stream_with_fallback(
            [Message(role="user", content="hi")],
            GenerationConfig(),
            preferred_model="model-c",
        )
    ]

    assert provider.stream_calls == ["model-c"]
    assert chunks[-1].content == "reply-from-model-c"


@pytest.mark.asyncio
async def test_stream_with_fallback_ignores_unknown_preferred_model():
    provider = FakeProvider()
    client = _client(provider)

    async for _ in client.stream_with_fallback(
        [Message(role="user", content="hi")],
        GenerationConfig(),
        preferred_model="unknown-model",
    ):
        pass

    assert provider.stream_calls == [CATALOG[0]]


def test_budgets_pull_limits_from_catalog_spec(monkeypatch):
    import app.ai.agents.model_client as model_client_module

    custom_spec = ModelSpec(id="model-a", label="A", limits=ModelLimits(rpm=1, tpm=None, rpd=1))
    monkeypatch.setattr(
        model_client_module, "get_model_spec",
        lambda model_id: custom_spec if model_id == "model-a" else None,
    )

    client = ModelClient(models=["model-a"], provider=FakeProvider())
    budget = client._budgets["model-a"]

    assert budget.can_use() is True
    budget.record_request()
    assert budget.can_use() is False  # rpm=1 exhausted after one request
