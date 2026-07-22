"""Create note tool."""

from uuid import UUID
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import Note
from app.ai.agents.action_snapshot_store import ActionSnapshot, get_snapshot_store
from app.ai.agents.tool_context import ToolContext
from app.services.notes import NoteService
from app.services.workspace_permission import WorkspacePermission
from app.schemas import NoteCreate
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CreateNoteInput(BaseModel):
    """Validation model for create_note tool."""
    content: str = Field(..., min_length=1, max_length=50000, description="Note content (markdown)")
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
    style_color = args.get("style_color", "yellow")

    workspace_id = ctx.workspace_id
    if workspace_id is None:
        raise ValueError("workspace_id is required but not available in context")

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

            # --- REVERT SNAPSHOT ---
            snapshot = ActionSnapshot(
                tool_name="create_note",
                user_id=str(ctx.user_id),
                conversation_id=str(getattr(ctx, "conversation_id", "")),
                snapshot={
                    "op": "create_note",
                    "note_id": str(note.id),
                    "workspace_id": str(note.workspace_id),
                },
            )
            action_id = await get_snapshot_store().save(snapshot)
            # -----------------------

            return {
                "id": str(note.id),
                "workspace_id": str(note.workspace_id),
                "created_at": note.created_at.isoformat(),
                "action_id": action_id,
                "revert_hint": "Bạn có thể yêu cầu hoàn tác hành động này bằng action_id trên.",
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
        "style_color": {
            "type": "string",
            "enum": ["yellow", "blue", "green", "pink", "purple"],
            "default": "yellow",
            "description": "Color of the note",
        },
    },
    "required": ["content"],
}

CREATE_NOTE_DEFINITION = {
    "name": "create_note",
    "handler": create_note_handler,
    "input_model": CreateNoteInput,
    "schema": CREATE_NOTE_SCHEMA,
    "description": "Create a new note in the current workspace.",
}
