from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import Asset, AssetStatus, AssetType, User
from app.schemas import AssetCreate, AssetResponse, AssetUpdate
from app.services.redis.stt_producer import enqueue_transcription_job
from app.utils.logger import get_logger

router = APIRouter(prefix="/assets", tags=["assets"])
logger = get_logger(__name__)


async def _enqueue_stt_processing(
    asset: Asset, 
    db: Session,
    payload: 'AssetCreate' | None = None
) -> bool:
    """Enqueue STT transcription job for eligible video assets."""
    if asset.type not in {AssetType.UPLOADED_VIDEO, AssetType.SCREEN_RECORDING, AssetType.LIVE_SESSION}:
        return False
    
    try:
        from app.services.redis.stt_producer import enqueue_transcription_job
        
        await enqueue_transcription_job(
            asset_id=asset.id,
            egress_id=asset.id,
            workspace_id=asset.workspace_id,
            user_id=asset.user_id,
            source_upload_id=asset.source_upload_id,
            source_object_key=asset.source_object_key,
            media_type=_detect_media_type(asset.source_object_key),
            source_type=asset.type.value,
            filename=payload.title if payload and payload.title else Path(asset.source_object_key).name,
            content_type=None,
            job_context={
                "asset_type": asset.type.value,
                "title": asset.title,
                "description": asset.description,
            },
        )
        logger.info(f"STT job enqueued for asset {asset.id}")
        return True
    except Exception as exc:
        logger.error(f"Failed to enqueue STT job for asset {asset.id}: {exc}")
        return False


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

    # Auto STT processing removed - use POST /assets/{id}/process manually
    pass

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


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy.exc import SQLAlchemyError
    from fastapi.responses import JSONResponse
    import logging
    
    logger = logging.getLogger(__name__)
    
    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.user_id == current_user.id,
        Asset.deleted_at.is_(None),
    ).first()
    
    if not asset:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Asset not found", "asset_id": str(asset_id)}
        )
    
    try:
        asset.deleted_at = datetime.utcnow()
        asset.status = AssetStatus.ARCHIVED
        asset.updated_at = datetime.utcnow()
        db.add(asset)
        db.commit()
        
        logger.info(f"Asset deleted successfully: user={current_user.id}, asset={asset_id}")
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True, 
                "message": "Asset archived successfully",
                "asset_id": str(asset_id)
            }
        )
        
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting asset {asset_id}: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False, 
                "error": "Database error during deletion",
                "details": str(e),
                "asset_id": str(asset_id)
            }
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error deleting asset {asset_id}: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Internal server error",
                "asset_id": str(asset_id)
            }
        )


@router.post("/{asset_id}/process")
async def process_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import JSONResponse
    from sqlalchemy.exc import SQLAlchemyError
    
    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.user_id == current_user.id,
        Asset.deleted_at.is_(None),
    ).first()
    
    if not asset:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Asset not found", "asset_id": str(asset_id)}
        )
    
    if asset.status != AssetStatus.READY:
        return JSONResponse(
            status_code=400,
            content={
                "success": False, 
                "error": "Asset not ready for processing",
                "current_status": asset.status.value
            }
        )
    
    success = await _enqueue_stt_processing(asset, db=db)
    
    if success:
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "STT processing job enqueued",
                "asset_id": str(asset_id),
                "job_stream": "transcription:stream"
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Failed to enqueue processing job",
                "asset_id": str(asset_id)
            }
        )
