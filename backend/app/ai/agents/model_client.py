"""
Unified LLM client supporting OpenAI-compatible providers.

Design
------
- Provider-agnostic: works with internal Message / GenerationConfig types.
- One request runs on exactly one model: the one asked for, or the
  default. No rotation, no cross-model fallback — see `ModelClient`.
- Retry for transient errors (500/503) on that same model.
- Streaming buffers the turn before yielding it.

Usage
-----
    from app.ai.agents.model_client import ModelClient
    from app.ai.agents.provider_types import Message, GenerationConfig

    client = ModelClient()
    model_used, response = await client.generate(messages, config, tools=tools)

    async for chunk in client.stream(messages, config, tools=tools):
        ...
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from app.config import settings
from app.ai.agents.base_provider import LLMProvider
from app.ai.agents.openai_provider import OpenAIProvider
from app.ai.agents.model_catalog import enabled_model_ids
from app.ai.agents.provider_types import (
    Message,
    GenerationConfig,
    ProviderResponse,
    ProviderStreamChunk,
    ToolDefinition,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def get_default_provider() -> LLMProvider:
    return OpenAIProvider()


def get_default_model(provider: LLMProvider | None = None) -> str:
    return settings.OPENAI_DEFAULT_MODEL


def get_default_models() -> list[str]:
    return enabled_model_ids()


RETRY_MAX_ATTEMPTS: int = 2
RETRY_DELAY_SECONDS: float = 2.0


# ---------------------------------------------------------------------------
# Error classifiers
# ---------------------------------------------------------------------------

_TRULY_FATAL_CODES: frozenset[str] = frozenset({"401", "403", "404"})


def is_fatal_error(exc: Exception) -> bool:
    s = str(exc)
    return any(code in s for code in _TRULY_FATAL_CODES)


def is_model_incompatible_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return "not supported" in s or "does not support" in s or "not found" in s


def is_quota_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return "429" in s or "quota" in s or "rate_limit" in s


def is_retryable_error(exc: Exception) -> bool:
    if is_quota_error(exc):
        return False
    s = str(exc)
    return "500" in s or "503" in s


# ---------------------------------------------------------------------------
# ModelClient
# ---------------------------------------------------------------------------

class ModelClient:
    """
    Provider-agnostic LLM client: one request, one model, plus a retry for
    transient errors.

    **There is deliberately no rotation and no cross-model fallback.**
    There used to be: a process-wide cursor walked the catalogue, each
    request started where the last success left off, and a failure slid
    down to the next model. It worked, and it was the wrong layer. Two
    reasons it had to go:

    - *It made the answer's author unpredictable.* Consecutive turns in
      one conversation were served by different models, so tone, format
      and capability shifted for no reason the user could see or control
      — and picking a model in the UI only expressed a preference, since
      a single hiccup silently moved the turn elsewhere.
    - *It duplicated the provider.* Everything reachable through
      `OPENAI_BASE_URL` is a proxy that already does its own routing and
      failover across upstreams, with a real view of their health. This
      client only ever had a guess: a hardcoded local rate-limit budget
      (15 rpm / 1500 rpd for every model, whatever the provider's actual
      quota) that skipped models *before calling them* — so a wrong guess
      became a refusal to make a request the provider would have served.

    What replaces it is the plain reading of the request: the chosen
    model, or the default when none was chosen. Failover is the LLM
    service's job now, and an error from it is reported rather than
    worked around.
    """

    def __init__(
        self,
        models: list[str] | None = None,
        provider: LLMProvider | None = None,
        retry_attempts: int = RETRY_MAX_ATTEMPTS,
        retry_delay: float = RETRY_DELAY_SECONDS,
    ) -> None:
        self._provider = provider or get_default_provider()
        self._models: list[str] = models or get_default_models()
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay

    def _resolve(self, preferred: str | None) -> str:
        """Which model this request runs on, and the only place that is
        decided.

        An unrecognised name falls back to the default rather than being
        passed through: the catalogue is what the UI offers, and sending
        the provider something outside it turns a stale client — or a
        typo — into a 404 mid-conversation. `"auto"` lands here too, and
        that is the point: it means "the default", not "whichever one is
        the provider's turn".
        """
        if preferred and preferred in self._models:
            return preferred
        return self._models[0] if self._models else get_default_model(self._provider)

    # ------------------------------------------------------------------
    # Public API — non-streaming
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
        preferred_model: str | None = None,
    ) -> tuple[str, ProviderResponse]:
        model = self._resolve(preferred_model)
        response = await self._call_with_retry(
            self._call_generate, model, messages, config, tools
        )
        return model, response

    # ------------------------------------------------------------------
    # Public API — streaming
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
        preferred_model: str | None = None,
    ) -> AsyncIterator[ProviderStreamChunk]:
        """
        Stream one turn from the chosen model.

        Chunks are buffered and only yielded once the stream completes.
        That was originally what made mid-stream fallback possible — half
        an answer from one model followed by half from another is worse
        than either — and it stays for the retry below, which has the
        same problem in miniature: a stream that dies after twenty tokens
        must be able to start over cleanly.

        The cost is real and worth stating: nothing reaches the caller
        until the model has finished, so "streaming" here is about the
        caller not having to wait for a full request/response round trip,
        not about tokens appearing as the model writes them.
        """
        model = self._resolve(preferred_model)
        last_exc: Exception | None = None

        for attempt in range(1, self._retry_attempts + 1):
            buffered: list[ProviderStreamChunk] = []
            try:
                stream = self._provider.generate_stream(
                    model=model, messages=messages, config=config, tools=tools
                )
                async for chunk in stream:
                    buffered.append(chunk)
            except Exception as exc:
                last_exc = exc
                if is_fatal_error(exc) or is_quota_error(exc):
                    logger.error(f"stream: {model} failed, not retryable → {str(exc)[:200]}")
                    raise
                if is_retryable_error(exc) and attempt < self._retry_attempts:
                    logger.warning(
                        f"stream: transient error on {model} attempt "
                        f"{attempt}/{self._retry_attempts} after {len(buffered)} "
                        f"buffered chunks (discarded), waiting {self._retry_delay}s. "
                        f"{str(exc)[:120]}"
                    )
                    await asyncio.sleep(self._retry_delay)
                    continue
                logger.error(f"stream: {model} failed → {str(exc)[:200]}", exc_info=True)
                raise

            logger.info(f"stream: {model} OK ({len(buffered)} chunks)")
            for chunk in buffered:
                yield chunk
            return

        raise last_exc  # unreachable: the loop either returns or raises

    # ------------------------------------------------------------------
    # Retry for transient errors
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self, call_fn, model: str,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None,
    ) -> ProviderResponse:
        """Retries 500/503 only. A 429 is not retried here — the provider
        is telling us to back off, and an immediate second attempt is the
        one response guaranteed not to help."""
        last_exc: Exception | None = None

        for attempt in range(1, self._retry_attempts + 1):
            try:
                return await call_fn(model, messages, config, tools)
            except Exception as exc:
                last_exc = exc

                if is_fatal_error(exc) or is_quota_error(exc):
                    raise

                if is_retryable_error(exc):
                    if attempt < self._retry_attempts:
                        logger.warning(
                            f"ModelClient: retryable error on {model} "
                            f"attempt {attempt}/{self._retry_attempts}, "
                            f"waiting {self._retry_delay}s. {str(exc)[:120]}"
                        )
                        await asyncio.sleep(self._retry_delay)
                        continue

                logger.error(f"ModelClient: unknown error on {model}: {str(exc)[:200]}", exc_info=True)
                raise

        raise last_exc

    # ------------------------------------------------------------------
    # Low-level SDK wrappers (delegate to provider)
    # ------------------------------------------------------------------

    async def _call_generate(
        self,
        model: str,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None,
    ) -> ProviderResponse:
        return await self._provider.generate(
            model=model,
            messages=messages,
            config=config,
            tools=tools,
        )
