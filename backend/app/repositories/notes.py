from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note


class NoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, note: Note) -> Note:
        self.session.add(note)
        await self.session.flush()
        await self.session.refresh(note)
        return note

    async def list_active_by_user(self, user_id: UUID) -> Sequence[Note]:
        stmt = (
            select(Note)
            .where(Note.user_id == user_id, Note.is_deleted.is_(False))
            .order_by(Note.updated_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_active_by_id_and_user(self, note_id: UUID, user_id: UUID) -> Note | None:
        stmt = select(Note).where(
            Note.id == note_id,
            Note.user_id == user_id,
            Note.is_deleted.is_(False),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_with_version(
        self,
        note_id: UUID,
        user_id: UUID,
        expected_version: int,
        updates: dict,
    ) -> Note | None:
        values = {
            **updates,
            "version": Note.version + 1,
            "updated_at": func.now(),
        }

        stmt = (
            update(Note)
            .where(
                Note.id == note_id,
                Note.user_id == user_id,
                Note.is_deleted.is_(False),
                Note.version == expected_version,
            )
            .values(**values)
            .returning(Note.id)
        )
        result = await self.session.execute(stmt)
        updated_id = result.scalar_one_or_none()
        if updated_id is None:
            return None

        return await self.get_active_by_id_and_user(updated_id, user_id)

    async def soft_delete(self, note_id: UUID, user_id: UUID) -> bool:
        stmt = (
            update(Note)
            .where(Note.id == note_id, Note.user_id == user_id, Note.is_deleted.is_(False))
            .values(is_deleted=True, updated_at=func.now())
            .returning(Note.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
