from typing import Any
from uuid import UUID

import bleach
from markdown_it import MarkdownIt
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note
from app.repositories.notes import NoteRepository
from app.schemas import BatchUpdateItem, BatchUpdateResponse, NoteCreate, NoteResponse, NoteUpdate

_ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "p",
    "pre",
    "code",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "blockquote",
    "hr",
    "br",
    "span",
]
_ALLOWED_ATTRIBUTES = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "a": ["href", "title", "target", "rel"],
    "span": ["class"],
    "code": ["class"],
}


class NoteService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = NoteRepository(session)
        self.markdown = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True})

    async def create_note(self, payload: NoteCreate, user_id: UUID) -> Note:
        note = Note(
            user_id=user_id,
            content=payload.content,
            content_type=payload.content_type,
            position=payload.position,
            size=payload.size,
            style=payload.style,
        )
        async with self.session.begin():
            return await self.repository.create(note)

    async def get_notes(self, user_id: UUID) -> list[Note]:
        notes = await self.repository.list_active_by_user(user_id)
        return list(notes)

    async def get_note(self, note_id: UUID, user_id: UUID) -> Note | None:
        return await self.repository.get_active_by_id_and_user(note_id, user_id)

    async def update_note(self, note_id: UUID, user_id: UUID, payload: NoteUpdate) -> Note | None:
        partial_updates = payload.model_dump(exclude_unset=True, exclude={"version"})
        if not partial_updates:
            return await self.repository.get_active_by_id_and_user(note_id, user_id)

        current_note = await self.repository.get_active_by_id_and_user(note_id, user_id)
        if current_note is None:
            return None

        normalized_updates = self._normalize_partial_updates(current_note, partial_updates)
        updated = await self.repository.update_with_version(
            note_id=note_id,
            user_id=user_id,
            expected_version=payload.version,
            updates=normalized_updates,
        )
        await self.session.commit()
        return updated

    async def soft_delete(self, note_id: UUID, user_id: UUID) -> bool:
        async with self.session.begin():
            return await self.repository.soft_delete(note_id, user_id)

    async def batch_update(self, user_id: UUID, items: list[BatchUpdateItem]) -> BatchUpdateResponse:
        success: list[UUID] = []
        failed: list[UUID] = []

        async with self.session.begin():
            for item in items:
                existing = await self.repository.get_active_by_id_and_user(item.id, user_id)
                if existing is None:
                    failed.append(item.id)
                    continue

                update_payload = item.updates.model_dump(exclude_unset=True)
                if not update_payload:
                    success.append(item.id)
                    continue

                normalized_updates = self._normalize_partial_updates(existing, update_payload)
                updated = await self.repository.update_with_version(
                    note_id=item.id,
                    user_id=user_id,
                    expected_version=item.version,
                    updates=normalized_updates,
                )
                if updated is None:
                    failed.append(item.id)
                else:
                    success.append(item.id)

        return BatchUpdateResponse(success=success, failed=failed)

    def to_response(self, note: Note, render_html: bool = False) -> NoteResponse:
        rendered_html = None
        if render_html:
            rendered_html = self._render_markdown_html(note.content)

        return NoteResponse(
            id=note.id,
            user_id=note.user_id,
            content=note.content,
            content_type=note.content_type,
            position=note.position,
            size=note.size,
            style=note.style,
            version=note.version,
            is_deleted=note.is_deleted,
            created_at=note.created_at,
            updated_at=note.updated_at,
            rendered_html=rendered_html,
        )

    def _normalize_partial_updates(self, current: Note, updates: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(updates)

        for json_key in ("position", "size", "style"):
            if json_key in normalized and normalized[json_key] is not None:
                existing = getattr(current, json_key) or {}
                normalized[json_key] = {**existing, **normalized[json_key]}

        return normalized

    def _render_markdown_html(self, markdown_content: str) -> str:
        unsafe_html = self.markdown.render(markdown_content)
        return bleach.clean(
            unsafe_html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRIBUTES,
            strip=True,
        )
