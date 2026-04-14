from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import Note, NoteSegmentLink, Segment, User
from app.schemas import NoteLinksByAssetResponse, NoteSegmentLinkPatchRequest, NoteSegmentLinkResponse

router = APIRouter(prefix="/notes", tags=["note-links"])


def _get_note_or_404(db: Session, note_id: UUID, user_id: UUID) -> Note:
    note = db.query(Note).filter(
        Note.id == note_id,
        Note.user_id == user_id,
        Note.is_deleted.is_(False),
    ).first()
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


def _get_segment_or_404(db: Session, segment_id: UUID, user_id: UUID) -> Segment:
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.user_id == user_id,
        Segment.deleted_at.is_(None),
    ).first()
    if not segment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return segment


@router.get("/{note_id}/links", response_model=NoteLinksByAssetResponse)
def get_note_links(
    note_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _get_note_or_404(db, note_id, current_user.id)

    links = db.query(NoteSegmentLink).filter(
        NoteSegmentLink.note_id == note_id,
        NoteSegmentLink.user_id == current_user.id,
        NoteSegmentLink.deleted_at.is_(None),
    ).order_by(NoteSegmentLink.linked_asset_id.asc(), NoteSegmentLink.linked_start_ms.asc()).all()

    grouped: dict[str, list[NoteSegmentLinkResponse]] = {}
    for link in links:
        key = str(link.linked_asset_id)
        grouped.setdefault(key, []).append(NoteSegmentLinkResponse.model_validate(link))

    return NoteLinksByAssetResponse(note_id=note_id, by_asset=grouped)


@router.patch("/{note_id}/links", response_model=NoteLinksByAssetResponse)
def patch_note_links(
    note_id: UUID,
    payload: NoteSegmentLinkPatchRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _get_note_or_404(db, note_id, current_user.id)

    for item in payload.remove:
        existing = db.query(NoteSegmentLink).filter(
            NoteSegmentLink.note_id == note_id,
            NoteSegmentLink.segment_id == item.segment_id,
            NoteSegmentLink.link_type == item.link_type,
            NoteSegmentLink.user_id == current_user.id,
            NoteSegmentLink.deleted_at.is_(None),
        ).first()
        if existing:
            existing.deleted_at = datetime.utcnow()
            existing.updated_at = datetime.utcnow()
            db.add(existing)

    for item in payload.add:
        segment = _get_segment_or_404(db, item.segment_id, current_user.id)
        if segment.asset_id != item.linked_asset_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="linked_asset_id must match segment.asset_id",
            )

        existing = db.query(NoteSegmentLink).filter(
            NoteSegmentLink.note_id == note_id,
            NoteSegmentLink.segment_id == item.segment_id,
            NoteSegmentLink.link_type == item.link_type,
            NoteSegmentLink.user_id == current_user.id,
        ).first()
        if existing:
            existing.linked_asset_id = item.linked_asset_id
            existing.linked_start_ms = item.linked_start_ms
            existing.linked_end_ms = item.linked_end_ms
            existing.weight = item.weight
            existing.anchor_text = item.anchor_text
            existing.start_offset = item.start_offset
            existing.end_offset = item.end_offset
            existing.meta = item.metadata
            existing.deleted_at = None
            existing.updated_at = datetime.utcnow()
            db.add(existing)
            continue

        db.add(NoteSegmentLink(
            user_id=current_user.id,
            note_id=note_id,
            segment_id=item.segment_id,
            linked_asset_id=item.linked_asset_id,
            linked_start_ms=item.linked_start_ms,
            linked_end_ms=item.linked_end_ms,
            link_type=item.link_type,
            weight=item.weight,
            anchor_text=item.anchor_text,
            start_offset=item.start_offset,
            end_offset=item.end_offset,
            created_by=current_user.id,
            meta=item.metadata,
        ))

    db.commit()
    return get_note_links(note_id=note_id, current_user=current_user, db=db)
