"""Update note tool that accepts full content and builds a patch server-side."""

from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas import MAX_NOTE_CONTENT_LENGTH, NotePatchRequest
from app.services.agent.tool_context import ToolContext
from app.services.notes import NoteService
from app.utils.logger import get_logger
from app.utils.note_delta import build_text_patch

logger = get_logger(__name__)


class UpdateNoteInput(BaseModel):
    """Validation model for update_note tool."""
    note_id: str = Field(..., description="Note UUID to update")
    content: str = Field(
        ..., min_length=1, max_length=MAX_NOTE_CONTENT_LENGTH, description="Full note content (markdown)"
    )


async def update_note_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Update a note by sending full content; server computes patch.

    Security:
    - Note must belong to ctx.user_id
    """
    try:
        note_id = UUID(args["note_id"])
    except ValueError:
        raise ValueError(f"Invalid note_id: {args['note_id']}")

    content = args["content"]

    try:
        async with ctx.async_db() as async_db:
            service = NoteService(async_db)
            current = await service.get_note(note_id=note_id, user_id=ctx.user_id)
            if current is None:
                raise ValueError("Note not found")

            current_content = await service.materialize_note_content(current)
            if current_content == content:
                return {
                    "id": str(current.id),
                    "version": current.version,
                    "updated": False,
                    "success": True,
                }

            patch = build_text_patch(current_content, content)
            if not patch:
                return {
                    "id": str(current.id),
                    "version": current.version,
                    "updated": False,
                    "success": True,
                }

            payload = NotePatchRequest(version=current.version, patch=patch)
            updated = await service.patch_note(note_id=note_id, user_id=ctx.user_id, payload=payload)
            if updated is None:
                raise ValueError("Version conflict, please retry")

            return {
                "id": str(updated.id),
                "version": updated.version,
                "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
                "updated": True,
                "success": True,
            }

    except Exception as exc:
        logger.error("update_note failed: %s", exc, exc_info=True)
        raise


UPDATE_NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "note_id": {
            "type": "string",
            "description": "UUID of note to update",
        },
        "content": {
            "type": "string",
            "description": "Full note content in markdown",
        },
    },
    "required": ["note_id", "content"],
}

UPDATE_NOTE_DEFINITION = {
    "name": "update_note",
    "handler": update_note_handler,
    "input_model": UpdateNoteInput,
    "schema": UPDATE_NOTE_SCHEMA,
    "description": "Update a note by providing full markdown content; server computes patch and saves.",
}
