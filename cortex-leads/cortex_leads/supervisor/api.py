"""Supervisor read-model (DESIGN §5.6): metadata only, through supervisor_run_view as cl_supervisor
(column grants, so a text column cannot be read even by mistake). Groups with n < 5 are hidden."""
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from cortex_leads.core.timefmt import wire
from cortex_leads.db.session import supervisor_session
from cortex_leads.review.auth import Caller, require

router = APIRouter()
SUPERVISOR = require("supervisor")
MIN_N = 5
_DIMS = {"status": "status", "act": "act", "reason_code": "reason_code",
         "staff_outcome": "staff_outcome"}


def _shown(n: int) -> int | None:
    return n if n >= MIN_N else None


@router.get("/summary")
async def summary(caller: Caller = SUPERVISOR, since: datetime | None = None
                  ) -> dict[str, Any]:
    since = since or datetime.now(UTC) - timedelta(days=7)
    since = since if since.tzinfo else since.replace(tzinfo=UTC)
    out: dict[str, Any] = {"since": wire(since)}
    async with supervisor_session(caller.tenant_id) as s:
        p = {"since": since}
        total = (await s.execute(text(
            "select count(*) from supervisor_run_view where started_at >= :since"), p)).scalar_one()
        for name, col in _DIMS.items():
            rows = (await s.execute(text(
                f"select {col}, count(*) from supervisor_run_view where started_at >= :since "
                f"and {col} is not null group by 1"), p)).all()
            out[name] = {k: _shown(n) for k, n in rows}
            if name == "staff_outcome":
                outcomes = dict(rows)
        rows = (await s.execute(text(
            "select c, count(*) from supervisor_run_view, unnest(blocked_codes) c "
            "where started_at >= :since group by 1"), p)).all()
        out["blocked_codes"] = {k: _shown(n) for k, n in rows}
        none_n = (await s.execute(text(
            "select count(*) from supervisor_run_view where started_at >= :since and act = 'none'"),
            p)).scalar_one()
        out["outbox"] = {}  # counts only, from supervisor_outbox_view (no text, no staff ref)
        for name in ("status", "reason", "actor_kind"):
            rows = (await s.execute(text(
                f"select {name}, count(*) from supervisor_outbox_view where created_at >= :since "
                f"and {name} is not null group by 1"), p)).all()
            out["outbox"][name] = {k: _shown(n) for k, n in rows}
        rows = (await s.execute(text(  # R39: how many leads need a phone call; counts only
            "select route, count(*) from supervisor_draft_view where created_at >= :since "
            "group by 1"), p)).all()
        out["draft_routes"] = {k: _shown(n) for k, n in rows}
    out["runs"] = _shown(total)
    out["silent_rate"] = round(none_n / total, 3) if total >= MIN_N and none_n >= MIN_N else None
    decided = sum(outcomes.values())
    out["outcome_rates"] = {k: round(n / decided, 3) for k, n in outcomes.items()
                            if n >= MIN_N and decided >= MIN_N}
    return out
