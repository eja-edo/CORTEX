from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.tool_context import ToolContext
from app.database_async import get_async_db
from app.dependencies import get_current_user_or_internal
from app.schemas import (
    PlanProposalApproveRequest,
    PlanProposalApproveResponse,
    PlanProposalListResponse,
    PlanProposalRejectResponse,
    PlanProposalResponse,
)
from app.services.plan_proposal_service import PlanProposalService

router = APIRouter(prefix="/plan-proposals", tags=["plan-proposals"])


@router.get("/{proposal_id}", response_model=PlanProposalResponse)
async def get_proposal(
    proposal_id: UUID,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = PlanProposalService(db)
    proposal = await service.get_proposal(proposal_id, current_user.id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return service.to_response(proposal)


@router.get("", response_model=PlanProposalListResponse)
async def list_proposals(
    status_filter: str | None = Query(None, alias="status", pattern="^(pending|approved|rejected|expired)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = PlanProposalService(db)
    items, total = await service.list_proposals(
        user_id=current_user.id, status=status_filter, limit=limit, offset=offset,
    )
    return PlanProposalListResponse(items=[service.to_response(p) for p in items], total=total)


@router.post("/{proposal_id}/approve", response_model=PlanProposalApproveResponse)
async def approve_proposal(
    proposal_id: UUID,
    body: PlanProposalApproveRequest = PlanProposalApproveRequest(),
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Approve a plan proposal: create each item via the existing
    task.create/schedule.create commands. Best-effort — one item failing
    doesn't block the others; see per-item `results` in the response."""
    service = PlanProposalService(db)

    proposal = await service.get_proposal(proposal_id, current_user.id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    ctx = ToolContext(user_id=current_user.id, async_db=db, conversation_id=proposal.conversation_id)
    items_override = (
        [item.model_dump(mode="json") for item in body.items] if body.items is not None else None
    )

    try:
        proposal, results = await service.approve_proposal(
            proposal_id=proposal_id,
            user_id=current_user.id,
            ctx=ctx,
            items_override=items_override,
        )
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    created_count = sum(1 for r in results if r.outcome == "created")
    failed_count = len(results) - created_count

    return PlanProposalApproveResponse(
        proposal_id=proposal.id,
        status=proposal.status,
        results=results,
        created_count=created_count,
        failed_count=failed_count,
    )


@router.post("/{proposal_id}/reject", response_model=PlanProposalRejectResponse)
async def reject_proposal(
    proposal_id: UUID,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = PlanProposalService(db)
    try:
        proposal = await service.reject_proposal(proposal_id=proposal_id, user_id=current_user.id)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return PlanProposalRejectResponse(proposal_id=proposal.id, status=proposal.status)
