from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note, NoteRevision


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

    async def list_active_by_project(self, project_id: UUID, user_id: UUID) -> Sequence[Note]:
        """Ghi chú đang sống trong một dự án, của một người.

        Lọc theo `user_id` là bắt buộc, không phải thừa: dự án là thực thể
        **dùng chung** (QĐ-1), nên "ghi chú trong dự án này" không đồng
        nghĩa với "ghi chú của tôi" — bỏ bộ lọc đi là lộ ghi chú của người
        khác ngay khi có thành viên thứ hai.
        """
        stmt = (
            select(Note)
            .where(
                Note.project_id == project_id,
                Note.user_id == user_id,
                Note.is_deleted.is_(False),
            )
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

    async def update_metadata(
        self,
        note_id: UUID,
        user_id: UUID,
        updates: dict,
    ) -> Note | None:
        """Update metadata (parent_note_id, position, size, style) without version check.
        """
        if not updates:
            return await self.get_active_by_id_and_user(note_id, user_id)

        values = {
            **updates,
            "updated_at": func.now(),
        }

        stmt = (
            update(Note)
            .where(
                Note.id == note_id,
                Note.user_id == user_id,
                Note.is_deleted.is_(False),
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

    async def create_revision(
        self,
        *,
        note_id: UUID,
        user_id: UUID,
        version: int,
        base_version: int,
        patch: list,
        patch_format: str,
        content_length: int,
    ) -> NoteRevision:
        revision = NoteRevision(
            note_id=note_id,
            user_id=user_id,
            version=version,
            base_version=base_version,
            patch=patch,
            patch_format=patch_format,
            content_length=content_length,
        )
        self.session.add(revision)
        await self.session.flush()
        await self.session.refresh(revision)
        return revision

    async def list_revisions_since_checkpoint(self, note_id: UUID, checkpoint_version: int) -> list[NoteRevision]:
        stmt = (
            select(NoteRevision)
            .where(NoteRevision.note_id == note_id, NoteRevision.version > checkpoint_version)
            .order_by(NoteRevision.version.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_revisions_up_to(self, note_id: UUID, version: int) -> int:
        stmt = delete(NoteRevision).where(NoteRevision.note_id == note_id, NoteRevision.version <= version)
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def list_revisions(self, note_id: UUID, user_id: UUID, limit: int = 100) -> list[NoteRevision]:
        stmt = (
            select(NoteRevision)
            .where(NoteRevision.note_id == note_id, NoteRevision.user_id == user_id)
            .order_by(NoteRevision.version.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
