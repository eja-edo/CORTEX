from __future__ import annotations

import json
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.config import settings
from app.services.agent.base_provider import LLMProvider
from app.services.agent.provider_types import (
    Message,
    GenerationConfig,
    ProviderResponse,
    ProviderStreamChunk,
    ToolCall,
    ToolDefinition,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )


_openai_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = _get_openai_client()
    return _openai_client


class OpenAIProvider(LLMProvider):
    def get_model_key(self, model: str) -> str:
        return model

    def get_usage(self, response: ProviderResponse) -> dict[str, int] | None:
        return response.usage

    async def generate(
        self,
        model: str,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
    ) -> ProviderResponse:
        openai_messages = self._messages_to_openai(messages, config)
        openai_tools = self._tools_to_openai(tools) if tools else None
        kwargs = self._config_to_openai_kwargs(config, openai_tools)

        client = _get_client()
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=openai_messages,
                **kwargs,
            )
        except Exception as exc:
            logger.error(f"OpenAIProvider.generate error on {model}: {exc}")
            raise

        return self._openai_response_to_provider(response)

    async def generate_stream(
        self,
        model: str,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[ProviderStreamChunk]:
        openai_messages = self._messages_to_openai(messages, config)
        openai_tools = self._tools_to_openai(tools) if tools else None
        kwargs = self._config_to_openai_kwargs(config, openai_tools)
        kwargs["stream"] = True

        client = _get_client()
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=openai_messages,
                **kwargs,
            )
            async for chunk in stream:
                yield self._openai_chunk_to_provider(chunk)
        except Exception as exc:
            logger.error(f"OpenAIProvider.generate_stream error on {model}: {exc}")
            raise

    def _messages_to_openai(
        self,
        messages: list[Message],
        config: GenerationConfig,
    ) -> list[dict]:
        result: list[dict] = []

        if config.system_instruction:
            result.append({
                "role": "system",
                "content": config.system_instruction,
            })

        for msg in messages:
            if msg.role == "user":
                if msg.tool_result:
                    result.append({
                        "role": "tool",
                        "tool_call_id": msg.tool_result.tool_call_id,
                        "content": json.dumps(msg.tool_result.content, default=str),
                    })
                else:
                    result.append({
                        "role": "user",
                        "content": msg.content or "",
                    })
            elif msg.role == "assistant":
                entry: dict = {"role": "assistant"}
                if msg.content:
                    entry["content"] = msg.content
                else:
                    entry["content"] = None
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.args, default=str),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(entry)
            elif msg.role == "tool" and msg.tool_result:
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_result.tool_call_id,
                    "content": json.dumps(msg.tool_result.content, default=str),
                })

        return result

    def _tools_to_openai(self, tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    def _config_to_openai_kwargs(
        self,
        config: GenerationConfig,
        tools: list[dict] | None = None,
    ) -> dict:
        kwargs: dict = {}

        if config.temperature is not None:
            kwargs["temperature"] = config.temperature

        if config.max_output_tokens is not None:
            kwargs["max_tokens"] = config.max_output_tokens

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        if config.response_schema and config.response_mime_type == "application/json":
            kwargs["response_format"] = {"type": "json_object"}

        return kwargs

    def _openai_response_to_provider(self, response: object) -> ProviderResponse:
        choice = response.choices[0] if hasattr(response, "choices") and response.choices else None
        if not choice:
            return ProviderResponse()

        message = getattr(choice, "message", None)
        if not message:
            return ProviderResponse()

        content = getattr(message, "content", None)
        tool_calls: list[ToolCall] = []

        openai_tool_calls = getattr(message, "tool_calls", None) or []
        for tc in openai_tool_calls:
            fn = getattr(tc, "function", None)
            if fn:
                args_str = getattr(fn, "arguments", "{}")
                try:
                    args = json.loads(args_str)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=getattr(tc, "id", ""),
                        name=getattr(fn, "name", "unknown"),
                        args=args,
                    )
                )

        usage = None
        usage_data = getattr(response, "usage", None)
        if usage_data:
            usage = {
                "prompt_tokens": getattr(usage_data, "prompt_tokens", 0),
                "completion_tokens": getattr(usage_data, "completion_tokens", 0),
                "total_tokens": getattr(usage_data, "total_tokens", 0),
            }

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=getattr(choice, "finish_reason", None),
            usage=usage,
        )

    def _openai_chunk_to_provider(self, chunk: object) -> ProviderStreamChunk:
        content: str | None = None
        tool_calls: list[ToolCall] = []
        finish_reason: str | None = None

        if hasattr(chunk, "choices") and chunk.choices:
            delta = getattr(chunk.choices[0], "delta", None)
            if delta:
                content = getattr(delta, "content", None)
                openai_tool_calls = getattr(delta, "tool_calls", None) or []
                for tc in openai_tool_calls:
                    fn = getattr(tc, "function", None)
                    if fn:
                        args_str = getattr(fn, "arguments", "{}")
                        try:
                            args = json.loads(args_str)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        tool_calls.append(
                            ToolCall(
                                id=getattr(tc, "id", ""),
                                name=getattr(fn, "name", "unknown"),
                                args=args,
                            )
                        )
                finish_reason = getattr(chunk.choices[0], "finish_reason", None)

        return ProviderStreamChunk(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=finish_reason,
        )
