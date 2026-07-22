from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.ai.agents.provider_types import (
    Message,
    GenerationConfig,
    ProviderResponse,
    ProviderStreamChunk,
    ToolDefinition,
)


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        model: str,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
    ) -> ProviderResponse:
        ...

    @abstractmethod
    async def generate_stream(
        self,
        model: str,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[ProviderStreamChunk]:
        ...

    @abstractmethod
    def get_model_key(self, model: str) -> str:
        ...

    @abstractmethod
    def get_usage(self, response: ProviderResponse) -> dict[str, int] | None:
        ...
