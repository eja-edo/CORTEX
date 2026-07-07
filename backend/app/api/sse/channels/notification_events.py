from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from anyio import from_thread
from fastapi import APIRouter, Depends, Query

from app.api.sse.sse_base import create_sse_response, event_generator
from app.api.sse.sse_manager import SSEManager
from app.dependencies import get_current_active_user
from app.models import User
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/sse/notifications", tags=["sse-notifications"])

NOTIFICATION_CHANNEL_TYPE = "notifications"


async def _broadcast_notification_event(message: dict[str, Any], user_id: str) -> int:
    manager = SSEManager()
    context_key = f"user:{user_id}"
    return await manager.broadcast_message(NOTIFICATION_CHANNEL_TYPE, context_key, message)


def publish_notification(
    *,
    user_id: str,
    notification_id: str,
    title: str,
    body: str,
    notification_type: str = "system",
    content: list[dict] | None = None,
    actions: list[dict] | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Publish a notification event for one user.

    This sync helper is intentionally sync-safe so it can be called from
    FastAPI sync endpoints (threadpool workers).
    """
    message: dict[str, Any] = {
        "event": "notification.created",
        "notification_id": notification_id,
        "title": title,
        "body": body,
        "content": content or [],
        "actions": actions or [],
        "type": notification_type,
        "payload": payload or {},
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        delivered = from_thread.run(_broadcast_notification_event, message, user_id)
        logger.debug(
            "[SSE Notifications] Published notification event to %s subscriber(s) for user %s",
            delivered,
            user_id,
        )
    except RuntimeError:
        # Fallback when called outside anyio worker thread context.
        delivered = asyncio.run(_broadcast_notification_event(message, user_id))
        logger.debug(
            "[SSE Notifications] Published notification event via fallback to %s subscriber(s) for user %s",
            delivered,
            user_id,
        )
    except Exception:
        logger.exception("[SSE Notifications] Failed to publish notification event for user %s", user_id)


@router.get("/events")
async def stream_notification_events(
    appid: str = Query(default="web", min_length=1, max_length=100),
    current_user: User = Depends(get_current_active_user),
):
    """SSE stream of notification events for the authenticated user."""
    manager = SSEManager()
    context_key = f"user:{current_user.id}"

    # Keep one active connection per appid for this user's notification channel.
    await manager.disconnect_existing_appid(NOTIFICATION_CHANNEL_TYPE, context_key, appid)
    connection_id = await manager.register_connection(NOTIFICATION_CHANNEL_TYPE, context_key, appid)
    connection_queue = await manager.create_connection_queue(NOTIFICATION_CHANNEL_TYPE, context_key, connection_id)

    return create_sse_response(
        event_generator(
            channel_type=NOTIFICATION_CHANNEL_TYPE,
            context_key=context_key,
            connection_id=connection_id,
            connection_queue=connection_queue,
            manager=manager,
        )
    )