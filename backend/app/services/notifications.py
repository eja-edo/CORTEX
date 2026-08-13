from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.sse.channels.notification_events import publish_notification
from app.models import Notification


def _build_notification(
    *,
    user_id: UUID,
    type: str,
    title: str,
    body: str = "",
    content: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
) -> Notification:
    if not content and body:
        content = [{"type": "text", "text": body}]
    return Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        content=content or [],
        actions=actions or [],
        payload=payload or {},
    )


async def create_notification_async(
    db: AsyncSession,
    *,
    user_id: UUID,
    type: str,
    title: str,
    body: str = "",
    content: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
) -> Notification:
    notification = _build_notification(
        user_id=user_id, type=type, title=title, body=body,
        content=content, actions=actions, payload=payload,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)

    publish_notification(
        user_id=str(user_id),
        notification_id=str(notification.id),
        title=notification.title,
        body=notification.body or "",
        content=notification.content,
        actions=notification.actions,
        notification_type=notification.type,
        payload=notification.payload,
    )
    return notification


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: UUID,
        type: str,
        title: str,
        body: str = "",
        content: list[dict[str, Any]] | None = None,
        actions: list[dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Notification:
        notification = _build_notification(
            user_id=user_id, type=type, title=title, body=body,
            content=content, actions=actions, payload=payload,
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)

        publish_notification(
            user_id=str(user_id),
            notification_id=str(notification.id),
            title=notification.title,
            body=notification.body or "",
            content=notification.content,
            actions=notification.actions,
            notification_type=notification.type,
            payload=notification.payload,
        )
        return notification

    def list_notifications(self, user_id: UUID, limit: int, offset: int) -> tuple[list[Notification], int]:
        query = self.db.query(Notification).filter(Notification.user_id == user_id)
        total = query.count()
        items = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()
        return items, total

    def delete(self, notification_id: UUID, user_id: UUID) -> bool:
        notification = self.db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        ).first()
        if notification is None:
            return False

        self.db.delete(notification)
        self.db.commit()
        return True

    def mark_as_read(self, notification_id: UUID, user_id: UUID) -> Notification | None:
        notification = self.db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        ).first()
        if notification is None:
            return None

        if notification.read_at is None:
            notification.read_at = datetime.utcnow()
            self.db.add(notification)
            self.db.commit()
            self.db.refresh(notification)

        return notification

    def mark_all_as_read(self, user_id: UUID) -> int:
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=datetime.utcnow())
            .execution_options(synchronize_session=False)
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return result.rowcount
