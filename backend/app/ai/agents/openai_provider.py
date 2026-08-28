from __future__ import annotations

import json
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.config import settings
from app.ai.agents.base_provider import LLMProvider
from app.ai.agents.provider_types import (
    Message,
    GenerationConfig,
    ToolDefinition,
    ToolCall,
    ProviderResponse,
    ProviderStreamChunk,
)

# Maximum character length for serialized tool output sent to the LLM.
# Longer outputs are truncated with a note. Prevents context-window waste
# from verbose tool results (search hits, file contents, etc.).
TOOL_OUTPUT_MAX_CHARS = 4000
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
        kwargs["stream_options"] = {"include_usage": True}

        accumulated_usage: dict[str, int] | None = None

        client = _get_client()
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=openai_messages,
                **kwargs,
            )

            accumulated_tool_calls: dict[int, dict] = {}

            async for chunk in stream:
                # Final usage-only chunk has no choices but carries `usage`
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    accumulated_usage = {
                        "prompt_tokens": getattr(chunk_usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(chunk_usage, "completion_tokens", 0),
                        "total_tokens": getattr(chunk_usage, "total_tokens", 0),
                    }

                if not (hasattr(chunk, "choices") and chunk.choices):
                    continue

                delta = getattr(chunk.choices[0], "delta", None)
                finish_reason = getattr(chunk.choices[0], "finish_reason", None)
                content = None

                if delta:
                    content = getattr(delta, "content", None)
                    reasoning = getattr(delta, "reasoning_content", None)

                    openai_tool_calls = getattr(delta, "tool_calls", None) or []
                    for tc in openai_tool_calls:
                        idx = getattr(tc, "index", 0)
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}

                        tc_id = getattr(tc, "id", None)
                        if tc_id:
                            accumulated_tool_calls[idx]["id"] = tc_id

                        fn = getattr(tc, "function", None)
                        if fn:
                            fn_name = getattr(fn, "name", None)
                            if fn_name:
                                accumulated_tool_calls[idx]["name"] = fn_name
                            fn_args = getattr(fn, "arguments", None)
                            if fn_args:
                                accumulated_tool_calls[idx]["arguments"] += fn_args

                if finish_reason:
                    tool_calls: list[ToolCall] = []
                    for idx in sorted(accumulated_tool_calls.keys()):
                        acc = accumulated_tool_calls[idx]
                        if acc["name"]:
                            try:
                                args = json.loads(acc["arguments"]) if acc["arguments"] else {}
                            except (json.JSONDecodeError, TypeError):
                                args = {}
                            tool_calls.append(
                                ToolCall(
                                    id=acc["id"] or f"tc_{idx}",
                                    name=acc["name"],
                                    args=args,
                                )
                            )
                    accumulated_tool_calls.clear()
                    yield ProviderStreamChunk(
                        content=content,
                        reasoning=reasoning,
                        tool_calls=tool_calls if tool_calls else None,
                        finish_reason=finish_reason,
                        usage=accumulated_usage,
                    )
                    accumulated_usage = None
                else:
                    if content:
                        yield ProviderStreamChunk(content=content)
                    if reasoning:
                        yield ProviderStreamChunk(reasoning=reasoning)

            if accumulated_usage:
                yield ProviderStreamChunk(usage=accumulated_usage)
        except Exception as exc:
            logger.error(f"OpenAIProvider.generate_stream error on {model}: {exc}")
            raise

    @staticmethod
    def _truncate_tool_output(content: dict) -> str:
        """Serialize a tool-output dict, truncating to TOOL_OUTPUT_MAX_CHARS.

        The full output is still stored in the DB; only the LLM-prompt
        copy is truncated.
        """
        serialized = json.dumps(content, default=str)
        if len(serialized) <= TOOL_OUTPUT_MAX_CHARS:
            return serialized
        truncated = serialized[:TOOL_OUTPUT_MAX_CHARS]
        return truncated + (
            f"\n\n[Output truncated at {TOOL_OUTPUT_MAX_CHARS} chars; "
            f"original size was {len(serialized)} chars]"
        )

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
                    "content": self._truncate_tool_output(msg.tool_result.content),
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
        # Hai lối thoát sớm này từng im lặng, và chúng là lối hay đi nhất
        # khi gateway hỏng: response về nhưng `choices` rỗng. Người dùng nhận
        # "I couldn't process your request." — câu nói rằng *tin nhắn của họ*
        # có vấn đề, trong khi thật ra dịch vụ mới là thứ hỏng. Log để phân
        # biệt được hai ca đó trong log thay vì đoán.
        choice = response.choices[0] if hasattr(response, "choices") and response.choices else None
        if not choice:
            logger.warning(
                "Gateway returned a response with no choices (usage=%s)",
                getattr(response, "usage", None),
            )
            return ProviderResponse()

        message = getattr(choice, "message", None)
        if not message:
            logger.warning("Gateway returned a choice with no message")
            return ProviderResponse()

        content = getattr(message, "content", None)
        # Gateway đặt phần suy luận ở đâu thì tuỳ model; thử các tên đã gặp.
        reasoning = None
        for attr in ("reasoning_content", "reasoning"):
            value = getattr(message, attr, None)
            if isinstance(value, str) and value.strip():
                reasoning = value
                break
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

        if not content and not tool_calls:
            # Không có gì để trả cho người dùng. Trước đây chỗ này im lặng và
            # người dùng nhận "I couldn't process your request." dù model đã
            # sinh cả trăm token — không có cách nào biết token đi đâu. Ghi
            # lại các trường thật sự có trên message để lần sau đọc log là ra.
            logger.warning(
                "Model returned no content and no tool calls "
                "(finish_reason=%s, fields=%s, reasoning=%s chars)",
                getattr(choice, "finish_reason", None),
                sorted(
                    k for k in vars(message).keys()
                    if not k.startswith("_")
                ) if hasattr(message, "__dict__") else "n/a",
                len(reasoning) if reasoning else 0,
            )

        return ProviderResponse(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=getattr(choice, "finish_reason", None),
            usage=usage,
        )


