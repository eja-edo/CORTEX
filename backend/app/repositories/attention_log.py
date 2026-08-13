from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttentionLevel, AttentionLog


class AttentionLogRepository:
    """Data access for `attention_log`. Every query is scoped by `user_id`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, entry: AttentionLog) -> AttentionLog:
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    async def get_by_id_and_user(self, log_id: UUID, user_id: UUID) -> AttentionLog | None:
        stmt = select(AttentionLog).where(
            AttentionLog.id == log_id, AttentionLog.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_last_spoken(
        self, user_id: UUID, item_id: UUID, reason_key: str, since: datetime
    ) -> AttentionLog | None:
        """The most recent row that actually reached the user for this
        (item_id, reason_key) pair since `since`.

        `silent` rows are excluded: they record a decision *not* to speak, so
        counting one as a prior surfacing would let a single silent
        evaluation gag Cortex for the rest of the window. See
        AttentionLogService.record_surface.

        Runs on ix_attention_log_user_item_reason_surfaced, whose column
        order matches this predicate exactly.
        """
        stmt = (
            select(AttentionLog)
            .where(
                AttentionLog.user_id == user_id,
                AttentionLog.item_id == item_id,
                AttentionLog.reason_key == reason_key,
                AttentionLog.surfaced_at >= since,
                AttentionLog.level != AttentionLevel.SILENT,
            )
            .order_by(AttentionLog.surfaced_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_item(self, user_id: UUID, item_id: UUID) -> Sequence[AttentionLog]:
        """Everything ever recorded for one item, oldest first — silent rows
        included, since "why did Cortex stay quiet?" is a primary question
        this table exists to answer."""
        stmt = (
            select(AttentionLog)
            .where(AttentionLog.user_id == user_id, AttentionLog.item_id == item_id)
            .order_by(AttentionLog.surfaced_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_by_user(
        self,
        user_id: UUID,
        item_type=None,
        reason_key: str | None = None,
        level=None,
        response=None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[AttentionLog]:
        stmt = select(AttentionLog).where(AttentionLog.user_id == user_id)
        if item_type is not None:
            stmt = stmt.where(AttentionLog.item_type == item_type)
        if reason_key is not None:
            stmt = stmt.where(AttentionLog.reason_key == reason_key)
        if level is not None:
            stmt = stmt.where(AttentionLog.level == level)
        if response is not None:
            stmt = stmt.where(AttentionLog.response == response)
        if since is not None:
            stmt = stmt.where(AttentionLog.surfaced_at >= since)
        stmt = stmt.order_by(AttentionLog.surfaced_at.desc()).limit(limit)
        return (await self.session.execute(stmt)).scalars().all()
