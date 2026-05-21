from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.schemas import NoteUpdate
from app.services.notes import NoteService


class FakeSession:
    async def commit(self) -> None:
        return None

    async def flush(self) -> None:
        return None


class FakeRepo:
    def __init__(self, notes: list[SimpleNamespace]) -> None:
        self.notes_by_id = {note.id: note for note in notes}

    async def get_active_by_id_and_user(self, note_id: UUID, user_id: UUID) -> SimpleNamespace | None:
        note = self.notes_by_id.get(note_id)
        if note is None or note.user_id != user_id:
            return None
        return note

    async def list_active_by_user(self, user_id: UUID) -> list[SimpleNamespace]:
        return [note for note in self.notes_by_id.values() if note.user_id == user_id]

    async def update_metadata(self, note_id: UUID, user_id: UUID, updates: dict) -> SimpleNamespace | None:
        note = await self.get_active_by_id_and_user(note_id, user_id)
        if note is None:
            return None

        for key, value in updates.items():
            setattr(note, key, value)
        return note

    async def update_with_version(self, note_id: UUID, user_id: UUID, expected_version: int, updates: dict) -> SimpleNamespace | None:
        note = await self.get_active_by_id_and_user(note_id, user_id)
        if note is None or note.version != expected_version:
            return None

        for key, value in updates.items():
            setattr(note, key, value)
        note.version += 1
        return note

    async def create_revision(self, **kwargs):
        return SimpleNamespace(**kwargs)

    async def list_revisions_since_checkpoint(self, note_id: UUID, checkpoint_version: int) -> list:
        return []

    async def delete_revisions_up_to(self, note_id: UUID, version: int) -> int:
        return 0


def make_note(*, note_id: UUID, user_id: UUID, parent_note_id: UUID | None = None, version: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=note_id,
        user_id=user_id,
        parent_note_id=parent_note_id,
        content="Note content",
        content_type="markdown",
        position={"x": 0, "y": 0},
        size={"width": 200, "height": 160},
        style={"color": "#000"},
        checkpoint_version=1,
        version=version,
        is_deleted=False,
        updated_at=None,
    )


@pytest.mark.asyncio
async def test_move_note_does_not_increment_version_and_can_move_again() -> None:
    user_id = uuid4()
    note_id = uuid4()
    parent_a_id = uuid4()
    parent_b_id = uuid4()
    parent_c_id = uuid4()

    notes = [
        make_note(note_id=parent_a_id, user_id=user_id),
        make_note(note_id=parent_b_id, user_id=user_id),
        make_note(note_id=parent_c_id, user_id=user_id),
        make_note(note_id=note_id, user_id=user_id, parent_note_id=parent_a_id, version=1),
    ]
    service = NoteService(FakeSession())
    service.repository = FakeRepo(notes)  # type: ignore[assignment]

    first_move = await service.update_note(
        note_id=note_id,
        user_id=user_id,
        payload=NoteUpdate(version=1, parent_note_id=parent_b_id),
    )
    assert first_move is not None
    assert first_move.version == 1
    assert first_move.parent_note_id == parent_b_id

    second_move = await service.update_note(
        note_id=note_id,
        user_id=user_id,
        payload=NoteUpdate(version=1, parent_note_id=parent_c_id),
    )
    assert second_move is not None
    assert second_move.version == 1
    assert second_move.parent_note_id == parent_c_id


@pytest.mark.asyncio
async def test_move_note_rejects_self_parent() -> None:
    user_id = uuid4()
    note_id = uuid4()
    note = make_note(note_id=note_id, user_id=user_id)

    service = NoteService(FakeSession())
    service.repository = FakeRepo([note])  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Cannot set note as its own parent"):
        await service.update_note(
            note_id=note_id,
            user_id=user_id,
            payload=NoteUpdate(version=1, parent_note_id=note_id),
        )