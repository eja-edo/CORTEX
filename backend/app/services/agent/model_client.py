"""
Shared Gemini API client with round-robin selection, per-model retry,
ordered fallback, and **proactive rate-limit tracking**.

Usage
-----
    from app.services.agent.model_client import ModelClient

    client = ModelClient()
    model_used, response = await client.generate(contents, config)

    # Streaming — yields (model_used, chunks_list) per turn
    async for chunk in client.stream_with_fallback(contents, config):
        ...

Design
------
Rate-limit budget tracking
    Each model has hard quota limits supplied by Google (free tier):

        Model                    RPM   TPM      RPD
        gemini-3.1-flash-lite     15   250 000   500
        gemma-4-31b-it            15   Unlim    1500
        gemma-4-26b-a4b-it        15   Unlim    1500

    RateLimitBudget tracks calls and tokens inside a sliding 60-second
    window (RPM / TPM) and a UTC-day window (RPD).  Before every call the
    client checks whether the target model has budget remaining.  If not,
    it skips directly to the next model in the rotation.

Round-robin + fallback
    The cursor advances after every *successful* call.

Per-model retry
    500 / 503 / INTERNAL / UNAVAILABLE -> retry same model RETRY_MAX_ATTEMPTS
    times with RETRY_DELAY_SECONDS delay.
    429 / quota -> penalise budget, skip to next model immediately.
    4xx fatal   -> abort the whole rotation.

stream_with_fallback changes (v2)
    - Buffers ALL chunks internally before yielding so a mid-stream error
      can still fall through to the next model cleanly.
    - ALL failures (0 chunks or N chunks buffered) fall through to the next
      model cleanly — the buffer is discarded, the caller never sees partial
      data, and no StreamPartialError is needed.
    - Fixes the `raise None` bug when all models are budget-skipped but
      last_exc is still None.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, AsyncIterator

from google import genai
from google.genai import types

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Model catalogue — free-tier limits from the Gemini dashboard
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelLimits:
    """Hard quota limits for one model (free-tier values)."""
    rpm: int            # requests per minute
    tpm: int | None     # tokens per minute  (None = unlimited)
    rpd: int            # requests per day


MODEL_LIMITS: dict[str, ModelLimits] = {
    "models/gemini-3.1-flash-lite": ModelLimits(rpm=15, tpm=250_000, rpd=500),
    "models/gemma-4-31b-it":        ModelLimits(rpm=15, tpm=None,    rpd=1_500),
    "models/gemma-4-26b-a4b-it":    ModelLimits(rpm=15, tpm=None,    rpd=1_500),
}

# Default model list (ordered by preference)
AVAILABLE_MODELS: list[str] = list(MODEL_LIMITS.keys())

# Models that reliably honor response_schema + application/json (exclude Gemma).
STRUCTURED_JSON_MODELS: list[str] = [
    "models/gemini-3.1-flash-lite",
]

# Conservative token estimate used *before* a call when real usage is unknown.
EST_TOKENS_PER_REQUEST: int = 1_500

# Retry knobs for transient (5xx) errors
RETRY_MAX_ATTEMPTS: int = 2
RETRY_DELAY_SECONDS: float = 2.0

# How many times to retry the *full model rotation* on stream failure
# before giving up entirely. Each attempt tries all available models.
STREAM_ROTATION_RETRIES: int = 2

# Safety margin: treat a model as exhausted when remaining budget < this fraction.
BUDGET_SAFETY_MARGIN: float = 0.05   # 5 %


# ---------------------------------------------------------------------------
# Low-level Gemini client (singleton)
# ---------------------------------------------------------------------------

_gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Error classifiers
# ---------------------------------------------------------------------------

# These status codes mean the *entire request* is broken regardless of model.
# Auth failures and missing resources cannot be fixed by switching models.
_TRULY_FATAL_CODES: frozenset[str] = frozenset({"401", "403", "404"})

# These 400 sub-statuses indicate a payload problem that no model can fix.
# Anything NOT in this set (e.g. INVALID_ARGUMENT) may just mean the model
# doesn't support a feature (tool calling, specific content type) — another
# model in the rotation might handle it fine.
_TRULY_FATAL_400_STATUSES: frozenset[str] = frozenset({
    "API_KEY_INVALID",
    "PERMISSION_DENIED",
    "UNAUTHENTICATED",
    "BILLING_DISABLED",
    "PROJECT_DISABLED",
})

# These 400 sub-statuses mean the *specific model* rejected the request
# (e.g. doesn't support function calling, content policy of that model)
# but another model in the rotation may succeed.
_MODEL_SKIP_400_STATUSES: frozenset[str] = frozenset({
    "INVALID_ARGUMENT",
    "FAILED_PRECONDITION",
    "UNIMPLEMENTED",
    "NOT_SUPPORTED",
})


def is_fatal_error(exc: Exception) -> bool:
    """
    True when NO model can ever succeed with this request.
    - 401 / 403 / 404 — auth / key / endpoint problems
    - 400 with auth/billing sub-status

    Does NOT include 400 INVALID_ARGUMENT because that often means
    "this specific model doesn't support function calling / this content
    type" — another model in the rotation may handle it fine.
    """
    s = str(exc)

    # 401 / 403 / 404 are always fatal
    if any(code in s for code in _TRULY_FATAL_CODES):
        return True

    # 400 — only fatal for specific sub-statuses
    if "400" in s:
        return any(status in s for status in _TRULY_FATAL_400_STATUSES)

    return False


def is_model_incompatible_error(exc: Exception) -> bool:
    """
    True when this *model* rejected the request but another model might
    succeed.  Covers:
    - 400 INVALID_ARGUMENT  — model doesn't support tool calling / content type
    - 400 FAILED_PRECONDITION / UNIMPLEMENTED — feature not available on model
    """
    s = str(exc)
    if "400" in s:
        return any(status in s for status in _MODEL_SKIP_400_STATUSES)
    return False


def is_quota_error(exc: Exception) -> bool:
    """Quota / rate-limit error — skip to next model immediately."""
    s = str(exc).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s


def is_retryable_error(exc: Exception) -> bool:
    """Transient server error — worth retrying the same model."""
    if is_quota_error(exc):
        return False
    s = str(exc)
    return "500" in s or "503" in s or "INTERNAL" in s or "UNAVAILABLE" in s


def _validate_stream_chunk(chunk: object) -> bool:
    """
    Validate that a stream chunk has expected structure.
    Returns True if valid, False if malformed.
    """
    if chunk is None:
        return False
    return (
        hasattr(chunk, 'text') or
        hasattr(chunk, 'candidates') or
        hasattr(chunk, 'function_calls')
    )


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class AllModelsExhaustedError(Exception):
    """All models are over their rate-limit budget or otherwise unavailable."""


# ---------------------------------------------------------------------------
# Per-model rate-limit budget tracker
# ---------------------------------------------------------------------------

class RateLimitBudget:
    """
    Sliding-window budget tracker for one model.  Thread-safe via a single lock.

    RPM / TPM  — true sliding 60-second window using a deque of timestamps.
    RPD        — UTC calendar day counter, resets at midnight.
    Penalty    — when a real 429 is received, the model is hard-blocked for
                 the remainder of the current minute (monotonic clock).
    """

    _WINDOW: float = 60.0   # seconds

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
                secs = self._blocked_until - now
                logger.debug(f"RateLimitBudget: hard-blocked for {secs:.1f}s more")
                return False

            self._evict(now)
            self._reset_rpd_if_needed(today)
            lim = self._limits
            margin = 1.0 - BUDGET_SAFETY_MARGIN

            if len(self._rpm_window) >= lim.rpm * margin:
                logger.debug(f"RateLimitBudget: RPM near limit {len(self._rpm_window)}/{lim.rpm}")
                return False

            if lim.tpm is not None:
                used_tpm = sum(t for _, t in self._tpm_window)
                if used_tpm + estimated_tokens >= lim.tpm * margin:
                    logger.debug(f"RateLimitBudget: TPM near limit {used_tpm}/{lim.tpm}")
                    return False

            if self._rpd_count >= lim.rpd * margin:
                logger.debug(f"RateLimitBudget: RPD near limit {self._rpd_count}/{lim.rpd}")
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
            logger.warning(f"RateLimitBudget: penalised — blocked for {self._WINDOW:.0f}s")

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
    Thread-safe Gemini API caller with:
      - Proactive RPM / TPM / RPD budget tracking per model
      - Round-robin cursor for even load distribution
      - Per-model retry for transient 5xx errors
      - Ordered fallback across all models
      - stream_with_fallback: buffers chunks, retries on failure, safe error surface
    """

    def __init__(
        self,
        models: list[str] | None = None,
        retry_attempts: int = RETRY_MAX_ATTEMPTS,
        retry_delay: float = RETRY_DELAY_SECONDS,
    ) -> None:
        self._models: list[str] = models or AVAILABLE_MODELS
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay

        self._cursor: int = 0
        self._lock = threading.Lock()

        _default_limits = ModelLimits(rpm=15, tpm=None, rpd=1_500)
        self._budgets: dict[str, RateLimitBudget] = {
            m: RateLimitBudget(MODEL_LIMITS.get(m, _default_limits))
            for m in self._models
        }

    # ------------------------------------------------------------------
    # Public API — non-streaming
    # ------------------------------------------------------------------

    async def generate(
        self,
        contents,
        config: types.GenerateContentConfig,
        estimated_tokens: int = EST_TOKENS_PER_REQUEST,
    ) -> tuple[str, object]:
        """
        Non-streaming generate_content with rate-limit awareness.
        Returns (model_name_used, response).
        Raises AllModelsExhaustedError if all models are budget-blocked.
        """
        return await self._run_with_rotation(
            call_fn=self._call_generate,
            contents=contents,
            config=config,
            estimated_tokens=estimated_tokens,
        )

    async def generate_stream(
        self,
        contents,
        config: types.GenerateContentConfig,
        estimated_tokens: int = EST_TOKENS_PER_REQUEST,
    ) -> tuple[str, object]:
        """
        Returns (model_name_used, stream_iterator) — caller iterates the stream.
        NOTE: Prefer stream_with_fallback for production use.
        """
        return await self._run_with_rotation(
            call_fn=self._call_generate_stream,
            contents=contents,
            config=config,
            estimated_tokens=estimated_tokens,
        )

    def record_stream_tokens(self, model: str, actual_tokens: int) -> None:
        budget = self._budgets.get(model)
        if budget:
            budget.update_tokens(actual_tokens)

    # ------------------------------------------------------------------
    # Public API — streaming with fallback (v2, buffered)
    # ------------------------------------------------------------------

    async def stream_with_fallback(
        self,
        contents,
        config: types.GenerateContentConfig,
        estimated_tokens: int = EST_TOKENS_PER_REQUEST,
    ) -> AsyncIterator[object]:
        """
        Streaming generator with automatic retry + model fallback.

        Strategy
        --------
        Chunks are buffered internally before being yielded to the caller.
        This means ANY failure — whether at chunk 0 or chunk N — can always
        fall through to the next model cleanly because nothing has been sent
        to the caller yet.

        Decision tree per model per attempt:
          Fatal 4xx         → raise immediately (no model can fix this)
          429 / quota       → penalise budget, continue to next model
          500/503 (5xx)     → discard buffer, continue to next model
                              (regardless of how many chunks were buffered)
          Format/ValueError → discard buffer, continue to next model
          Success           → yield all buffered chunks, advance cursor, return

        After the inner model loop, if every model failed, retry the full
        rotation up to STREAM_ROTATION_RETRIES times with exponential backoff.
        This handles brief windows where all models are simultaneously 5xx.

        Raises
        ------
        AllModelsExhaustedError  — every model is budget-blocked or exhausted.
        Exception                — fatal 4xx from any model.
        """
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

            ordered = self._model_order()
            models_tried: dict[str, str] = {}
            budget_skipped: list[str] = []

            for model in ordered:
                budget = self._budgets[model]

                # Proactive budget check
                if not budget.can_use(estimated_tokens):
                    budget_skipped.append(model)
                    logger.debug(f"stream_with_fallback: skip {model} (budget exhausted)")
                    continue

                budget.record_request(estimated_tokens)

                # ── Buffer the entire stream for this model ───────────
                # Because we buffer before yielding, ANY mid-stream error
                # is recoverable — we simply discard the buffer and try
                # the next model. The caller never sees partial data.
                buffered_chunks: list = []
                try:
                    stream_iter = _gemini_client.models.generate_content_stream(
                        model=model,
                        contents=contents,
                        config=config,
                    )
                    logger.debug(
                        f"stream_with_fallback: started stream from {model} "
                        f"(rotation_attempt={rotation_attempt})"
                    )

                    for chunk in stream_iter:
                        if not _validate_stream_chunk(chunk):
                            raise ValueError(
                                f"Invalid stream chunk type={type(chunk).__name__} "
                                f"from model={model}"
                            )
                        buffered_chunks.append(chunk)
                        _try_update_tokens(budget, chunk)

                    # ── Full stream collected successfully ────────────
                    self._advance_cursor_to(model)
                    logger.info(
                        f"✅ stream_with_fallback: {model} OK "
                        f"({len(buffered_chunks)} chunks, "
                        f"rotation_attempt={rotation_attempt})"
                    )
                    for chunk in buffered_chunks:
                        yield chunk
                    return  # ← clean exit

                except Exception as error:
                    last_exc = error
                    err_str = str(error)[:200]

                    # ── Fatal: no model can fix this ─────────────────
                    if is_fatal_error(error):
                        logger.error(
                            f"stream_with_fallback: FATAL on {model} → {err_str}"
                        )
                        raise

                    # ── Model-incompatible 400: skip to next model ────
                    # e.g. Gemma returning 400 INVALID_ARGUMENT because it
                    # doesn't support function calling. Another model may work.
                    if is_model_incompatible_error(error):
                        models_tried[model] = f"MODEL_INCOMPATIBLE: {err_str}"
                        logger.warning(
                            f"stream_with_fallback: model-incompatible error on {model} "
                            f"(400 sub-status). Trying next model... {err_str}"
                        )
                        continue

                    # ── Quota / 429: penalise and try next model ──────
                    if is_quota_error(error):
                        budget.penalise()
                        models_tried[model] = f"QUOTA: {err_str}"
                        logger.warning(
                            f"stream_with_fallback: quota on {model}, penalised. "
                            f"buffered_chunks={len(buffered_chunks)} (discarded). "
                            f"Trying next model... {err_str}"
                        )
                        continue

                    # ── 5xx / format error / any other recoverable ────
                    # Discard buffer and fall through to next model.
                    models_tried[model] = err_str
                    logger.warning(
                        f"stream_with_fallback: recoverable error on {model} "
                        f"after {len(buffered_chunks)} buffered chunks (discarded). "
                        f"Trying next model... {err_str}"
                    )
                    continue

            # ── End of inner model loop ───────────────────────────────
            budget_skipped_all.extend(budget_skipped)

            if models_tried:
                # At least one model was attempted — worth retrying rotation
                logger.warning(
                    f"stream_with_fallback: all models failed on rotation attempt "
                    f"{rotation_attempt + 1}/{STREAM_ROTATION_RETRIES + 1}. "
                    f"tried={list(models_tried.keys())} skipped={budget_skipped} "
                    f"errors={models_tried}"
                )
                # Continue outer loop → sleep + retry rotation
            else:
                # Every model was budget-skipped — no point retrying immediately
                logger.warning(
                    f"stream_with_fallback: all models budget-skipped on rotation "
                    f"{rotation_attempt + 1}, skipping further retries."
                )
                break

        # ── All rotation attempts exhausted ──────────────────────────
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

    def budget_status(self) -> dict[str, dict]:
        return {m: b.status() for m, b in self._budgets.items()}

    # ------------------------------------------------------------------
    # Core rotation loop (non-streaming)
    # ------------------------------------------------------------------

    async def _run_with_rotation(
        self,
        call_fn,
        contents,
        config,
        estimated_tokens: int,
    ) -> tuple[str, object]:
        ordered = self._model_order()
        last_exc: Exception | None = None
        budget_skipped: list[str] = []

        for idx, model in enumerate(ordered):
            budget = self._budgets[model]

            if not budget.can_use(estimated_tokens):
                budget_skipped.append(model)
                logger.info(f"ModelClient: skip {model} (budget) | {budget.status()}")
                continue

            budget.record_request(estimated_tokens)

            try:
                result = await self._call_with_retry(call_fn, model, contents, config)
                _try_update_tokens(budget, result)
                self._advance_cursor_to(model)

                if idx > 0 or budget_skipped:
                    logger.info(
                        f"✅ ModelClient: model={model} succeeded "
                        f"(rotation_idx={idx}, budget_skipped={budget_skipped})"
                    )
                return model, result

            except Exception as exc:
                last_exc = exc

                if is_fatal_error(exc):
                    logger.error(f"ModelClient: fatal error on {model}, aborting. {str(exc)[:200]}")
                    raise

                if is_model_incompatible_error(exc):
                    logger.warning(
                        f"ModelClient: model-incompatible 400 on {model}, trying next. {str(exc)[:120]}"
                    )
                    continue

                if is_quota_error(exc):
                    budget.penalise()
                    logger.warning(f"ModelClient: 429 on {model} — penalised 60s. {str(exc)[:120]}")
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

    async def _call_with_retry(self, call_fn, model: str, contents, config) -> object:
        last_exc: Exception | None = None

        for attempt in range(1, self._retry_attempts + 1):
            try:
                return await call_fn(model, contents, config)
            except Exception as exc:
                last_exc = exc

                if is_fatal_error(exc) or is_quota_error(exc) or is_model_incompatible_error(exc):
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
                    else:
                        logger.error(
                            f"ModelClient: retryable error on {model} "
                            f"after {self._retry_attempts} attempts. {str(exc)[:200]}"
                        )
                        raise

                logger.error(f"ModelClient: unknown error on {model}: {str(exc)[:200]}", exc_info=True)
                raise

        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Cursor helpers
    # ------------------------------------------------------------------

    def _model_order(self) -> list[str]:
        with self._lock:
            start = self._cursor
        n = len(self._models)
        return [self._models[(start + i) % n] for i in range(n)]

    def _advance_cursor_to(self, model: str) -> None:
        try:
            idx = self._models.index(model)
        except ValueError:
            return
        with self._lock:
            self._cursor = (idx + 1) % len(self._models)

    # ------------------------------------------------------------------
    # Low-level SDK wrappers
    # ------------------------------------------------------------------

    async def _call_generate(self, model: str, contents, config) -> object:
        return _gemini_client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

    async def _call_generate_stream(self, model: str, contents, config) -> object:
        return _gemini_client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        )


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _try_update_tokens(budget: RateLimitBudget, result: object) -> None:
    """Update budget with real token count from response metadata if available."""
    try:
        meta = getattr(result, "usage_metadata", None)
        if meta is None:
            return
        total = getattr(meta, "total_token_count", None)
        if total is not None:
            budget.update_tokens(int(total))
    except Exception:
        pass