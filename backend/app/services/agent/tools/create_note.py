"""Create note tool."""

from uuid import UUID
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import Note
from app.services.agent.tool_context import ToolContext
from app.services.notes import NoteService
from app.services.workspace_permission import WorkspacePermission
from app.schemas import NoteCreate
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CreateNoteInput(BaseModel):
    """Validation model for create_note tool."""
    content: str = Field(..., min_length=1, max_length=50000, description="Note content (markdown)")
    workspace_id: str = Field(..., description="Workspace UUID where to create note")
    style_color: str = Field(
        default="yellow",
        pattern="^(yellow|blue|green|pink|purple)$",
        description="Note color"
    )


async def create_note_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Create a new note for the user.
    
    Security:
    - User must be editor in the workspace
    - user_id comes from ctx (never from args)
    """
    content = args["content"]
    workspace_id_str = args["workspace_id"]
    style_color = args.get("style_color", "yellow")

    try:
        workspace_id = UUID(workspace_id_str)
    except ValueError:
        raise ValueError(f"Invalid workspace_id format: {workspace_id_str}")

    # Check workspace permission (sync check)
    with ctx.get_sync_db() as sync_db:
        member = WorkspacePermission.require_member(workspace_id, ctx.user_id, sync_db)
        WorkspacePermission.require_editor(member)

    # Create note
    try:
        async with ctx.async_db() as async_db:
            service = NoteService(async_db)
            payload = NoteCreate(
                workspace_id=workspace_id,
                content=content,
                style={"color": style_color},
            )
            note = await service.create_note(payload, ctx.user_id)

            return {
                "id": str(note.id),
                "workspace_id": str(note.workspace_id),
                "created_at": note.created_at.isoformat(),
                "success": True,
            }

    except PermissionError as exc:
        raise PermissionError(f"Permission denied: {exc}")
    except Exception as exc:
        logger.error(f"create_note failed: {exc}", exc_info=True)
        raise


CREATE_NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": "Note content in markdown format",
        },
        "workspace_id": {
            "type": "string",
            "description": "UUID of the workspace to create note in",
        },
        "style_color": {
            "type": "string",
            "enum": ["yellow", "blue", "green", "pink", "purple"],
            "default": "yellow",
            "description": "Color of the note",
        },
    },
    "required": ["content", "workspace_id"],
}

CREATE_NOTE_DEFINITION = {
    "name": "create_note",
    "handler": create_note_handler,
    "input_model": CreateNoteInput,
    "schema": CREATE_NOTE_SCHEMA,
    "description": "Create a new note. User must be editor in the workspace.",
}
