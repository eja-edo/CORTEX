import asyncio
import logging
from collections import defaultdict
from uuid import UUID

from cortex_leads.core.context import RunContext
from cortex_leads.llm.providers import Provider, classify_error
from cortex_leads.llm.types import (
    LLMError,
    LLMFatalError,
    LLMQuotaError,
    LLMResult,
    LLMTimeoutError,
    LLMTransientError,
    ToolCall,
)

__all__ = ["LLMGateway", "LLMResult", "ToolCall"]

logger = logging.getLogger(__name__)


class LLMGateway:
    """The single door to the LLM (DESIGN A4): global + per-tenant concurrency, timeout,
    short retry for transient errors. No model fallback/rotation (removed on purpose in
    the old model_client); quota and fatal errors are never retried."""

    def __init__(
        self,
        provider: Provider,
        *,
        global_concurrency: int = 4,
        per_tenant_concurrency: int = 2,
        max_attempts: int = 3,
        retry_delay_s: float = 0.5,
    ) -> None:
        self._provider = provider
        self._global = asyncio.Semaphore(global_concurrency)
        self._per_tenant_n = per_tenant_concurrency
        self._tenants: dict[UUID, asyncio.Semaphore] = {}
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay_s
        self.usage: dict[UUID, tuple[int, int]] = defaultdict(lambda: (0, 0))  # tenant -> (in, out)

    def _tenant_sem(self, tenant_id: UUID) -> asyncio.Semaphore:
        sem = self._tenants.get(tenant_id)
        if sem is None:
            sem = self._tenants[tenant_id] = asyncio.Semaphore(self._per_tenant_n)
        return sem

    async def complete(
        self,
        ctx: RunContext,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        timeout_s: float = 30,
    ) -> LLMResult:
        tenant_sem = self._tenant_sem(ctx.tenant_id)
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            # Slots are held per attempt, not across the backoff sleep. Tenant first, so
            # one noisy tenant queues on its own semaphore, not on the global one.
            async with tenant_sem, self._global:
                try:
                    result = await asyncio.wait_for(
                        self._provider.complete(messages, tools=tools, model=model), timeout_s
                    )
                except TimeoutError:
                    last = LLMTimeoutError(f"LLM call exceeded {timeout_s}s")
                except Exception as exc:  # noqa: BLE001 - classified, then re-raised or retried
                    last = classify_error(exc)
                else:
                    t_in, t_out = self.usage[ctx.tenant_id]
                    self.usage[ctx.tenant_id] = (t_in + result.tokens_in, t_out + result.tokens_out)
                    return result
            if isinstance(last, (LLMFatalError, LLMQuotaError)) or not isinstance(
                last, LLMTransientError
            ):
                raise last
            if attempt < self._max_attempts:
                logger.warning("llm transient error %d/%d: %s", attempt, self._max_attempts, last)
                await asyncio.sleep(self._retry_delay * attempt)
        assert isinstance(last, LLMError)
        raise last
