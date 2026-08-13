from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import User
from app.schemas import MessageResponse, NotificationListResponse, NotificationResponse
from app.services.notifications import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = NotificationService(db)
    items, total = service.list_notifications(user_id=current_user.id, limit=limit, offset=offset)
    return NotificationListResponse(items=items, total=total)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = NotificationService(db)
    notification = service.mark_as_read(notification_id=notification_id, user_id=current_user.id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notification


@router.post("/read-all", response_model=MessageResponse)
def mark_all_notifications_read(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = NotificationService(db)
    updated_count = service.mark_all_as_read(user_id=current_user.id)
    return MessageResponse(message=f"Marked {updated_count} notifications as read")


@router.delete("/{notification_id}", response_model=MessageResponse)
def delete_notification(
    notification_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = NotificationService(db)
    deleted = service.delete(notification_id=notification_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return MessageResponse(message="Notification deleted")
