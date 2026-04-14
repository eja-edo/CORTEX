from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import Asset, NoteSegmentLink, Segment, SegmentContent, SegmentSource, User
from app.schemas import (
    SegmentBatchUpsertRequest,
    SegmentBatchUpsertResponse,
    SegmentCreate,
    SegmentNoteLinkView,
    SegmentResponse,
)

router = APIRouter(tags=["segments"])


def _get_asset_or_404(db: Session, asset_id: UUID, user_id: UUID) -> Asset:
    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.user_id == user_id,
        Asset.deleted_at.is_(None),
    ).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


def _serialize_segment(segment: Segment, db: Session) -> SegmentResponse:
    contents = (
        db.query(SegmentContent)
        .filter(SegmentContent.segment_id == segment.id)
        .order_by(SegmentContent.created_at.asc())
        .all()
    )
    return SegmentResponse.model_validate({
        "id": segment.id,
        "user_id": segment.user_id,
        "asset_id": segment.asset_id,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "source": segment.source,
        "confidence": segment.confidence,
        "keyframe_url": segment.keyframe_url,
        "language": segment.language,
        "external_id": segment.external_id,
        "metadata": segment.meta,
        "created_at": segment.created_at,
        "updated_at": segment.updated_at,
        "contents": contents,
    })


@router.get("/assets/{asset_id}/segments", response_model=list[SegmentResponse])
def list_asset_segments(
    asset_id: UUID,
    from_ms: int | None = Query(default=None, ge=0),
    to_ms: int | None = Query(default=None, ge=1),
    source: SegmentSource | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _get_asset_or_404(db, asset_id, current_user.id)

    query = db.query(Segment).filter(
        Segment.asset_id == asset_id,
        Segment.user_id == current_user.id,
        Segment.deleted_at.is_(None),
    )
    if from_ms is not None:
        query = query.filter(Segment.end_ms >= from_ms)
    if to_ms is not None:
        query = query.filter(Segment.start_ms <= to_ms)
    if source is not None:
        query = query.filter(Segment.source == source)

    segments = query.order_by(Segment.start_ms.asc()).offset(offset).limit(limit).all()
    return [_serialize_segment(segment, db) for segment in segments]


@router.post("/assets/{asset_id}/segments", response_model=SegmentResponse, status_code=status.HTTP_201_CREATED)
def create_segment(
    asset_id: UUID,
    payload: SegmentCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _get_asset_or_404(db, asset_id, current_user.id)

    segment = Segment(
        user_id=current_user.id,
        asset_id=asset_id,
        start_ms=payload.start_ms,
        end_ms=payload.end_ms,
        source=payload.source,
        confidence=payload.confidence,
        keyframe_url=payload.keyframe_url,
        language=payload.language,
        external_id=payload.external_id,
        meta=payload.metadata,
    )
    db.add(segment)
    db.flush()

    for item in payload.contents:
        db.add(SegmentContent(
            segment_id=segment.id,
            content_type=item.content_type,
            content=item.content,
            language=item.language,
            confidence=item.confidence,
            meta=item.metadata,
        ))

    db.commit()
    db.refresh(segment)
    return _serialize_segment(segment, db)


@router.post("/segments/batch", response_model=SegmentBatchUpsertResponse)
def batch_upsert_segments(
    payload: SegmentBatchUpsertRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _get_asset_or_404(db, payload.asset_id, current_user.id)

    created = 0
    updated = 0
    skipped = 0

    for item in payload.segments:
        existing = None
        if item.external_id:
            existing = db.query(Segment).filter(
                Segment.asset_id == payload.asset_id,
                Segment.external_id == item.external_id,
                Segment.user_id == current_user.id,
                Segment.deleted_at.is_(None),
            ).first()

        if existing:
            existing.start_ms = item.start_ms
            existing.end_ms = item.end_ms
            existing.source = item.source
            existing.confidence = item.confidence
            existing.keyframe_url = item.keyframe_url
            existing.language = item.language
            existing.meta = item.metadata
            existing.updated_at = datetime.utcnow()
            db.query(SegmentContent).filter(SegmentContent.segment_id == existing.id).delete()
            for content_item in item.contents:
                db.add(SegmentContent(
                    segment_id=existing.id,
                    content_type=content_item.content_type,
                    content=content_item.content,
                    language=content_item.language,
                    confidence=content_item.confidence,
                    meta=content_item.metadata,
                ))
            updated += 1
            continue

        if not item.external_id and not item.contents:
            skipped += 1
            continue

        segment = Segment(
            user_id=current_user.id,
            asset_id=payload.asset_id,
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            source=item.source,
            confidence=item.confidence,
            keyframe_url=item.keyframe_url,
            language=item.language,
            external_id=item.external_id,
            meta=item.metadata,
        )
        db.add(segment)
        db.flush()

        for content_item in item.contents:
            db.add(SegmentContent(
                segment_id=segment.id,
                content_type=content_item.content_type,
                content=content_item.content,
                language=content_item.language,
                confidence=content_item.confidence,
                meta=content_item.metadata,
            ))

        created += 1

    db.commit()
    return SegmentBatchUpsertResponse(created=created, updated=updated, skipped=skipped)


@router.get("/segments/{segment_id}/notes", response_model=list[SegmentNoteLinkView])
def get_segment_notes(
    segment_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.user_id == current_user.id,
        Segment.deleted_at.is_(None),
    ).first()
    if not segment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")

    links = db.query(NoteSegmentLink).filter(
        NoteSegmentLink.segment_id == segment_id,
        NoteSegmentLink.user_id == current_user.id,
        NoteSegmentLink.deleted_at.is_(None),
    ).order_by(NoteSegmentLink.created_at.desc()).all()

    return [
        SegmentNoteLinkView(
            note_id=link.note_id,
            link=link,
        )
        for link in links
    ]
