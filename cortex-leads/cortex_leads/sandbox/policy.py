"""Sandbox rules: when one is mandatory, kill switch, hard budgets (DESIGN §5.6)."""
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.envelope import BlockedCode, Violation
from cortex_leads.core.timefmt import day_start, tenant_tz
from cortex_leads.db.models import Draft, Sandbox, TriggerRun

# Any one of these forces the config into a sandbox.
SANDBOX_TRIGGERS = ("touches_customer_data", "untrusted_input", "customer_channel", "external_mcp")


def requires_sandbox(cfg: dict[str, Any]) -> bool:
    return any(bool(cfg.get(k)) for k in SANDBOX_TRIGGERS)


def is_paused(sandbox: Sandbox) -> bool:
    return sandbox.status == "paused"


async def check_budget(session: AsyncSession, sandbox: Sandbox,
                       kind: Literal["runs", "drafts", "tokens"], now: datetime) -> Violation | None:
    """None = allowed. Counts since the business's local midnight (DESIGN §5.13); budgets live in sandbox.budget."""
    if is_paused(sandbox):
        return Violation(code=BlockedCode.PAUSED, detail=f"sandbox {sandbox.name} is paused")
    day = day_start(now, await tenant_tz(session, sandbox.tenant_id))
    key, used = {
        "runs": ("runs_per_day", select(func.count()).select_from(TriggerRun).where(
            TriggerRun.sandbox_id == sandbox.id, TriggerRun.started_at >= day)),
        "drafts": ("drafts_per_staff_per_day", select(func.count()).select_from(Draft).where(
            Draft.sandbox_id == sandbox.id, Draft.created_at >= day)),
        "tokens": ("tokens_per_day", select(
            func.coalesce(func.sum(TriggerRun.tokens_in + TriggerRun.tokens_out), 0)).where(
            TriggerRun.sandbox_id == sandbox.id, TriggerRun.started_at >= day)),
    }[kind]
    limit = sandbox.budget.get(key)
    if limit is None:  # no number configured -> deny: a missing cap must not mean unlimited
        return Violation(code=BlockedCode.BUDGET, detail=f"{key} not configured")
    if (await session.execute(used)).scalar_one() >= limit:
        return Violation(code=BlockedCode.BUDGET, detail=f"{key} exhausted ({limit})")
    return None
