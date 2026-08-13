from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlanProposal


class PlanProposalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, proposal: PlanProposal) -> PlanProposal:
        self.session.add(proposal)
        await self.session.flush()
        await self.session.refresh(proposal)
        return proposal

    async def get_by_id(self, proposal_id: UUID) -> PlanProposal | None:
        stmt = select(PlanProposal).where(PlanProposal.id == proposal_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[PlanProposal], int]:
        conditions = [PlanProposal.user_id == user_id]
        if status:
            conditions.append(PlanProposal.status == status)

        count_stmt = select(func.count()).select_from(PlanProposal).where(*conditions)
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(PlanProposal)
            .where(*conditions)
            .order_by(PlanProposal.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def set_approved(self, proposal_id: UUID) -> bool:
        stmt = (
            update(PlanProposal)
            .where(PlanProposal.id == proposal_id)
            .values(status="approved", approved_at=func.now(), updated_at=func.now())
            .returning(PlanProposal.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def set_rejected(self, proposal_id: UUID) -> bool:
        stmt = (
            update(PlanProposal)
            .where(PlanProposal.id == proposal_id)
            .values(status="rejected", rejected_at=func.now(), updated_at=func.now())
            .returning(PlanProposal.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
