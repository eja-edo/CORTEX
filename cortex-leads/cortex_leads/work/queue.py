"""The life of one piece of slow work, shared (WP33): a recording to transcribe, a submission to grade. Both keep their state in a
row with the same columns (status, attempts, claimed_at, error, finished_at, created_at) and need the same four things done the
same way: take a few queued rows without two workers taking the same one, give back rows a dead worker left half done, let
only the worker that holds the latest claim write the result, and end a failure as a short code, never as the exception's text.
Not a workflow engine: no stages table, no scheduler, nothing a model class does not already have as columns."""
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

MAX_ATTEMPTS = 3
CLAIM_TTL = timedelta(hours=1)


async def claim[R](session: AsyncSession, model: type[R], where: list[Any], now: datetime, *, limit: int,
                ttl: timedelta = CLAIM_TTL) -> list[R]:
    """Up to `limit` queued rows matching `where`, oldest first, now `working` and stamped with `now` (the claim token).
    Rows `working` for longer than `ttl` are first put back in the queue: their worker is gone."""
    await session.execute(update(model).where(*where, model.status == "working", model.claimed_at < now - ttl).values(status="queued"))
    rows = list((await session.execute(select(model).where(*where, model.status == "queued")
                                       .order_by(model.created_at).limit(limit).with_for_update(skip_locked=True))).scalars())
    for r in rows:
        r.status, r.claimed_at, r.attempts = "working", now, r.attempts + 1
    return rows


async def mine[R](session: AsyncSession, model: type[R], row_id: Any, token: datetime) -> R | None:
    """The row, locked, if this worker still holds it. A worker slow past the TTL finds the row taken by another and gets None:
    it must not write over that one's result."""
    row = await session.get(model, row_id, with_for_update=True)
    return row if row is not None and row.status == "working" and row.claimed_at == token else None


def fail(row: Any, code: str, now: datetime, *, max_attempts: int = MAX_ATTEMPTS) -> None:
    """Record why this try ended, as a code. Back in the queue for another try, or `failed` once the tries are used up."""
    row.error = code
    row.status, row.finished_at = ("failed", now) if row.attempts >= max_attempts else ("queued", None)


def release(row: Any) -> None:
    """Give the row back without counting the try: the work was not attempted (over budget, a kill switch)."""
    row.status, row.claimed_at, row.attempts = "queued", None, row.attempts - 1
