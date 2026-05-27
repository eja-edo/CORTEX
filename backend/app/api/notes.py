from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.database_async import get_async_db
from app.dependencies import get_current_active_user
from app.models import User
from app.schemas import NoteCreate, NotePatchRequest, NoteResponse, NoteRevisionResponse, NoteUpdate
from app.services.notes import NoteService
from app.services.workspace_permission import WorkspacePermission

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    try:
        created = await service.create_note(payload=payload, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return service.to_response(created)


@router.get("", response_model=list[NoteResponse])
async def get_notes(
    render_html: bool = Query(False, description="Render markdown to sanitized HTML"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    notes = await service.get_notes(current_user.id)
    responses: list[NoteResponse] = []
    for note in notes:
        content = await service.materialize_note_content(note)
        responses.append(service.to_response(note, render_html=render_html, content_override=content))
    return responses


@router.get("/workspaces/{workspace_id}", response_model=list[NoteResponse])
async def get_workspace_notes(
    workspace_id: UUID,
    render_html: bool = Query(False, description="Render markdown to sanitized HTML"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Get all notes in a workspace. User must be a member."""
    # Check workspace membership (sync DB)
    with SessionLocal() as sync_db:
        WorkspacePermission.require_member(workspace_id, current_user.id, sync_db)

    service = NoteService(db)
    notes = await service.get_notes_by_workspace(workspace_id)
    responses: list[NoteResponse] = []
    for note in notes:
        content = await service.materialize_note_content(note)
        responses.append(service.to_response(note, render_html=render_html, content_override=content))
    return responses


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    payload: NoteUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    current = await service.get_note(note_id=note_id, user_id=current_user.id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    # Only check version for content updates; metadata-only updates (e.g., parent_note_id) don't conflict
    is_content_update = payload.content is not None
    if is_content_update and current.version != payload.version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version conflict")

    try:
        updated = await service.update_note(note_id=note_id, user_id=current_user.id, payload=payload)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version conflict")

    content = await service.materialize_note_content(updated)
    return service.to_response(updated, content_override=content)


@router.post("/{note_id}/patch", response_model=NoteResponse)
async def patch_note(
    note_id: UUID,
    payload: NotePatchRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    current = await service.get_note(note_id=note_id, user_id=current_user.id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    if current.version != payload.version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version conflict")

    updated = await service.patch_note(note_id=note_id, user_id=current_user.id, payload=payload)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version conflict")

    content = await service.materialize_note_content(updated)
    return service.to_response(updated, content_override=content)


@router.get("/{note_id}/revisions", response_model=list[NoteRevisionResponse])
async def get_note_revisions(
    note_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    current = await service.get_note(note_id=note_id, user_id=current_user.id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return await service.list_revisions(note_id=note_id, user_id=current_user.id, limit=limit)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    deleted = await service.soft_delete(note_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return None
