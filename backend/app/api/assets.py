from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.dependencies import get_current_active_user
from app.models import Asset, AssetStatus, AssetType, User
from app.schemas import AssetCreate, AssetResponse, AssetUpdate
from app.services.redis.stt_producer import enqueue_transcription_job
from app.services.redis.ocr_processor_task import enqueue_video_processing
from app.services.workspace_permission import WorkspacePermission
from app.utils.logger import get_logger

router = APIRouter(prefix="/assets", tags=["assets"])
logger = get_logger(__name__)



from app.models import Upload

def _detect_media_type_from_upload(asset: Asset, db: Session) -> str:
    """
    Xác định media_type dựa trên content_type của upload liên kết.
    Nếu không có upload hoặc content_type, fallback về kiểm tra tên file.
    """
    if asset.source_upload_id:
        upload = db.query(Upload).filter(Upload.id == asset.source_upload_id).first()
        if upload and upload.content_type:
            content_type = upload.content_type.lower()
            if content_type.startswith("audio/"):
                return "audio"
            if content_type.startswith("video/"):
                return "video"
    # fallback cũ nếu không có upload/content_type
    filename = asset.source_object_key.lower()
    if filename.endswith((".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".webm")):
        return "audio"
    return "video"


async def _enqueue_all_processing(asset: Asset, db: Session) -> dict:
    """
    Enqueue cả STT (transcription) và OCR/video processing cho asset.

    - STT: áp dụng cho mọi asset có media (video + audio)
    - OCR: chỉ áp dụng cho video (không phải audio-only)

    Trả về dict {"stt": bool, "ocr": bool} cho biết task nào được enqueue thành công.
    """
    results = {"stt": False, "ocr": False}
    media_type = _detect_media_type_from_upload(asset, db)

    # ── STT ──────────────────────────────────────────────────────────────────
    eligible_for_stt = asset.type in {
        AssetType.UPLOADED_VIDEO,
        AssetType.SCREEN_RECORDING,
        AssetType.LIVE_SESSION,
    }
    if eligible_for_stt:
        try:
            await enqueue_transcription_job(
                asset_id=asset.id,
                egress_id=asset.id,
                user_id=asset.user_id,
                source_upload_id=asset.source_upload_id,
                source_object_key=asset.source_object_key,
                media_type=media_type,
                source_type=asset.type.value,
                filename=Path(asset.source_object_key).name,
                content_type=None,
                job_context={
                    "asset_type": asset.type.value,
                    "title": asset.title,
                },
            )
            results["stt"] = True
            logger.info(f"STT job enqueued for asset {asset.id}")
        except Exception as exc:
            logger.error(f"Failed to enqueue STT job for asset {asset.id}: {exc}")

    # ── OCR (video only) ──────────────────────────────────────────────────────
    if media_type == "video":
        try:
            await enqueue_video_processing(
                video_path=asset.source_object_key,  # object key trong MinIO
                output_dir="",                        # worker tự resolve từ task_id
                video_id=asset.id,
                user_id=asset.user_id,
                ocr_engine="easyocr",
                target_fps=1.0,
                enable_ui_detect=True,
                enable_ocr=True,
                job_context={
                    "asset_type": asset.type.value,
                    "title": asset.title,
                },
            )
            results["ocr"] = True
            logger.info(f"OCR job enqueued for asset {asset.id}")
        except Exception as exc:
            logger.error(f"Failed to enqueue OCR job for asset {asset.id}: {exc}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# CRUD endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AssetResponse])
def list_assets(
    status_filter: AssetStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(Asset).filter(
        Asset.user_id == current_user.id,
        Asset.deleted_at.is_(None),
    )
    if status_filter is not None:
        query = query.filter(Asset.status == status_filter)

    assets = query.order_by(Asset.created_at.desc()).offset(offset).limit(limit).all()
    return assets


@router.get("/workspaces/{workspace_id}", response_model=list[AssetResponse])
def list_workspace_assets(
    workspace_id: UUID,
    status_filter: AssetStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all assets in a workspace. User must be a member."""
    # Check workspace membership
    WorkspacePermission.require_member(workspace_id, current_user.id, db)

    query = db.query(Asset).filter(
        Asset.workspace_id == workspace_id,
        Asset.deleted_at.is_(None),
    )
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
    import logging

    _logger = logging.getLogger(__name__)

    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.user_id == current_user.id,
        Asset.deleted_at.is_(None),
    ).first()

    if not asset:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Asset not found", "asset_id": str(asset_id)},
        )

    try:
        asset.deleted_at = datetime.utcnow()
        asset.status = AssetStatus.ARCHIVED
        asset.updated_at = datetime.utcnow()
        db.add(asset)
        db.commit()

        _logger.info(f"Asset deleted successfully: user={current_user.id}, asset={asset_id}")

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Asset archived successfully",
                "asset_id": str(asset_id),
            },
        )

    except SQLAlchemyError as e:
        db.rollback()
        _logger.error(f"Database error deleting asset {asset_id}: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Database error during deletion",
                "details": str(e),
                "asset_id": str(asset_id),
            },
        )
    except Exception as e:
        db.rollback()
        _logger.error(f"Unexpected error deleting asset {asset_id}: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Internal server error",
                "asset_id": str(asset_id),
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Processing trigger
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{asset_id}/process")
async def process_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Trigger manual processing for a READY asset.

    Enqueues:
      - STT job  → stt_service xử lý transcript
      - OCR job  → ocr_worker xử lý video frames (chỉ với video)
        └─ Sau khi OCR xong, ocr_worker tự động enqueue LLM job

    Asset phải ở trạng thái READY mới được xử lý.
    Sau khi enqueue thành công, asset chuyển sang trạng thái PROCESSING.
    """
    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.user_id == current_user.id,
        Asset.deleted_at.is_(None),
    ).first()

    if not asset:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Asset not found", "asset_id": str(asset_id)},
        )

    if asset.status != AssetStatus.READY:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "Asset not ready for processing",
                "current_status": asset.status.value,
                "hint": "Asset must be in READY status to start processing.",
            },
        )

    results = await _enqueue_all_processing(asset, db=db)

    if not results["stt"] and not results["ocr"]:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Failed to enqueue any processing job",
                "asset_id": str(asset_id),
            },
        )

    # Chuyển sang PROCESSING chỉ khi ít nhất một job được enqueue thành công
    asset.status = AssetStatus.PROCESSING
    asset.updated_at = datetime.utcnow()
    db.add(asset)
    db.commit()

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": "Processing jobs enqueued successfully",
            "asset_id": str(asset_id),
            "jobs": {
                "stt": "enqueued" if results["stt"] else "failed",
                "ocr": "enqueued" if results["ocr"] else "skipped_or_failed",
            },
        },
    )