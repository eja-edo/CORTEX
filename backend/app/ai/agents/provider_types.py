from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: dict[str, Any]


@dataclass
class Message:
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_result: ToolResult | None = None
    created_at: datetime | None = None


@dataclass
class GenerationConfig:
    system_instruction: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    response_schema: dict[str, Any] | None = None
    response_mime_type: str | None = None


@dataclass
class ProviderResponse:
    content: str | None = None
    # Một số model suy luận sau gateway OpenAI-compatible trả lời trong
    # `reasoning_content` và để `content` rỗng. `ProviderStreamChunk` đã có
    # trường này từ đầu; nhánh không-stream thì không, nên câu trả lời rơi
    # mất im lặng — xem `_openai_response_to_provider`.
    reasoning: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


@dataclass
class ProviderStreamChunk:
    content: str | None = None
    reasoning: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
