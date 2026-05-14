"""
Shared Gemini API client with round-robin selection, per-model retry,
ordered fallback, and **proactive rate-limit tracking**.

Usage
-----
    from app.services.agent.model_client import ModelClient

    client = ModelClient()
    model_used, response = await client.generate(contents, config)
    model_used, response = await client.generate_stream(contents, config)

Design
------
Rate-limit budget tracking  (the main addition over the previous version)
    Each model has hard quota limits supplied by Google (free tier):

        Model                    RPM   TPM      RPD
        gemini-3.1-flash-lite     15   250 000   500
        gemma-4-31b-it            15   Unlim    1500
        gemma-4-26b-a4b-it        15   Unlim    1500

    RateLimitBudget tracks calls and tokens inside a sliding 60-second
    window (RPM / TPM) and a UTC-day window (RPD).  Before every call the
    client checks whether the target model has budget remaining.  If not,
    it skips directly to the next model in the rotation — no wasted network
    round-trip, no 429 to parse.

    Token counts come from response.usage_metadata when available.  For
    requests where we don't know upfront how many tokens will be consumed,
    we record an *estimated* cost (EST_TOKENS_PER_REQUEST) before the call
    and replace it with the real number afterwards.

    On a real 429 / RESOURCE_EXHAUSTED the budget for the offending model is
    penalised for 60 s so subsequent requests don't keep retrying it.

Round-robin + fallback
    The cursor advances after every *successful* call, spreading load evenly.
    On error the cursor stays put and the next model in the ordered list is
    tried.

Per-model retry
    500 / 503 / INTERNAL / UNAVAILABLE -> retry same model RETRY_MAX_ATTEMPTS
    times with RETRY_DELAY_SECONDS delay.
    429 / quota -> penalise budget, skip to next model immediately.
    4xx fatal   -> abort the whole rotation.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque

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


# Free-tier limits as provided:
#   gemini-3.1-flash-lite  RPM=15  TPM=250k   RPD=500
#   gemma-4-31b-it         RPM=15  TPM=unlim  RPD=1500
#   gemma-4-26b-a4b-it     RPM=15  TPM=unlim  RPD=1500
MODEL_LIMITS: dict[str, ModelLimits] = {
    "models/gemini-3.1-flash-lite": ModelLimits(rpm=15, tpm=250_000, rpd=500),
    "models/gemma-4-31b-it":        ModelLimits(rpm=15, tpm=None,    rpd=1_500),
    "models/gemma-4-26b-a4b-it":    ModelLimits(rpm=15, tpm=None,    rpd=1_500),
}

# Default model list (ordered by preference)
AVAILABLE_MODELS: list[str] = list(MODEL_LIMITS.keys())

# Conservative token estimate used *before* a call when real usage is unknown.
# Replaced with actual usage_metadata afterwards.
EST_TOKENS_PER_REQUEST: int = 1_500

# Retry knobs for transient (5xx) errors
RETRY_MAX_ATTEMPTS: int = 2
RETRY_DELAY_SECONDS: float = 2.0

# Safety margin: treat a model as exhausted when remaining budget < this
# fraction.  Avoids racing right up to the hard wall.
BUDGET_SAFETY_MARGIN: float = 0.05   # 5 %


# ---------------------------------------------------------------------------
# Low-level Gemini client (singleton)
# ---------------------------------------------------------------------------

_gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Error classifiers
# ---------------------------------------------------------------------------

_FATAL_CODES: frozenset[str] = frozenset({"400", "401", "403", "404"})


def is_fatal_error(exc: Exception) -> bool:
    """Client-side error — retrying or switching models will not help."""
    s = str(exc)
    return any(code in s for code in _FATAL_CODES)


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
    Returns True if valid, False if malformed (should trigger retry).
    """
    if chunk is None:
        return False
    
    # Check for basic attributes that chunks should have
    has_text_or_parts = (
        hasattr(chunk, 'text') or
        hasattr(chunk, 'candidates') or
        hasattr(chunk, 'function_calls')
    )
    
    return has_text_or_parts


# ---------------------------------------------------------------------------
# Per-model rate-limit budget tracker
# ---------------------------------------------------------------------------

