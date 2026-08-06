"""Create note tool — thin wrapper around the note.create command."""

from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
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
    - Workspace editor check + user_id are enforced by CommandRegistry
      (WRITE scope + Command.workspace_id → WorkspacePermission), not
      manually here — see app/commands/registry.py::_check_permission.
    - user_id comes from ctx (never from args)
    """
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    content = args["content"]
    style_color = args.get("style_color", "yellow")

    workspace_id = ctx.workspace_id
    if workspace_id is None:
        raise ValueError("workspace_id is required but not available in context")

    command = Command(
        command_name="note.create",
        args={
            "workspace_id": str(workspace_id),
            "content": content,
            "style": {"color": style_color},
        },
        requested_by=ctx.user_id,
        workspace_id=workspace_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )

    result = await get_command_registry().execute(command, ctx)

    if not result.success:
        if result.error and "Permission denied" in result.error:
            raise PermissionError(result.error)
        raise ValueError(result.error)

    return {
        "id": result.data["id"],
        "workspace_id": result.data["workspace_id"],
        "created_at": result.data["created_at"],
        "action_id": result.action_id,
        "revert_hint": "Bạn có thể yêu cầu hoàn tác hành động này bằng action_id trên.",
        "success": True,
    }


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
