from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteEditProposal


class ProposalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, proposal: NoteEditProposal) -> NoteEditProposal:
        self.session.add(proposal)
        await self.session.flush()
        await self.session.refresh(proposal)
        return proposal

    async def get_by_id(self, proposal_id: UUID) -> NoteEditProposal | None:
        stmt = select(NoteEditProposal).where(NoteEditProposal.id == proposal_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_by_note(
        self, note_id: UUID, include_superseded: bool = False
    ) -> Sequence[NoteEditProposal]:
        stmt = (
            select(NoteEditProposal)
            .where(NoteEditProposal.note_id == note_id)
            .order_by(NoteEditProposal.created_at.desc())
        )
        if not include_superseded:
            stmt = stmt.where(NoteEditProposal.status.in_(["pending", "applying"]))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_user(
        self,
        user_id: UUID,
        note_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[NoteEditProposal], int]:
        conditions = [NoteEditProposal.creator_id == str(user_id), NoteEditProposal.creator_type == "USER"]
        if note_id:
            conditions.append(NoteEditProposal.note_id == note_id)
        if status:
            conditions.append(NoteEditProposal.status == status)

        count_stmt = select(func.count()).select_from(NoteEditProposal).where(*conditions)
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(NoteEditProposal)
            .where(*conditions)
            .order_by(NoteEditProposal.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def transition_status(
        self, proposal_id: UUID, from_status: str, to_status: str
    ) -> bool:
        stmt = (
            update(NoteEditProposal)
            .where(
                NoteEditProposal.id == proposal_id,
                NoteEditProposal.status == from_status,
            )
            .values(status=to_status, updated_at=func.now())
            .returning(NoteEditProposal.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def set_approved(
        self, proposal_id: UUID, approved_by: UUID
    ) -> bool:
        stmt = (
            update(NoteEditProposal)
            .where(NoteEditProposal.id == proposal_id)
            .values(
                status="approved",
                approved_by=approved_by,
                approved_at=func.now(),
                updated_at=func.now(),
            )
            .returning(NoteEditProposal.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def set_rejected(
        self, proposal_id: UUID, rejected_by: UUID
    ) -> bool:
        stmt = (
            update(NoteEditProposal)
            .where(NoteEditProposal.id == proposal_id)
            .values(
                status="rejected",
                rejected_by=rejected_by,
                rejected_at=func.now(),
                updated_at=func.now(),
            )
            .returning(NoteEditProposal.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def supersede_older_pending(
        self, note_id: UUID, except_id: UUID | None = None
    ) -> int:
        stmt = (
            update(NoteEditProposal)
            .where(
                NoteEditProposal.note_id == note_id,
                NoteEditProposal.status == "pending",
            )
        )
        if except_id:
            stmt = stmt.where(NoteEditProposal.id != except_id)
        stmt = stmt.values(status="superseded", updated_at=func.now())
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def touch_last_viewed(self, proposal_id: UUID) -> None:
        stmt = (
            update(NoteEditProposal)
            .where(NoteEditProposal.id == proposal_id)
            .values(
                last_viewed_at=func.now(),
                expires_at=func.now() + timedelta(hours=24),
                updated_at=func.now(),
            )
        )
        await self.session.execute(stmt)

    async def expire_stale(self) -> int:
        stmt = (
            update(NoteEditProposal)
            .where(
                NoteEditProposal.status == "pending",
                NoteEditProposal.expires_at < func.now(),
            )
            .values(status="expired", updated_at=func.now())
            .returning(NoteEditProposal.id)
        )
        result = await self.session.execute(stmt)
        return len(result.all())
