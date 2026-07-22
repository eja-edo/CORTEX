"""Get notifications tool."""

from typing import Optional
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification
from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GetNotificationsInput(BaseModel):
    """Validation model for get_notifications tool."""
    limit: int = Field(default=20, ge=1, le=100, description="Max notifications to return")
    unread_only: bool = Field(default=True, description="Only return unread notifications")


async def get_notifications_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Get user's notifications.
    
    Security:
    - Always filtered by ctx.user_id (from authenticated session)
    """
    limit = args.get("limit", 20)
    unread_only = args.get("unread_only", True)

    try:
        async with ctx.async_db() as db:
            stmt = (
                select(Notification)
                .where(Notification.user_id == ctx.user_id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )

            # Filter unread if requested
            if unread_only:
                stmt = stmt.where(Notification.read_at.is_(None))

            result = await db.execute(stmt)
            notifications = result.scalars().all()

            # Serialize notifications INSIDE the async context before session closes
            serialized = [
                {
                    "id": str(notif.id),
                    "type": notif.type,
                    "title": notif.title,
                    "body": notif.body,
                    "content": notif.content or [],
                    "actions": notif.actions or [],
                    "read_at": notif.read_at.isoformat() if notif.read_at else None,
                    "created_at": notif.created_at.isoformat(),
                }
                for notif in notifications
            ]

        return {
            "count": len(serialized),
            "notifications": serialized,
        }

    except Exception as exc:
        logger.error(f"get_notifications failed: {exc}", exc_info=True)
        raise


GET_NOTIFICATIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "description": "Maximum notifications to return",
        },
        "unread_only": {
            "type": "boolean",
            "description": "Only return unread notifications",
        },
    },
}

GET_NOTIFICATIONS_DEFINITION = {
    "name": "get_notifications",
    "handler": get_notifications_handler,
    "input_model": GetNotificationsInput,
    "schema": GET_NOTIFICATIONS_SCHEMA,
    "description": "Get user's notifications. Can filter to unread only.",
}
