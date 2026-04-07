from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.schemas import BatchUpdateItem, BatchUpdateResponse, NoteCreate, NoteResponse, NoteUpdate
from app.services.notes import NoteService

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(payload: NoteCreate, db: AsyncSession = Depends(get_async_db)):
    service = NoteService(db)
    created = await service.create_note(payload)
    return service.to_response(created)


@router.get("", response_model=list[NoteResponse])
async def get_notes(
    user_id: UUID = Query(..., description="Owner user ID"),
    render_html: bool = Query(False, description="Render markdown to sanitized HTML"),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    notes = await service.get_notes(user_id)
    return [service.to_response(note, render_html=render_html) for note in notes]


@router.patch("/batch", response_model=BatchUpdateResponse)
async def batch_update_notes(
    items: list[BatchUpdateItem],
    user_id: UUID = Query(..., description="Owner user ID"),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    return await service.batch_update(user_id=user_id, items=items)


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    payload: NoteUpdate,
    user_id: UUID = Query(..., description="Owner user ID"),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    current = await service.get_note(note_id=note_id, user_id=user_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    if current.version != payload.version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version conflict")

    updated = await service.update_note(note_id=note_id, user_id=user_id, payload=payload)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version conflict")

    return service.to_response(updated)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    user_id: UUID = Query(..., description="Owner user ID"),
    db: AsyncSession = Depends(get_async_db),
):
    service = NoteService(db)
    deleted = await service.soft_delete(note_id, user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return None
