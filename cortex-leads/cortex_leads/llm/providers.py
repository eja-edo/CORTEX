import asyncio
import inspect
import json
from collections.abc import Callable
from typing import Any, Protocol

import httpx
import openai

from cortex_leads.config import get_settings
from cortex_leads.core.errors import ConfigError
from cortex_leads.llm.types import (
    LLMError,
    LLMFatalError,
    LLMQuotaError,
    LLMResult,
    LLMTransientError,
    ScriptExhaustedError,
    ToolCall,
)


class Provider(Protocol):
    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, model: str | None
    ) -> LLMResult: ...


# port từ backend/app/ai/agents/model_client.py (is_fatal_error / is_quota_error /
# is_retryable_error), but by status_code / exception type rather than message text.
_FATAL_STATUS = {400, 401, 403, 404, 422}


def classify_error(exc: BaseException) -> Exception:
    """Map any provider exception to LLMFatalError / LLMQuotaError / LLMTransientError."""
    if isinstance(exc, LLMError):
        return exc
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status == 429:
            return LLMQuotaError(f"quota/rate limit (429): {str(exc)[:200]}")
        if status in _FATAL_STATUS:
            return LLMFatalError(f"HTTP {status}: {str(exc)[:200]}")
        if status >= 500:
            return LLMTransientError(f"HTTP {status}: {str(exc)[:200]}")
    if isinstance(exc, (openai.APIConnectionError, httpx.TransportError, asyncio.TimeoutError)):
        return LLMTransientError(f"connection/timeout: {str(exc)[:200]}")
    return LLMFatalError(f"unclassified provider error: {type(exc).__name__}: {str(exc)[:200]}")


class OpenAICompatibleProvider:
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None,
                 default_model: str | None = None) -> None:
        s = get_settings()
        base_url, api_key = base_url or s.LLM_BASE_URL, api_key or s.LLM_API_KEY
        self._model = default_model or s.LLM_MODEL_LITE
        if not (base_url and api_key and self._model):
            raise ConfigError("CL_LLM_BASE_URL, CL_LLM_API_KEY, CL_LLM_MODEL_LITE are required")
        # The gateway owns retries; the SDK must not stack its own on top.
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None = None, model: str | None = None
    ) -> LLMResult:
        used = model or self._model
        kwargs: dict[str, Any] = {"model": used, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise classify_error(exc) from exc
        if not resp.choices:  # gateway sometimes answers 200 with an empty body
            raise LLMTransientError("empty response (no choices)")
        msg = resp.choices[0].message
        calls = [self._tool_call(tc) for tc in (msg.tool_calls or [])]
        usage = resp.usage
        return LLMResult(
            content=msg.content, tool_calls=calls,
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            model=resp.model or used,
        )

    @staticmethod
    def _tool_call(tc: Any) -> ToolCall:
        raw = tc.function.arguments or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError as e:
            return ToolCall(tc.id, tc.function.name, {}, parse_error=f"invalid JSON: {e}")
        if not isinstance(args, dict):
            return ToolCall(tc.id, tc.function.name, {}, parse_error="arguments not an object")
        return ToolCall(tc.id, tc.function.name, args)


class FakeProvider:
    """Scripted provider for tests. Items: LLMResult, Exception (raised), or a callable
    (messages, tools) -> LLMResult | Exception, sync or async."""

    def __init__(self, script: list[LLMResult | Exception | Callable[..., Any]]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None = None, model: str | None = None
    ) -> LLMResult:
        self.calls.append({"messages": messages, "tools": tools, "model": model})
        if not self._script:
            raise ScriptExhaustedError(
                f"FakeProvider script exhausted after {len(self.calls) - 1} call(s)"
            )
        item = self._script.pop(0)
        if callable(item) and not isinstance(item, LLMResult):
            item = item(messages, tools)
            if inspect.isawaitable(item):
                item = await item
        if isinstance(item, BaseException):
            raise item
        return item
