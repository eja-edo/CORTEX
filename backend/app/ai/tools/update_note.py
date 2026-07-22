"""Update note tool that creates a reviewable proposal instead of applying directly."""

from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas import MAX_NOTE_CONTENT_LENGTH
from app.ai.agents.tool_context import ToolContext
from app.services.notes import NoteService
from app.services.proposal_service import ProposalService
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
    Update a note by creating a proposal. The proposal must be approved
    before changes are applied to the note.

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
            note_service = NoteService(async_db)
            proposal_service = ProposalService(async_db)

            current = await note_service.get_note(note_id=note_id, user_id=ctx.user_id)
            if current is None:
                raise ValueError("Note not found")

            current_content = await note_service.materialize_note_content(current)
            if current_content == content:
                return {
                    "id": str(current.id),
                    "version": current.version,
                    "proposal_id": None,
                    "updated": False,
                    "success": True,
                }

            patch = build_text_patch(current_content, content)
            if not patch:
                return {
                    "id": str(current.id),
                    "version": current.version,
                    "proposal_id": None,
                    "updated": False,
                    "success": True,
                }

            # Create a proposal instead of applying directly
            proposal = await proposal_service.create_proposal(
                note=current,
                user_id=ctx.user_id,
                old_content=current_content,
                new_content=content,
                patch=patch,
                creator_type="AGENT",
                creator_id=f"agent:{ctx.user_id}",
                conversation_id=getattr(ctx, "conversation_id", None),
            )

            logger.info(
                f"update_note: created proposal {proposal.id} for note {current.id} "
                f"(version={current.version})"
            )
            return {
                "id": str(current.id),
                "version": current.version,
                "proposal_id": str(proposal.id),
                "updated": False,
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
    "description": "Update a note by providing full markdown content; server computes patch and creates a reviewable proposal (approval required before changes take effect).",
}
