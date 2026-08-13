from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_user_or_internal
from app.models import AttentionItemType, AttentionLevel, AttentionResponse
from app.schemas import (
    AttentionItemHistory,
    AttentionLogResponse,
    AttentionResponseUpdate,
    AttentionSurfaceCreate,
    AttentionSurfaceResult,
)
from app.services.attention_log import AttentionLogService

router = APIRouter(prefix="/attention-log", tags=["attention-log"])


@router.post("", response_model=AttentionSurfaceResult, status_code=status.HTTP_200_OK)
async def record_surface(
    payload: AttentionSurfaceCreate,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Record a surfacing decision, including a decision to stay silent.

    Returns 200 rather than 201 because the honest answer is sometimes "no
    row was written, this was already surfaced" — suppression is a normal
    outcome, not a client error. `suppressed` in the body says which
    happened.
    """
    service = AttentionLogService(db)
    return await service.record_surface(payload=payload, user_id=current_user.id)


@router.get("", response_model=list[AttentionLogResponse])
async def list_attention_log(
    item_type: AttentionItemType | None = Query(None),
    reason_key: str | None = Query(None, description="Exact reason_key match"),
    level: AttentionLevel | None = Query(
        None, description="Pass 'silent' to review what Cortex chose not to say"
    ),
    response: AttentionResponse | None = Query(None),
    since: datetime | None = Query(None, description="Only surfacings at or after this time"),
    limit: int = Query(100, ge=1, le=500),
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = AttentionLogService(db)
    rows = await service.list_logs(
        current_user.id,
        item_type=item_type,
        reason_key=reason_key,
        level=level,
        response=response,
        since=since,
        limit=limit,
    )
    return [service.to_response(row) for row in rows]


@router.get("/items/{item_id}", response_model=AttentionItemHistory)
async def get_item_history(
    item_id: UUID,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Has this item been surfaced, for what reasons, how many times, and how
    did the user respond? (2.9 M2.)

    Never 404s: "this item has never been surfaced" is a real answer, and the
    caller asking is usually the Attention Gate deciding whether to speak.
    """
    service = AttentionLogService(db)
    return await service.get_item_history(user_id=current_user.id, item_id=item_id)


@router.get("/items/{item_id}/should-surface", response_model=AttentionSurfaceResult)
async def check_should_surface(
    item_id: UUID,
    reason_key: str = Query(..., min_length=1, max_length=100),
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Would surfacing this (item, reason) right now be a repeat?

    A read-only dry run of the dedup rule, so a caller can skip composing a
    message it isn't allowed to send. Writes nothing.
    """
    service = AttentionLogService(db)
    previous = await service.was_recently_surfaced(
        user_id=current_user.id, item_id=item_id, reason_key=reason_key
    )
    if previous is None:
        return AttentionSurfaceResult(
            suppressed=False, dedup_window_hours=service.dedup_window_hours, log=None
        )
    return AttentionSurfaceResult(
        suppressed=True,
        reason=(
            f"Already surfaced for '{reason_key}' at "
            f"{previous.surfaced_at.isoformat()} — inside the "
            f"{service.dedup_window_hours}h dedup window"
        ),
        dedup_window_hours=service.dedup_window_hours,
        log=service.to_response(previous),
    )


@router.get("/{log_id}", response_model=AttentionLogResponse)
async def get_attention_log(
    log_id: UUID,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = AttentionLogService(db)
    entry = await service.get_log(log_id=log_id, user_id=current_user.id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attention log entry not found")
    return service.to_response(entry)


@router.post("/{log_id}/response", response_model=AttentionLogResponse)
async def record_response(
    log_id: UUID,
    payload: AttentionResponseUpdate,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Attach the user's reaction to a surfacing — the raw material for the
    Feedback Loop (6.9)."""
    service = AttentionLogService(db)
    updated = await service.record_response(
        log_id=log_id, user_id=current_user.id, response=payload.response
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attention log entry not found")
    return service.to_response(updated)
