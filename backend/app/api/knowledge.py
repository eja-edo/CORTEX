"""
Knowledge API Endpoints

Endpoints to query OCR frames, processed windows, and extracted knowledge.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_current_active_user
from app.models import User
from app.services.mongo_service import mongo_ocr_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/assets/{asset_id}/summary")
async def get_asset_summary(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
):
    """Get session-level knowledge summary for an asset."""
    if not mongo_ocr_service.is_connected:
        await mongo_ocr_service.connect()

    doc = await mongo_ocr_service.get_asset_knowledge(str(asset_id))
    if not doc:
        raise HTTPException(
            status_code=404, detail="Knowledge summary not yet generated"
        )

    # Verify ownership
    if doc.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/assets/{asset_id}/frames")
async def get_asset_ocr_frames(
    asset_id: UUID,
    skip_empty: bool = Query(default=True),
    current_user: User = Depends(get_current_active_user),
):
    """Get all OCR frames for an asset."""
    if not mongo_ocr_service.is_connected:
        await mongo_ocr_service.connect()

    frames = await mongo_ocr_service.get_ocr_frames(
        str(asset_id), skip_empty=skip_empty
    )

    # Verify ownership by checking first frame
    if frames and frames[0].get("user_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    for f in frames:
        f["_id"] = str(f["_id"])
    return frames


@router.get("/assets/{asset_id}/processed")
async def get_asset_processed_windows(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
):
    """Get all processed (Gemini-analyzed) windows for an asset."""
    if not mongo_ocr_service.is_connected:
        await mongo_ocr_service.connect()

    windows = await mongo_ocr_service.get_ocr_processed(str(asset_id))

    # Verify ownership
    if windows and windows[0].get("user_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    for w in windows:
        w["_id"] = str(w["_id"])
    return windows


@router.get("/units")
async def get_knowledge_units(
    asset_id: UUID | None = Query(default=None),
    unit_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
):
    """Get extracted knowledge units, optionally filtered by asset and type."""
    if not mongo_ocr_service.is_connected:
        await mongo_ocr_service.connect()

    units = await mongo_ocr_service.get_knowledge_units(
        user_id=str(current_user.id),
        asset_id=str(asset_id) if asset_id else None,
        unit_type=unit_type,
        limit=limit,
    )

    for u in units:
        u["_id"] = str(u["_id"])
    return units
