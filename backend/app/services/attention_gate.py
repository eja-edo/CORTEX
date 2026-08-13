"""Attention Gate (Milestone 6.1 M1 stub).

Every notification-creation path in the backend goes through the two
functions here — today they're a pure pass-through to NotificationService,
but this is the single seam Phase 6 (dedup, throttle, quiet-hours,
attention_log-driven suppression) fills in later, instead of retrofitting
every call site again once real gating logic exists.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Notification
from app.services.notifications import NotificationService, create_notification_async


async def request_attention_async(
    db: AsyncSession,
    *,
    user_id: UUID,
    title: str,
    body: str = "",
    type: str = "system",
    content: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
) -> Notification:
    return await create_notification_async(
        db, user_id=user_id, type=type, title=title, body=body,
        content=content, actions=actions, payload=payload,
    )


def request_attention_sync(
    db: Session,
    *,
    user_id: UUID,
    title: str,
    body: str = "",
    type: str = "system",
    content: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
) -> Notification:
    return NotificationService(db).create(
        user_id=user_id, type=type, title=title, body=body,
        content=content, actions=actions, payload=payload,
    )
