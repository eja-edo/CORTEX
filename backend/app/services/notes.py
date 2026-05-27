from typing import Any
from datetime import datetime
from uuid import UUID

import bleach
from markdown_it import MarkdownIt
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models import Note
from app.repositories.notes import NoteRepository
from app.schemas import NoteCreate, NotePatchRequest, NoteResponse, NoteUpdate
from app.services.workspace_permission import WorkspacePermission
from app.utils.note_delta import apply_text_patch, build_text_patch

PATCH_COMPACTION_THRESHOLD = 20

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
        # Check user has write permission in the workspace
        with SessionLocal() as sync_db:
            member = WorkspacePermission.require_member(payload.workspace_id, user_id, sync_db)
            WorkspacePermission.require_editor(member)

        if payload.parent_note_id is not None:
            parent = await self.repository.get_active_by_id_and_user(payload.parent_note_id, user_id)
            if parent is None:
                raise ValueError("Parent note not found")

        note = Note(
            user_id=user_id,
            workspace_id=payload.workspace_id,
            parent_note_id=payload.parent_note_id,
            content=payload.content,
            content_type=payload.content_type,
            position=payload.position,
            size=payload.size,
            style=payload.style,
            checkpoint_version=1,
        )
        try:
            created = await self.repository.create(note)
            await self.session.commit()
            return created
        except Exception:
            await self.session.rollback()
            raise

    async def get_notes(self, user_id: UUID) -> list[Note]:
        notes = await self.repository.list_active_by_user(user_id)
        return list(notes)

    async def get_notes_by_workspace(self, workspace_id: UUID) -> list[Note]:
        """Get all active notes in a workspace."""
        notes = await self.repository.list_active_by_workspace(workspace_id)
        return list(notes)

    async def get_note(self, note_id: UUID, user_id: UUID) -> Note | None:
        return await self.repository.get_active_by_id_and_user(note_id, user_id)

    async def update_note(self, note_id: UUID, user_id: UUID, payload: NoteUpdate) -> Note | None:
        current_note = await self.repository.get_active_by_id_and_user(note_id, user_id)
        if current_note is None:
            return None

        update_payload = payload.model_dump(exclude_unset=True, exclude={"version"})
        if "parent_note_id" in update_payload:
            await self._validate_parent_assignment(
                note_id=note_id,
                user_id=user_id,
                parent_note_id=update_payload["parent_note_id"],
            )
            if update_payload["parent_note_id"] == current_note.parent_note_id:
                update_payload.pop("parent_note_id")

        content = update_payload.pop("content", None)

        if content is None:
            if not update_payload:
                return current_note

            # Metadata-only update (parent_note_id, position, size, style) - no version check needed
            normalized_updates = self._normalize_partial_updates(current_note, update_payload)
            updated = await self.repository.update_metadata(
                note_id=note_id,
                user_id=user_id,
                updates=normalized_updates,
            )
            await self.session.commit()
            return updated

        current_content = await self._materialize_note_content(current_note)
        patch_ops = build_text_patch(current_content, content)
        metadata_updates = self._normalize_partial_updates(current_note, update_payload) if update_payload else {}

        if not patch_ops and not metadata_updates:
            return current_note

        updated = await self.repository.update_with_version(
            note_id=note_id,
            user_id=user_id,
            expected_version=payload.version,
            updates=metadata_updates,
        )
        if updated is None:
            return None

        if patch_ops:
            new_version = payload.version + 1
            await self.repository.create_revision(
                note_id=note_id,
                user_id=user_id,
                version=new_version,
                base_version=current_note.version,
                patch=patch_ops,
                patch_format="text_diff",
                content_length=len(content),
            )

            if self._should_compact(current_note.checkpoint_version, new_version):
                await self._compact_checkpoint(note_id=note_id, user_id=user_id, full_content=content, version=new_version)

        await self.session.commit()
        return await self.repository.get_active_by_id_and_user(note_id, user_id)

    async def patch_note(self, note_id: UUID, user_id: UUID, payload: NotePatchRequest) -> Note | None:
        current_note = await self.repository.get_active_by_id_and_user(note_id, user_id)
        if current_note is None:
            return None

        current_content = await self._materialize_note_content(current_note)
        new_content = apply_text_patch(current_content, [op.model_dump() for op in payload.patch])
        metadata_updates = self._normalize_partial_updates(current_note, {
            key: value for key, value in {
                "position": payload.position,
                "size": payload.size,
                "style": payload.style,
            }.items() if value is not None
        })

        if new_content == current_content and not metadata_updates:
            return current_note

        updated = await self.repository.update_with_version(
            note_id=note_id,
            user_id=user_id,
            expected_version=payload.version,
            updates=metadata_updates,
        )
        if updated is None:
            return None

        new_version = payload.version + 1
        await self.repository.create_revision(
            note_id=note_id,
            user_id=user_id,
            version=new_version,
            base_version=current_note.version,
            patch=[op.model_dump() for op in payload.patch],
            patch_format="text_patch_ops",
            content_length=len(new_content),
        )

        if self._should_compact(current_note.checkpoint_version, new_version):
            await self._compact_checkpoint(note_id=note_id, user_id=user_id, full_content=new_content, version=new_version)


        await self.session.commit()
        return await self.repository.get_active_by_id_and_user(note_id, user_id)

    async def soft_delete(self, note_id: UUID, user_id: UUID) -> bool:
        async with self.session.begin():
            notes = await self.repository.list_active_by_user(user_id)
            children_by_parent: dict[UUID | None, list[UUID]] = {}
            for note in notes:
                children_by_parent.setdefault(note.parent_note_id, []).append(note.id)

            to_delete: list[UUID] = []
            stack = [note_id]
            seen: set[UUID] = set()
            while stack:
                current_id = stack.pop()
                if current_id in seen:
                    continue
                seen.add(current_id)
                to_delete.append(current_id)
                stack.extend(children_by_parent.get(current_id, []))

            deleted_any = False
            for target_id in to_delete:
                deleted_any = await self.repository.soft_delete(target_id, user_id) or deleted_any
            return deleted_any

    async def materialize_note_content(self, note: Note) -> str:
        return await self._materialize_note_content(note)

    async def list_revisions(self, note_id: UUID, user_id: UUID, limit: int = 100):
        return await self.repository.list_revisions(note_id=note_id, user_id=user_id, limit=limit)

    def to_response(self, note: Note, render_html: bool = False, content_override: str | None = None) -> NoteResponse:
        content = content_override if content_override is not None else note.content
        rendered_html = None
        if render_html:
            rendered_html = self._render_markdown_html(content)

        return NoteResponse(
            id=note.id,
            user_id=note.user_id,
            workspace_id=note.workspace_id,
            parent_note_id=getattr(note, "parent_note_id", None),
            content=content,
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

    async def _materialize_note_content(self, note: Note) -> str:
        revisions = await self.repository.list_revisions_since_checkpoint(note.id, note.checkpoint_version)
        content = note.content
        for revision in revisions:
            content = apply_text_patch(content, revision.patch)
        return content

    def _should_compact(self, checkpoint_version: int, current_version: int) -> bool:
        return (current_version - checkpoint_version) >= PATCH_COMPACTION_THRESHOLD

    async def _compact_checkpoint(self, note_id: UUID, user_id: UUID, full_content: str, version: int) -> None:
        note = await self.repository.get_active_by_id_and_user(note_id, user_id)
        if note is None:
            return

        note.content = full_content
        note.checkpoint_version = version
        note.updated_at = datetime.utcnow()
        await self.session.flush()
        await self.repository.delete_revisions_up_to(note_id, version)

    async def _validate_parent_assignment(self, *, note_id: UUID, user_id: UUID, parent_note_id: UUID | None) -> None:
        if parent_note_id is None:
            return

        if parent_note_id == note_id:
            raise ValueError("Cannot set note as its own parent")

        parent_note = await self.repository.get_active_by_id_and_user(parent_note_id, user_id)
        if parent_note is None:
            raise ValueError("Parent note not found")

        notes = await self.repository.list_active_by_user(user_id)
        children_by_parent: dict[UUID | None, list[UUID]] = {}
        for note in notes:
            children_by_parent.setdefault(note.parent_note_id, []).append(note.id)

        stack = [note_id]
        seen: set[UUID] = set()
        while stack:
            current_id = stack.pop()
            if current_id in seen:
                continue
            seen.add(current_id)
            if current_id == parent_note_id:
                raise ValueError("Cannot move note under its descendant")
            stack.extend(children_by_parent.get(current_id, []))

    def _render_markdown_html(self, markdown_content: str) -> str:
        unsafe_html = self.markdown.render(markdown_content)
        return bleach.clean(
            unsafe_html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRIBUTES,
            strip=True,
        )
