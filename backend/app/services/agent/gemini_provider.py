from __future__ import annotations

from typing import AsyncIterator

from google import genai
from google.genai import types as gemini_types

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

_gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)


class GeminiProvider(LLMProvider):
    def get_model_key(self, model: str) -> str:
        if model.startswith("models/"):
            return model
        return f"models/{model}"

    def get_usage(self, response: ProviderResponse) -> dict[str, int] | None:
        return response.usage

    async def generate(
        self,
        model: str,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
    ) -> ProviderResponse:
        contents = self._messages_to_contents(messages)
        gen_config = self._config_to_gemini(config, tools)

        try:
            response = _gemini_client.models.generate_content(
                model=model,
                contents=contents,
                config=gen_config,
            )
        except Exception as exc:
            logger.error(f"GeminiProvider.generate error on {model}: {exc}")
            raise

        return self._gemini_response_to_provider(response)

    async def generate_stream(
        self,
        model: str,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[ProviderStreamChunk]:
        contents = self._messages_to_contents(messages)
        gen_config = self._config_to_gemini(config, tools)

        try:
            stream = _gemini_client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=gen_config,
            )
            for chunk in stream:
                yield self._gemini_chunk_to_provider(chunk)
        except Exception as exc:
            logger.error(f"GeminiProvider.generate_stream error on {model}: {exc}")
            raise

    def _messages_to_contents(self, messages: list[Message]) -> list[gemini_types.Content]:
        contents: list[gemini_types.Content] = []
        for msg in messages:
            if msg.role == "user":
                if msg.tool_result:
                    contents.append(
                        gemini_types.Content(
                            role="user",
                            parts=[
                                gemini_types.Part.from_function_response(
                                    name=msg.tool_result.name,
                                    response=msg.tool_result.content,
                                )
                            ],
                        )
                    )
                else:
                    contents.append(
                        gemini_types.Content(
                            role="user",
                            parts=[gemini_types.Part.from_text(text=msg.content or "")],
                        )
                    )
            elif msg.role == "assistant":
                if msg.tool_calls:
                    parts = [
                        gemini_types.Part.from_function_call(tc.name, tc.args)
                        for tc in msg.tool_calls
                    ]
                    contents.append(gemini_types.Content(role="model", parts=parts))
                else:
                    contents.append(
                        gemini_types.Content(
                            role="model",
                            parts=[gemini_types.Part.from_text(text=msg.content or "")],
                        )
                    )
            elif msg.role == "tool" and msg.tool_result:
                contents.append(
                    gemini_types.Content(
                        role="user",
                        parts=[
                            gemini_types.Part.from_function_response(
                                name=msg.tool_result.name,
                                response=msg.tool_result.content,
                            )
                        ],
                    )
                )

        merged = self._merge_consecutive_function_responses(contents)
        return merged

    def _merge_consecutive_function_responses(self, contents: list[gemini_types.Content]) -> list[gemini_types.Content]:
        merged: list[gemini_types.Content] = []
        for content in contents:
            if merged and self._is_function_response(content) and self._is_function_response(merged[-1]):
                merged[-1].parts.extend(content.parts)
            else:
                merged.append(content)
        return merged

    def _is_function_response(self, content: gemini_types.Content) -> bool:
        if content.role != "user":
            return False
        if not content.parts:
            return False
        return any(
            getattr(p, "function_response", None) is not None
            for p in content.parts
        )

    def _config_to_gemini(
        self,
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
    ) -> gemini_types.GenerateContentConfig:
        kwargs: dict = {}

        if config.system_instruction:
            kwargs["system_instruction"] = config.system_instruction

        if config.temperature is not None:
            kwargs["temperature"] = config.temperature

        if config.max_output_tokens is not None:
            kwargs["max_output_tokens"] = config.max_output_tokens

        if config.response_schema and config.response_mime_type:
            kwargs["response_schema"] = config.response_schema
            kwargs["response_mime_type"] = config.response_mime_type

        if tools:
            kwargs["tools"] = self._tools_to_gemini(tools)
            kwargs["automatic_function_calling"] = gemini_types.AutomaticFunctionCallingConfig(
                disable=True
            )

        return gemini_types.GenerateContentConfig(**kwargs)

    def _tools_to_gemini(self, tools: list[ToolDefinition]) -> list[gemini_types.Tool]:
        declarations = [
            gemini_types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters_json_schema=t.parameters,
            )
            for t in tools
        ]
        return [gemini_types.Tool(function_declarations=declarations)]

    def _gemini_response_to_provider(self, response: object) -> ProviderResponse:
        tool_calls: list[ToolCall] = []
        content: str | None = None

        function_calls = getattr(response, "function_calls", None) or []
        if function_calls:
            for i, fc in enumerate(function_calls):
                tool_calls.append(
                    ToolCall(
                        id=getattr(fc, "name", f"fc_{i}"),
                        name=getattr(fc, "name", "unknown"),
                        args=dict(getattr(fc, "args", {}) or {}),
                    )
                )

        try:
            content = getattr(response, "text", None)
        except (ValueError, AttributeError):
            content = None

        usage = None
        metadata = getattr(response, "usage_metadata", None)
        if metadata:
            usage = {
                "prompt_tokens": getattr(metadata, "prompt_token_count", 0),
                "completion_tokens": getattr(metadata, "candidates_token_count", 0),
                "total_tokens": getattr(metadata, "total_token_count", 0),
            }

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
        )

    def _gemini_chunk_to_provider(self, chunk: object) -> ProviderStreamChunk:
        tool_calls: list[ToolCall] = []
        content: str | None = None

        if hasattr(chunk, "text") and chunk.text:
            content = chunk.text

        function_calls = getattr(chunk, "function_calls", None) or []
        if function_calls:
            for i, fc in enumerate(function_calls):
                tool_calls.append(
                    ToolCall(
                        id=getattr(fc, "name", f"fc_{i}"),
                        name=getattr(fc, "name", "unknown"),
                        args=dict(getattr(fc, "args", {}) or {}),
                    )
                )

        finish_reason = None
        if hasattr(chunk, "candidates") and chunk.candidates:
            candidate = chunk.candidates[0]
            if hasattr(candidate, "finish_reason"):
                finish_reason = str(candidate.finish_reason)

        return ProviderStreamChunk(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=finish_reason,
        )
