"""
Note command handlers.

These are the actual implementations invoked by CommandRegistry. Tool
handlers in app/ai/tools/ are thin wrappers that build a Command and call
CommandRegistry.execute() — see app/ai/tools/create_note.py / update_note.py.
"""

from uuid import UUID

from app.commands.args import NoteCreateArgs, NoteDeleteArgs, NoteUpdateArgs
from app.commands.schemas import Command, PermissionScope
from app.ai.agents.tool_context import ToolContext
from app.schemas import NoteCreate
from app.services.notes import NoteService
from app.services.proposal_service import ProposalService
from app.utils.logger import get_logger
from app.utils.note_delta import build_text_patch

logger = get_logger(__name__)


async def note_create_handler(command: Command, ctx: ToolContext) -> dict:
    """Create note command handler. Called by CommandRegistry after
    validation/permission checks (WRITE scope + workspace_id → editor
    check)."""
    args = NoteCreateArgs(**command.args)

    async with ctx.async_db() as db:
        service = NoteService(db)
        note = await service.create_note(
            payload=NoteCreate(
                workspace_id=args.workspace_id,
                title=args.title,
                content=args.content,
                parent_note_id=args.parent_note_id,
                content_type=args.content_type,
                **({"style": args.style} if args.style is not None else {}),
            ),
            user_id=ctx.user_id,
        )

        logger.info(f"Note created: {note.id}")

        return {
            "id": str(note.id),
            "workspace_id": str(note.workspace_id),
            "title": note.title,
            "created_at": note.created_at.isoformat() if note.created_at else None,
            "prev_state": {"note_id": str(note.id)},  # For revert (soft delete)
        }


async def note_update_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Update note command handler.

    Does NOT apply changes directly — creates a reviewable Proposal via
    ProposalService, pending user approval (matches the existing
    app/ai/tools/update_note.py behavior). No `prev_state`: nothing has
    changed yet, so nothing to revert — this command is registered with
    revertable=False.
    """
    args = NoteUpdateArgs(**command.args)

    async with ctx.async_db() as db:
        note_service = NoteService(db)
        proposal_service = ProposalService(db)

        current = await note_service.get_note(args.note_id, ctx.user_id)
        if current is None:
            raise ValueError("Note not found")

        current_content = await note_service.materialize_note_content(current)
        if args.content is None or current_content == args.content:
            return {
                "id": str(current.id),
                "version": current.version,
                "proposal_id": None,
                "updated": False,
            }

        patch = build_text_patch(current_content, args.content)
        if not patch:
            return {
                "id": str(current.id),
                "version": current.version,
                "proposal_id": None,
                "updated": False,
            }

        proposal = await proposal_service.create_proposal(
            note=current,
            user_id=ctx.user_id,
            old_content=current_content,
            new_content=args.content,
            patch=patch,
            creator_type="AGENT",
            creator_id=f"agent:{ctx.user_id}",
            conversation_id=command.conversation_id,
        )

        logger.info(
            f"note.update: created proposal {proposal.id} for note {current.id} "
            f"(version={current.version})"
        )

        return {
            "id": str(current.id),
            "version": current.version,
            "proposal_id": str(proposal.id),
            "updated": False,
        }


async def note_delete_handler(command: Command, ctx: ToolContext) -> dict:
    """Delete note command handler (soft delete). No AI tool exposes this
    directly yet — registered for completeness/future use (e.g. a future
    `delete_note` tool, or workflow actions)."""
    args = NoteDeleteArgs(**command.args)

    async with ctx.async_db() as db:
        service = NoteService(db)

        note = await service.get_note(args.note_id, ctx.user_id)
        if not note:
            raise ValueError(f"Note not found: {args.note_id}")

        prev_state = {
            "note_id": str(args.note_id),
            "title": note.title,
            "content": await service.materialize_note_content(note),
        }

        success = await service.soft_delete(args.note_id, ctx.user_id)
        if not success:
            raise ValueError("Delete failed")

        logger.info(f"Note deleted: {args.note_id}")

        return {
            "note_id": str(args.note_id),
            "deleted": True,
            "prev_state": prev_state,
        }


def register_note_commands() -> None:
    """Register all note commands with the global CommandRegistry."""
    from app.commands.registry import get_command_registry

    registry = get_command_registry()

    registry.register(
        name="note.create",
        description="Create a new note in workspace",
        args_schema=NoteCreateArgs,
        handler=note_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
    )

    registry.register(
        name="note.update",
        description="Propose an update to an existing note (pending approval, not applied immediately)",
        args_schema=NoteUpdateArgs,
        handler=note_update_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=False,  # creates a Proposal — nothing to restore, see docstring
    )

    registry.register(
        name="note.delete",
        description="Delete note (soft delete)",
        args_schema=NoteDeleteArgs,
        handler=note_delete_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
    )

    logger.info("Note commands registered")
