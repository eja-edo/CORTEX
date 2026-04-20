from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import Asset, AssetStatus, AssetType, User
from app.schemas import AssetCreate, AssetResponse, AssetUpdate
from app.services.redis.stt_producer import enqueue_transcription_job
from app.utils.logger import get_logger

router = APIRouter(prefix="/assets", tags=["assets"])
logger = get_logger(__name__)


def _detect_media_type(source_object_key: str) -> str:
    filename = source_object_key.lower()
    if filename.endswith((".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".webm")):
        return "audio"
    return "video"


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    payload: AssetCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    asset = Asset(
        user_id=current_user.id,
        workspace_id=payload.workspace_id,
        type=payload.type,
        title=payload.title,
        description=payload.description,
        source_upload_id=payload.source_upload_id,
        source_object_key=payload.source_object_key,
        status=AssetStatus.PENDING,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    if asset.type in {AssetType.UPLOADED_VIDEO, AssetType.SCREEN_RECORDING, AssetType.LIVE_SESSION}:
        try:
            await enqueue_transcription_job(
                asset_id=asset.id,
                egress_id=asset.id,
                workspace_id=asset.workspace_id,
                user_id=asset.user_id,
                source_upload_id=asset.source_upload_id,
                source_object_key=asset.source_object_key,
                media_type=_detect_media_type(asset.source_object_key),
                source_type=asset.type.value,
                filename=payload.title or Path(asset.source_object_key).name,
                content_type=None,
                job_context={
                    "asset_type": asset.type.value,
                    "title": asset.title,
                    "description": asset.description,
                },
            )
        except Exception as exc:
            logger.warning(f"Failed to enqueue STT job for asset {asset.id}: {exc}")

    return asset


@router.get("", response_model=list[AssetResponse])
def list_assets(
    status_filter: AssetStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(Asset).filter(Asset.user_id == current_user.id, Asset.deleted_at.is_(None))
    if status_filter is not None:
        query = query.filter(Asset.status == status_filter)

    assets = query.order_by(Asset.created_at.desc()).offset(offset).limit(limit).all()
    return assets


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.user_id == current_user.id,
        Asset.deleted_at.is_(None),
    ).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.patch("/{asset_id}", response_model=AssetResponse)
def update_asset(
    asset_id: UUID,
    payload: AssetUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.user_id == current_user.id,
        Asset.deleted_at.is_(None),
    ).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "metadata" and value is not None:
            existing = asset.meta or {}
            asset.meta = {**existing, **value}
            continue
        setattr(asset, key, value)

    asset.updated_at = datetime.utcnow()
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.user_id == current_user.id,
        Asset.deleted_at.is_(None),
    ).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    asset.deleted_at = datetime.utcnow()
    asset.status = AssetStatus.ARCHIVED
    asset.updated_at = datetime.utcnow()
    db.add(asset)
    db.commit()
    return None
