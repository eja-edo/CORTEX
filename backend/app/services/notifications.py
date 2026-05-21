from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Notification


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_notifications(self, user_id: UUID, limit: int, offset: int) -> tuple[list[Notification], int]:
        query = self.db.query(Notification).filter(Notification.user_id == user_id)
        total = query.count()
        items = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()
        return items, total

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
        unread = self.db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        ).all()

        if not unread:
            return 0

        now = datetime.utcnow()
        for item in unread:
            item.read_at = now
            self.db.add(item)

        self.db.commit()
        return len(unread)
