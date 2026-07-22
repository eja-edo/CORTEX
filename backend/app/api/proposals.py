from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_user_or_internal
from app.models import User
from app.schemas import (
    NoteEditProposalResponse,
    NoteProposalApproveResponse,
    NoteProposalListResponse,
    NoteProposalRejectResponse,
)
from app.services.notes import NoteService
from app.services.proposal_service import ProposalService

router = APIRouter(prefix="/note-proposals", tags=["note-proposals"])


@router.get("/{proposal_id}", response_model=NoteEditProposalResponse)
async def get_proposal(
    proposal_id: UUID,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Get a proposal with computed old/new content."""
    service = ProposalService(db)
    note_service = NoteService(db)

    proposal_data = await service.get_proposal_dict(proposal_id, current_user.id)
    if proposal_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    note = await note_service.get_note(note_id=proposal_data["note_id"], user_id=current_user.id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    old_content, new_content = await service.compute_proposal_content(proposal_data, note)

    return service.to_response_from_dict(proposal_data, old_content=old_content, new_content=new_content)


@router.get("", response_model=NoteProposalListResponse)
async def list_proposals(
    note_id: UUID | None = Query(None),
    status: str | None = Query(None, pattern="^(pending|applying|approved|rejected|expired|superseded)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """List proposals for the current user."""
    service = ProposalService(db)
    items, total = await service.list_proposals(
        user_id=current_user.id,
        note_id=note_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return NoteProposalListResponse(
        items=[
            service.to_response_from_dict({
                "id": p.id,
                "note_id": p.note_id,
                "base_revision_id": p.base_revision_id,
                "base_version": p.base_version,
                "patch": list(p.patch) if isinstance(p.patch, list) else [],
                "creator_type": p.creator_type,
                "creator_id": p.creator_id,
                "status": p.status,
                "approved_by": p.approved_by,
                "approved_at": p.approved_at,
                "rejected_by": p.rejected_by,
                "rejected_at": p.rejected_at,
                "last_viewed_at": p.last_viewed_at,
                "expires_at": p.expires_at,
                "conversation_id": p.conversation_id,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            })
            for p in items
        ],
        total=total,
    )


@router.post("/{proposal_id}/approve", response_model=NoteProposalApproveResponse)
async def approve_proposal(
    proposal_id: UUID,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Approve a proposal: apply the patch to the note.
    Idempotent: if already approved, returns current state.
    """
    service = ProposalService(db)
    note_service = NoteService(db)

    try:
        proposal, updated_note = await service.approve_proposal(
            proposal_id=proposal_id,
            user_id=current_user.id,
            note_service=note_service,
        )
    except ValueError as exc:
        if "Version conflict" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            )
        if "not found" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return NoteProposalApproveResponse(
        proposal_id=proposal.id,
        note_id=proposal.note_id,
        status=proposal.status,
        version=updated_note.version if updated_note else proposal.base_version,
    )


@router.post("/{proposal_id}/reject", response_model=NoteProposalRejectResponse)
async def reject_proposal(
    proposal_id: UUID,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Reject a proposal: set status to rejected (no DB changes).
    Idempotent: if already rejected, returns current state.
    """
    service = ProposalService(db)

    try:
        proposal = await service.reject_proposal(
            proposal_id=proposal_id,
            user_id=current_user.id,
        )
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return NoteProposalRejectResponse(
        proposal_id=proposal.id,
        note_id=proposal.note_id,
        status=proposal.status,
    )
