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

router = APIRouter(prefix="/sse/sync", tags=["sse-sync"])

SYNC_CHANNEL_TYPE = "sync-events"


async def _broadcast_sync_event(message: dict[str, Any], user_id: str) -> int:
    manager = SSEManager()
    context_key = f"user:{user_id}"
    return await manager.broadcast_message(SYNC_CHANNEL_TYPE, context_key, message)


def publish_sync_event(
    *,
    user_id: str,
    source: str,
    trigger: str,
    stats: dict[str, int] | None = None,
    detail: str | None = None,
) -> None:
    """Publish a sync status event for one user.

    This sync helper is intentionally sync-safe so it can be called from
    FastAPI sync endpoints (threadpool workers).
    """
    message: dict[str, Any] = {
        "event": "sync.update",
        "source": source,
        "trigger": trigger,
        "stats": stats or {},
        "detail": detail,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        delivered = from_thread.run(_broadcast_sync_event, message, user_id)
        logger.debug("[SSE Sync] Published sync event to %s subscriber(s) for user %s", delivered, user_id)
    except RuntimeError:
        # Fallback when called outside anyio worker thread context.
        delivered = asyncio.run(_broadcast_sync_event(message, user_id))
        logger.debug("[SSE Sync] Published sync event via fallback to %s subscriber(s) for user %s", delivered, user_id)
    except Exception:
        logger.exception("[SSE Sync] Failed to publish sync event for user %s", user_id)


@router.get("/events")
async def stream_sync_events(
    appid: str = Query(default="web", min_length=1, max_length=100),
    current_user: User = Depends(get_current_active_user),
):
    """SSE stream of sync events for the authenticated user."""
    manager = SSEManager()
    context_key = f"user:{current_user.id}"

    # Keep one active connection per appid for this user's sync channel.
    await manager.disconnect_existing_appid(SYNC_CHANNEL_TYPE, context_key, appid)
    connection_id = await manager.register_connection(SYNC_CHANNEL_TYPE, context_key, appid)
    connection_queue = await manager.create_connection_queue(SYNC_CHANNEL_TYPE, context_key, connection_id)

    return create_sse_response(
        event_generator(
            channel_type=SYNC_CHANNEL_TYPE,
            context_key=context_key,
            connection_id=connection_id,
            connection_queue=connection_queue,
            manager=manager,
        )
    )
