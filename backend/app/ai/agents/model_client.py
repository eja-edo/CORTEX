"""
Unified LLM client supporting OpenAI-compatible providers.

Design
------
- Provider-agnostic: works with internal Message / GenerationConfig types.
- Round-robin model selection with rate-limit budget tracking.
- Per-model retry for transient errors.
- Ordered fallback across all models.
- Streaming with buffered fallback.

Usage
-----
    from app.ai.agents.model_client import ModelClient
    from app.ai.agents.provider_types import Message, GenerationConfig

    client = ModelClient()
    response = await client.generate(messages, config, tools=tools)

    async for chunk in client.stream_with_fallback(messages, config, tools=tools):
        ...
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Deque, AsyncIterator

from app.config import settings
from app.ai.agents.base_provider import LLMProvider
from app.ai.agents.openai_provider import OpenAIProvider
from app.ai.agents.model_catalog import ModelLimits, DEFAULT_LIMITS, enabled_model_ids, get_model_spec
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


EST_TOKENS_PER_REQUEST: int = 1_500
RETRY_MAX_ATTEMPTS: int = 2
RETRY_DELAY_SECONDS: float = 2.0
STREAM_ROTATION_RETRIES: int = 2
BUDGET_SAFETY_MARGIN: float = 0.05


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
# Custom exceptions
# ---------------------------------------------------------------------------

class AllModelsExhaustedError(Exception):
    """All models are over their rate-limit budget or otherwise unavailable."""


# ---------------------------------------------------------------------------
# Per-model rate-limit budget tracker
# ---------------------------------------------------------------------------

class RateLimitBudget:
    _WINDOW: float = 60.0

    def __init__(self, limits: ModelLimits) -> None:
        self._limits = limits
        self._lock = threading.Lock()
        self._rpm_window: Deque[float] = deque()
        self._tpm_window: Deque[tuple[float, int]] = deque()
        self._rpd_date: str = ""
        self._rpd_count: int = 0
        self._blocked_until: float = 0.0

    def can_use(self, estimated_tokens: int = EST_TOKENS_PER_REQUEST) -> bool:
        with self._lock:
            now = time.monotonic()
            today = _utc_date()
            if now < self._blocked_until:
                return False
            self._evict(now)
            self._reset_rpd_if_needed(today)
            lim = self._limits
            margin = 1.0 - BUDGET_SAFETY_MARGIN
            if len(self._rpm_window) >= lim.rpm * margin:
                return False
            if lim.tpm is not None:
                used_tpm = sum(t for _, t in self._tpm_window)
                if used_tpm + estimated_tokens >= lim.tpm * margin:
                    return False
            if self._rpd_count >= lim.rpd * margin:
                return False
            return True

    def record_request(self, estimated_tokens: int = EST_TOKENS_PER_REQUEST) -> None:
        with self._lock:
            now = time.monotonic()
            today = _utc_date()
            self._evict(now)
            self._reset_rpd_if_needed(today)
            self._rpm_window.append(now)
            if self._limits.tpm is not None:
                self._tpm_window.append((now, estimated_tokens))
            self._rpd_count += 1

    def update_tokens(self, actual_tokens: int) -> None:
        if self._limits.tpm is None:
            return
        with self._lock:
            if not self._tpm_window:
                return
            ts, _ = self._tpm_window[-1]
            self._tpm_window[-1] = (ts, actual_tokens)

    def penalise(self) -> None:
        with self._lock:
            self._blocked_until = time.monotonic() + self._WINDOW

    def status(self) -> dict:
        with self._lock:
            now = time.monotonic()
            today = _utc_date()
            self._evict(now)
            self._reset_rpd_if_needed(today)
            lim = self._limits
            tpm_used = sum(t for _, t in self._tpm_window) if lim.tpm else None
            return {
                "rpm_used": len(self._rpm_window),
                "rpm_limit": lim.rpm,
                "tpm_used": tpm_used,
                "tpm_limit": lim.tpm,
                "rpd_used": self._rpd_count,
                "rpd_limit": lim.rpd,
                "hard_blocked": now < self._blocked_until,
                "blocked_secs_remaining": max(0.0, self._blocked_until - now),
            }

    def _evict(self, now: float) -> None:
        cutoff = now - self._WINDOW
        while self._rpm_window and self._rpm_window[0] < cutoff:
            self._rpm_window.popleft()
        while self._tpm_window and self._tpm_window[0][0] < cutoff:
            self._tpm_window.popleft()

    def _reset_rpd_if_needed(self, today: str) -> None:
        if today != self._rpd_date:
            self._rpd_date = today
            self._rpd_count = 0


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# ModelClient
# ---------------------------------------------------------------------------

class ModelClient:
    """
    Provider-agnostic LLM client with round-robin, rate-limit tracking,
    per-model retry, and ordered fallback across models.
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

        self._cursor: int = 0
        self._lock = threading.Lock()

        self._budgets: dict[str, RateLimitBudget] = {}
        for m in self._models:
            spec = get_model_spec(m)
            limits = spec.limits if spec else DEFAULT_LIMITS
            self._budgets[m] = RateLimitBudget(limits)

    # ------------------------------------------------------------------
    # Public API — non-streaming
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
        estimated_tokens: int = EST_TOKENS_PER_REQUEST,
        preferred_model: str | None = None,
    ) -> tuple[str, ProviderResponse]:
        return await self._run_with_rotation(
            call_fn=self._call_generate,
            messages=messages,
            config=config,
            tools=tools,
            estimated_tokens=estimated_tokens,
            preferred_model=preferred_model,
        )

    # ------------------------------------------------------------------
    # Public API — streaming with fallback (v2, buffered)
    # ------------------------------------------------------------------

    async def stream_with_fallback(
        self,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None = None,
        estimated_tokens: int = EST_TOKENS_PER_REQUEST,
        preferred_model: str | None = None,
    ) -> AsyncIterator[ProviderStreamChunk]:
        last_exc: Exception | None = None
        budget_skipped_all: list[str] = []

        for rotation_attempt in range(STREAM_ROTATION_RETRIES + 1):
            if rotation_attempt > 0:
                delay = self._retry_delay * (2 ** (rotation_attempt - 1))
                logger.warning(
                    f"stream_with_fallback: rotation attempt {rotation_attempt + 1}/"
                    f"{STREAM_ROTATION_RETRIES + 1} — waiting {delay:.1f}s before retry"
                )
                await asyncio.sleep(delay)

            ordered = self._ordered(preferred_model)
            models_tried: dict[str, str] = {}
            budget_skipped: list[str] = []

            for model in ordered:
                budget = self._budgets.get(model)

                if budget and not budget.can_use(estimated_tokens):
                    budget_skipped.append(model)
                    logger.debug(f"stream_with_fallback: skip {model} (budget exhausted)")
                    continue

                if budget:
                    budget.record_request(estimated_tokens)

                buffered_chunks: list[ProviderStreamChunk] = []
                try:
                    stream = self._provider.generate_stream(
                        model=model,
                        messages=messages,
                        config=config,
                        tools=tools,
                    )
                    async for chunk in stream:
                        buffered_chunks.append(chunk)

                    self._advance_cursor_to(model)
                    logger.info(
                        f"stream_with_fallback: {model} OK "
                        f"({len(buffered_chunks)} chunks, "
                        f"rotation_attempt={rotation_attempt})"
                    )
                    for chunk in buffered_chunks:
                        yield chunk
                    return

                except Exception as error:
                    last_exc = error
                    err_str = str(error)[:200]

                    if is_fatal_error(error):
                        logger.error(f"stream_with_fallback: FATAL on {model} → {err_str}")
                        raise

                    if is_quota_error(error):
                        if budget:
                            budget.penalise()
                        models_tried[model] = f"QUOTA: {err_str}"
                        logger.warning(
                            f"stream_with_fallback: quota on {model}, penalised. "
                            f"buffered_chunks={len(buffered_chunks)} (discarded). "
                            f"{err_str}"
                        )
                        continue

                    models_tried[model] = err_str
                    logger.warning(
                        f"stream_with_fallback: recoverable error on {model} "
                        f"after {len(buffered_chunks)} buffered chunks (discarded). "
                        f"{err_str}"
                    )
                    continue

            budget_skipped_all.extend(budget_skipped)

            if models_tried:
                logger.warning(
                    f"stream_with_fallback: all models failed on rotation attempt "
                    f"{rotation_attempt + 1}/{STREAM_ROTATION_RETRIES + 1}. "
                    f"tried={list(models_tried.keys())} skipped={budget_skipped} "
                    f"errors={models_tried}"
                )
            else:
                logger.warning(
                    f"stream_with_fallback: all models budget-skipped on rotation "
                    f"{rotation_attempt + 1}, skipping further retries."
                )
                break

        if budget_skipped_all and last_exc is None:
            raise AllModelsExhaustedError(
                f"All models over rate-limit budget. "
                f"Skipped: {budget_skipped_all}. "
                f"Status: {self.budget_status()}"
            )

        if last_exc is None:
            raise AllModelsExhaustedError(
                "All models exhausted — no specific error recorded."
            )

        logger.error(
            f"stream_with_fallback: giving up after "
            f"{STREAM_ROTATION_RETRIES + 1} rotation attempts. "
            f"last_error={str(last_exc)[:300]}"
        )
        raise last_exc

    def record_stream_tokens(self, model: str, actual_tokens: int) -> None:
        budget = self._budgets.get(model)
        if budget:
            budget.update_tokens(actual_tokens)

    def budget_status(self) -> dict[str, dict]:
        return {m: b.status() for m, b in self._budgets.items()}

    # ------------------------------------------------------------------
    # Core rotation loop (non-streaming)
    # ------------------------------------------------------------------

    async def _run_with_rotation(
        self,
        call_fn,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None,
        estimated_tokens: int,
        preferred_model: str | None = None,
    ) -> tuple[str, ProviderResponse]:
        ordered = self._ordered(preferred_model)
        last_exc: Exception | None = None
        budget_skipped: list[str] = []

        for idx, model in enumerate(ordered):
            budget = self._budgets.get(model)

            if budget and not budget.can_use(estimated_tokens):
                budget_skipped.append(model)
                logger.info(f"ModelClient: skip {model} (budget) | {budget.status()}")
                continue

            if budget:
                budget.record_request(estimated_tokens)

            try:
                result = await self._call_with_retry(
                    call_fn, model, messages, config, tools
                )
                self._advance_cursor_to(model)

                if idx > 0 or budget_skipped:
                    logger.info(
                        f"ModelClient: model={model} succeeded "
                        f"(rotation_idx={idx}, budget_skipped={budget_skipped})"
                    )
                return model, result

            except Exception as exc:
                last_exc = exc

                if is_fatal_error(exc):
                    logger.error(f"ModelClient: fatal error on {model}, aborting. {str(exc)[:200]}")
                    raise

                if is_quota_error(exc):
                    if budget:
                        budget.penalise()
                    logger.warning(f"ModelClient: 429 on {model} — penalised. {str(exc)[:120]}")
                    continue

                if is_retryable_error(exc):
                    logger.warning(f"ModelClient: transient error exhausted on {model}. {str(exc)[:120]}")
                    continue

                logger.error(f"ModelClient: unknown error on {model}. {str(exc)[:200]}", exc_info=True)
                raise

        if budget_skipped and last_exc is None:
            raise AllModelsExhaustedError(
                f"All models over rate-limit budget. "
                f"Skipped: {budget_skipped}. "
                f"Status: {self.budget_status()}"
            )

        if last_exc is None:
            raise AllModelsExhaustedError("All models exhausted — no specific error recorded.")

        logger.error(
            f"ModelClient: all models exhausted | "
            f"budget_skipped={budget_skipped} | last_error={str(last_exc)[:300]}"
        )
        raise last_exc

    # ------------------------------------------------------------------
    # Per-model retry for transient errors
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self, call_fn, model: str,
        messages: list[Message],
        config: GenerationConfig,
        tools: list[ToolDefinition] | None,
    ) -> ProviderResponse:
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
    # Cursor helpers
    # ------------------------------------------------------------------

    def _model_order(self) -> list[str]:
        with self._lock:
            start = self._cursor
        n = len(self._models)
        return [self._models[(start + i) % n] for i in range(n)]

    def _ordered(self, preferred: str | None) -> list[str]:
        base = self._model_order()
        if not preferred or preferred not in self._models:
            return base
        return [preferred] + [m for m in base if m != preferred]

    def _advance_cursor_to(self, model: str) -> None:
        try:
            idx = self._models.index(model)
        except ValueError:
            return
        with self._lock:
            self._cursor = (idx + 1) % len(self._models)

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
