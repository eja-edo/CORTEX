"""
Attention Bundle Queue (Milestone 6.1 M3 — steps 4-5, bundling + timing).

Step 3 of the Gate (attention_gate.py) can downgrade a non-critical
candidate to SILENT while the user is busy. Before M3, that was the end of
the story — a silenced candidate was simply never delivered. This module is
where it goes instead: `enqueue_async`/`enqueue_sync` are called by the Gate
right after a busy-downgrade, and `AttentionBundleWorker` (attention_bundle_worker.py)
periodically finds users who've become free again and turns everything
they accumulated into one Notification — the planning doc's own scenario
for 6.1 ("8 candidates during a meeting -> 0 during, 1 bundled after").

The bundle Notification itself does **not** go back through the Gate. It
already *is* the Gate's output for those candidates — re-gating it would be
asking "is it worth mentioning that I decided this was worth mentioning",
and could in principle silence itself forever if the user is back-to-back
busy. `flush_due_bundles` only fires once `is_user_busy` is false, which is
the Gate's own step-3 predicate — so the timing rule ("khi nào tốt" — leaving
a busy state) is honoured, just from the flush side instead of the
candidate side.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import AttentionBundleQueue, AttentionItemType, AttentionLevel
from app.services.availability import is_user_busy
from app.services.notifications import create_notification_async
from app.utils.logger import get_logger

logger = get_logger(__name__)

BUNDLE_REASON_KEY = "attention.bundle"


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def enqueue_async(
    session: AsyncSession,
    *,
    user_id: UUID,
    item_type: AttentionItemType,
    item_id: UUID,
    reason_key: str,
    title: str,
    body: str | None,
    payload: dict[str, Any] | None,
    actions: list[dict[str, Any]] | None,
    attention_log_id: UUID | None,
) -> AttentionBundleQueue:
    entry = AttentionBundleQueue(
        user_id=user_id, item_type=item_type, item_id=item_id, reason_key=reason_key,
        title=title, body=body, payload=payload or {}, actions=actions or [],
        attention_log_id=attention_log_id,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


def enqueue_sync(
    session: Session,
    *,
    user_id: UUID,
    item_type: AttentionItemType,
    item_id: UUID,
    reason_key: str,
    title: str,
    body: str | None,
    payload: dict[str, Any] | None,
    actions: list[dict[str, Any]] | None,
    attention_log_id: UUID | None,
) -> AttentionBundleQueue:
    entry = AttentionBundleQueue(
        user_id=user_id, item_type=item_type, item_id=item_id, reason_key=reason_key,
        title=title, body=body, payload=payload or {}, actions=actions or [],
        attention_log_id=attention_log_id,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def _compose_bundle(
    rows: list[AttentionBundleQueue],
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
    """Returns `(title, body, content, payload)`.

    Both `body` (a single " • "-joined line) and `content` (one text block
    per item) carry the same list, deliberately redundant: `body` is what
    the compact single-line surfaces read (NotificationsPage's row
    snippet only looks at `body`, never `content`); `content`, rendered
    through BlockRenderer, is what the detail modal prefers and is what
    actually stacks one item per line — `_build_notification` only
    auto-derives `content` from `body` when `content` is omitted, and that
    auto-derived single block doesn't get the `white-space: pre-wrap` CSS
    a hand-built multi-line `body` would need, so passing embedded `\n`s in
    `body` alone silently collapsed to one line in the modal. Building the
    blocks explicitly here sidesteps that rather than special-casing the
    frontend for one notification type.
    """
    if len(rows) == 1:
        title = f"Trong lúc bạn bận: {rows[0].title}"
    else:
        title = f"Trong lúc bạn bận có {len(rows)} việc cần chú ý"
    body = " • ".join(row.title for row in rows)
    content = [{"type": "text", "text": f"• {row.title}"} for row in rows]
    payload = {
        "bundled_items": [
            {
                "item_type": row.item_type.value,
                "item_id": str(row.item_id),
                "reason_key": row.reason_key,
                "title": row.title,
                "payload": row.payload,
            }
            for row in rows
        ]
    }
    return title, body, content, payload


async def _users_with_pending_bundles(session: AsyncSession) -> list[UUID]:
    stmt = (
        select(AttentionBundleQueue.user_id)
        .where(AttentionBundleQueue.flushed_at.is_(None))
        .distinct()
    )
    return list((await session.execute(stmt)).scalars().all())


async def _pending_rows_for_user(session: AsyncSession, user_id: UUID) -> list[AttentionBundleQueue]:
    stmt = (
        select(AttentionBundleQueue)
        .where(AttentionBundleQueue.user_id == user_id, AttentionBundleQueue.flushed_at.is_(None))
        .order_by(AttentionBundleQueue.queued_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def flush_due_bundles(session: AsyncSession) -> int:
    """Flush every user whose pending bundle is ready to go out (no longer
    busy). Returns how many users were flushed this sweep — the worker logs
    it, tests assert on it.

    One user at a time, each in its own transaction: a failure partway
    through (bad row, DB hiccup) must not roll back bundles for users who
    already succeeded in this same sweep, and the next sweep interval will
    simply retry whatever didn't get flushed.
    """
    flushed = 0
    for user_id in await _users_with_pending_bundles(session):
        try:
            if await is_user_busy(session, user_id):
                continue
            rows = await _pending_rows_for_user(session, user_id)
            if not rows:
                continue

            title, body, content, payload = _compose_bundle(rows)
            notification = await create_notification_async(
                session, user_id=user_id, type="attention_bundle", title=title, body=body,
                content=content, payload=payload, reason_key=BUNDLE_REASON_KEY,
                attention_level=AttentionLevel.INFORM,
            )
            now = _naive_utcnow()
            for row in rows:
                row.flushed_at = now
                row.bundle_notification_id = notification.id
            await session.commit()
            flushed += 1
        except Exception:
            await session.rollback()
            logger.exception("Failed to flush attention bundle for user %s", user_id)
    return flushed
