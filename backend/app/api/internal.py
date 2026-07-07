"""
Internal API Endpoints for Service-to-Service Communication

These endpoints are NOT exposed to the internet. They are used by internal
microservices (OCR service, LLM service) to update backend state.

Security: Protected by X-Internal-API-Key header.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Asset, AssetStatus, Notification
from app.api.sse.channels.notification_events import publish_notification
from app.core.internal_auth import verify_internal_key, get_internal_user, InternalUser
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


class AssetStatusUpdate(BaseModel):
    """Payload for updating asset processing status."""
    status: str  # "processing" | "completed" | "failed"
    failed_reason: str | None = None


def verify_internal_key(x_internal_api_key: str = Header(..., alias="X-Internal-API-Key")):
    """Verify that the request comes from an authorized internal service."""
    if not settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="INTERNAL_API_KEY not configured in backend",
        )
    
    if x_internal_api_key != settings.INTERNAL_API_KEY:
        logger.warning("Invalid internal API key attempt")
        raise HTTPException(
            status_code=403,
            detail="Invalid internal API key",
        )


@router.patch("/assets/{asset_id}/status")
def update_asset_status_internal(
    asset_id: UUID,
    payload: AssetStatusUpdate,
    _: None = Depends(verify_internal_key),
    db: Session = Depends(get_db),
):
    """
    Update asset processing status (called by OCR/LLM services).
    
    This endpoint allows internal microservices to update the Asset.status
    field in PostgreSQL without needing direct database access.
    
    Valid status values:
    - "processing": Asset is being processed
    - "completed": Processing finished successfully
    - "failed": Processing failed (provide failed_reason)
    """
    # Validate status value
    try:
        new_status = AssetStatus(payload.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {payload.status}. Must be one of: {[s.value for s in AssetStatus]}",
        )
    
    # Find asset
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(
            status_code=404,
            detail=f"Asset {asset_id} not found",
        )
    
    # Update status
    old_status = asset.status
    asset.status = new_status
    asset.updated_at = datetime.utcnow()
    
    if payload.failed_reason:
        asset.failed_reason = payload.failed_reason
    
    db.commit()
    
    logger.info(
        f"Asset {asset_id} status updated: {old_status.value} → {new_status.value}"
        + (f" (reason: {payload.failed_reason})" if payload.failed_reason else "")
    )
    
    return {"ok": True, "asset_id": str(asset_id), "status": new_status.value}


class NotificationBlockSchema(BaseModel):
    type: str  # text, image, html, code, markdown, etc.
    text: str | None = None
    url: str | None = None
    html: str | None = None
    language: str | None = None
    content: str | None = None


class NotificationActionSchema(BaseModel):
    label: str
    action: str = "navigate"
    url: str | None = None
    payload: dict[str, Any] | None = None


class CreateNotificationRequest(BaseModel):
    user_id: str
    title: str
    body: str = ""
    type: str = "system"
    content: list[NotificationBlockSchema] = []
    actions: list[NotificationActionSchema] = []


@router.post("/notifications", include_in_schema=False)
def create_notification_internal(
    payload: CreateNotificationRequest,
    _: None = Depends(verify_internal_key),
    db: Session = Depends(get_db),
):
    """Create a notification for a user (called by workflow actions)."""
    try:
        user_uuid = UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    # Auto-wrap body into a text block if no content provided
    content = payload.content
    if not content and payload.body:
        content = [NotificationBlockSchema(type="text", text=payload.body)]

    notification = Notification(
        user_id=user_uuid,
        title=payload.title,
        body=payload.body,
        type=payload.type,
        content=[b.model_dump() for b in content],
        actions=[a.model_dump() for a in payload.actions],
        created_at=datetime.utcnow(),
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    # Broadcast real-time notification via SSE
    publish_notification(
        user_id=payload.user_id,
        notification_id=str(notification.id),
        title=payload.title,
        body=payload.body,
        content=[b.model_dump() for b in content],
        actions=[a.model_dump() for a in payload.actions],
        notification_type=payload.type,
    )

    return {"ok": True, "notification_id": str(notification.id)}


@router.get("/health")
def internal_health_check(
    _: None = Depends(verify_internal_key),
):
    """
    Health check endpoint for internal services.
    
    Allows OCR/LLM services to verify backend is reachable and responsive.
    """
    return {
        "status": "healthy",
        "service": "backend",
        "ocr_service_mode": settings.OCR_SERVICE_MODE,
    }