class RateLimitBudget:
    """
    Sliding-window budget tracker for one model.

    Thread-safe via a single lock.

    RPM / TPM  — true sliding 60-second window using a deque of timestamps.
                 Old entries are evicted on every read/write so the window
                 always reflects the actual last 60 seconds, not a fixed bucket.

    RPD        — UTC calendar day counter, resets at midnight.

    Penalty    — when a real 429 is received, the model is hard-blocked for
                 the remainder of the current minute (monotonic clock).
    """

    _WINDOW: float = 60.0   # seconds

    def __init__(self, limits: ModelLimits) -> None:
        self._limits = limits
        self._lock = threading.Lock()

        # RPM: deque of monotonic timestamps (one entry per request)
        self._rpm_window: Deque[float] = deque()

        # TPM: deque of (monotonic_ts, token_count) pairs
        self._tpm_window: Deque[tuple[float, int]] = deque()

        # RPD: (utc_date_str, count)
        self._rpd_date: str = ""
        self._rpd_count: int = 0

        # Penalty timestamp
        self._blocked_until: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def can_use(self, estimated_tokens: int = EST_TOKENS_PER_REQUEST) -> bool:
        """
        Return True if the model has sufficient budget for one more request.
        Checks active penalty, RPM, TPM (if capped), and RPD.
        """
        with self._lock:
            now = time.monotonic()
            today = _utc_date()

            # Hard block from a recent 429
            if now < self._blocked_until:
                secs = self._blocked_until - now
                logger.debug(f"RateLimitBudget: hard-blocked for {secs:.1f}s more")
                return False

            self._evict(now)
            self._reset_rpd_if_needed(today)
            lim = self._limits
            margin = 1.0 - BUDGET_SAFETY_MARGIN

            # RPM check
            if len(self._rpm_window) >= lim.rpm * margin:
                logger.debug(
                    f"RateLimitBudget: RPM near limit "
                    f"{len(self._rpm_window)}/{lim.rpm}"
                )
                return False

            # TPM check (only for models with a cap)
            if lim.tpm is not None:
                used_tpm = sum(t for _, t in self._tpm_window)
                if used_tpm + estimated_tokens >= lim.tpm * margin:
                    logger.debug(
                        f"RateLimitBudget: TPM near limit "
                        f"{used_tpm}/{lim.tpm} (+{estimated_tokens} est.)"
                    )
                    return False

            # RPD check
            if self._rpd_count >= lim.rpd * margin:
                logger.debug(
                    f"RateLimitBudget: RPD near limit "
                    f"{self._rpd_count}/{lim.rpd}"
                )
                return False

            return True

    def record_request(self, estimated_tokens: int = EST_TOKENS_PER_REQUEST) -> None:
        """
        Register a request that is about to be sent.
        Call this immediately *before* the API call.
        """
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
        """
        Replace the most-recent TPM estimate with the real token count.
        Call this after a successful response using usage_metadata.
        """
        if self._limits.tpm is None:
            return
        with self._lock:
            if not self._tpm_window:
                return
            ts, _ = self._tpm_window[-1]
            self._tpm_window[-1] = (ts, actual_tokens)

    def penalise(self) -> None:
        """
        Hard-block this model for 60 s after receiving a real 429.
        Also bumps RPM window to reflect the failed attempt.
        """
        with self._lock:
            self._blocked_until = time.monotonic() + self._WINDOW
            logger.warning(
                f"RateLimitBudget: penalised — blocked for {self._WINDOW:.0f}s"
            )

    def status(self) -> dict:
        """Snapshot of current usage — useful for logging / metrics."""
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

    # ------------------------------------------------------------------
    # Internal helpers  (must be called with self._lock held)
    # ------------------------------------------------------------------

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
# Custom exception
# ---------------------------------------------------------------------------

