"""Update note tool — thin wrapper around the note.update command (which
creates a reviewable proposal instead of applying directly)."""

from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas import MAX_NOTE_CONTENT_LENGTH
from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

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
    - Note must belong to ctx.user_id (note.update has no workspace_id on
      its Command — see app/commands/registry.py::_check_permission's
      ownership-only branch; matches this tool's pre-migration behavior,
      which never gated on workspace role either).
    """
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    try:
        note_id = UUID(args["note_id"])
    except ValueError:
        raise ValueError(f"Invalid note_id: {args['note_id']}")

    content = args["content"]

    # No version pre-fetch: NoteUpdateArgs.version is optional and unused by
    # note_update_handler (the Proposal flow has no in-place write to
    # optimistic-lock against) — see app/commands/args.py. Fetching the note
    # here would just be a redundant read; note_update_handler does its own
    # lookup anyway (and raises "Note not found" the same way).
    command = Command(
        command_name="note.update",
        args={"note_id": str(note_id), "content": content},
        requested_by=ctx.user_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )

    result = await get_command_registry().execute(command, ctx)

    if not result.success:
        raise ValueError(result.error)

    return {**result.data, "success": True}


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