class AllModelsExhaustedError(Exception):
    """All models are over their rate-limit budget or otherwise unavailable."""


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

    Each instance has an independent cursor and budget trackers so agent and
    summarizer services don't interfere with each other's rotation.
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

        # Round-robin cursor (protected by lock)
        self._cursor: int = 0
        self._lock = threading.Lock()

        # One budget tracker per model, using known limits or a safe default
        _default_limits = ModelLimits(rpm=15, tpm=None, rpd=1_500)
        self._budgets: dict[str, RateLimitBudget] = {
            m: RateLimitBudget(MODEL_LIMITS.get(m, _default_limits))
            for m in self._models
        }

    # ------------------------------------------------------------------
    # Public API
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
        Raises the last API exception if all models fail for other reasons.
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
        Streaming generate_content_stream with rate-limit awareness.

        Returns (model_name_used, stream_iterator).
        Token usage is NOT updated automatically for streaming calls because
        usage_metadata arrives at the end of the stream which the caller
        controls.  Call record_stream_tokens() after iteration.
        """
        return await self._run_with_rotation(
            call_fn=self._call_generate_stream,
            contents=contents,
            config=config,
            estimated_tokens=estimated_tokens,
        )

    def record_stream_tokens(self, model: str, actual_tokens: int) -> None:
        """
        Update the TPM budget with real token usage after streaming completes.
        Call this when usage_metadata becomes available at end of stream.
        """
        budget = self._budgets.get(model)
        if budget:
            budget.update_tokens(actual_tokens)

    async def stream_with_fallback(
        self,
        contents,
        config: types.GenerateContentConfig,
        estimated_tokens: int = EST_TOKENS_PER_REQUEST,
    ):
        """
        Streaming generator with automatic fallback on any failure during iteration.

        Yields chunks from the stream. If ANY error occurs (5xx, format error, etc.),
        automatically retries with the next model in the rotation.

        Yields:
            Chunks from the stream iterator.

        Raises:
            AllModelsExhaustedError: All models are rate-limit blocked.
            Last Exception: If all models fail with fatal errors (4xx).
        """
        ordered = self._model_order()
        last_exc: Exception | None = None
        models_tried: dict[str, str] = {}  # model -> error_msg

        for model in ordered:
            budget = self._budgets[model]

            # Proactive budget check
            if not budget.can_use(estimated_tokens):
                logger.debug(f"stream_with_fallback: skip {model} (budget exhausted)")
                continue

            budget.record_request(estimated_tokens)

            stream_success = False
            try:
                # Call low-level SDK directly to get stream
                stream_iter = _gemini_client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=config,
                )
                
                logger.debug(f"stream_with_fallback: got iterator from {model}")

                # Iterate and yield chunks
                chunk_count = 0
                for chunk in stream_iter:
                    # Validate chunk structure before yielding
                    if not _validate_stream_chunk(chunk):
                        raise ValueError(
                            f"Stream chunk has invalid structure: {type(chunk).__name__}. "
                            f"Expected text, candidates, or function_calls attributes."
                        )
                    
                    chunk_count += 1
                    yield chunk
                    # Try to update tokens if available early
                    _try_update_tokens(budget, chunk)

                # Successfully completed stream
                stream_success = True
                self._advance_cursor_to(model)
                logger.info(
                    f"✅ stream_with_fallback: {model} succeeded "
                    f"({chunk_count} chunks) after {len(models_tried)} prior failures"
                )
                return

            except Exception as error:
                err_str = str(error)[:150]
                last_exc = error
                
                # Check for fatal errors that should abort immediately
                if is_fatal_error(error):
                    logger.error(
                        f"stream_with_fallback: FATAL error on {model}, aborting. {err_str}"
                    )
                    raise
                
                # Check for quota errors - penalise and continue
                if is_quota_error(error):
                    budget.penalise()
                    models_tried[model] = f"QUOTA: {err_str}"
                    logger.warning(
                        f"stream_with_fallback: quota error on {model}, "
                        f"penalised. Trying next model... {err_str}"
                    )
                    continue
                
                # Any other error during stream: format error, 5xx, etc.
                if not stream_success:
                    models_tried[model] = err_str
                    logger.warning(
                        f"stream_with_fallback: error on {model} "
                        f"(stream_success=False), trying next model... {err_str}"
                    )
                    continue
                
                # Should not reach here, but if stream_success=True and error occurs, re-raise
                logger.error(
                    f"stream_with_fallback: unexpected error after success on {model}. {err_str}",
                    exc_info=True,
                )
                raise

        # All models exhausted
        if models_tried and last_exc is None:
            raise AllModelsExhaustedError(
                f"All {len(models_tried)} models failed. "
                f"Failures: {models_tried}"
            )

        logger.error(
            f"stream_with_fallback: all models exhausted. "
            f"Tried: {models_tried} | Last error: {str(last_exc)[:200]}"
        )
        raise last_exc  # type: ignore[misc]

    def budget_status(self) -> dict[str, dict]:
        """Snapshot of all models' current budget — for logging / health checks."""
        return {m: b.status() for m, b in self._budgets.items()}

    # ------------------------------------------------------------------
    # Core rotation loop
    # ------------------------------------------------------------------

    async def _run_with_rotation(
        self,
        call_fn,
        contents,
        config,
        estimated_tokens: int,
    ) -> tuple[str, object]:
        """
        Iterate through models in round-robin order.

        Per model:
          1. Proactive budget check — skip if RPM / TPM / RPD exhausted.
          2. Record request in budget window (optimistic).
          3. Call API with per-model retry for 5xx.
          4. Success  -> update real tokens, advance cursor, return.
          5. 429      -> penalise budget, continue to next model.
          6. 5xx      -> retries exhausted, continue to next model.
          7. 4xx      -> abort rotation (no other model will fix it).
        """
        ordered = self._model_order()
        last_exc: Exception | None = None
        budget_skipped: list[str] = []

        for idx, model in enumerate(ordered):
            budget = self._budgets[model]

            # ── 1. Proactive budget gate ──────────────────────────────
            if not budget.can_use(estimated_tokens):
                budget_skipped.append(model)
                logger.info(
                    f"ModelClient: skip {model} (budget) "
                    f"| {budget.status()}"
                )
                continue

            # ── 2. Optimistic budget record ───────────────────────────
            budget.record_request(estimated_tokens)

            try:
                result = await self._call_with_retry(
                    call_fn, model, contents, config
                )

                # ── 4. Success ────────────────────────────────────────
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

                # ── 7. Fatal ──────────────────────────────────────────
                if is_fatal_error(exc):
                    logger.error(
                        f"ModelClient: fatal error on {model}, aborting. "
                        f"{str(exc)[:200]}"
                    )
                    raise

                # ── 5. Rate-limited ───────────────────────────────────
                if is_quota_error(exc):
                    budget.penalise()
                    logger.warning(
                        f"ModelClient: 429 on {model} — penalised 60s, "
                        f"trying next. {str(exc)[:120]}"
                    )
                    continue

                # ── 6. Transient ──────────────────────────────────────
                if is_retryable_error(exc):
                    logger.warning(
                        f"ModelClient: transient error exhausted on {model}, "
                        f"trying next. {str(exc)[:120]}"
                    )
                    continue

                # Unknown — don't try other models
                logger.error(
                    f"ModelClient: unknown error on {model}. {str(exc)[:200]}",
                    exc_info=True,
                )
                raise

        # All models exhausted
        if budget_skipped and last_exc is None:
            # Every model was proactively blocked by budget — surface clearly
            raise AllModelsExhaustedError(
                f"All models over rate-limit budget. "
                f"Skipped: {budget_skipped}. "
                f"Status: {self.budget_status()}"
            )

        logger.error(
            f"ModelClient: all models exhausted | "
            f"budget_skipped={budget_skipped} | "
            f"last_error={str(last_exc)[:300]}"
        )
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Per-model retry for transient errors
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self, call_fn, model: str, contents, config
    ) -> object:
        last_exc: Exception | None = None

        for attempt in range(1, self._retry_attempts + 1):
            try:
                return await call_fn(model, contents, config)

            except Exception as exc:
                last_exc = exc

                # Let the rotation loop handle these
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
                    else:
                        logger.error(
                            f"ModelClient: retryable error on {model} "
                            f"after {self._retry_attempts} attempts. {str(exc)[:200]}"
                        )
                        raise

                # Unknown — don't retry
                logger.error(
                    f"ModelClient: unknown error on {model}: {str(exc)[:200]}",
                    exc_info=True,
                )
                raise

        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Cursor helpers
    # ------------------------------------------------------------------

    def _model_order(self) -> list[str]:
        """Return all models starting from the current cursor (round-robin)."""
        with self._lock:
            start = self._cursor
        n = len(self._models)
        return [self._models[(start + i) % n] for i in range(n)]

    def _advance_cursor_to(self, model: str) -> None:
        """Move cursor to the slot *after* model so the next call starts there."""
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
# Module-level helper (used by RateLimitBudget, extracted to avoid closure)
# ---------------------------------------------------------------------------

def _try_update_tokens(budget: RateLimitBudget, result: object) -> None:
    """
    If *result* has usage_metadata, update the budget with the real token count.
    Silently skips on any error — estimation is acceptable as a fallback.
    """
    try:
        meta = getattr(result, "usage_metadata", None)
        if meta is None:
            return
        total = getattr(meta, "total_token_count", None)
        if total is not None:
            budget.update_tokens(int(total))
    except Exception:
        pass