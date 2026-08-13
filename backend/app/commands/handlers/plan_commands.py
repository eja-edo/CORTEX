"""
Plan command handlers (3.2 AI Planner).

`plan.propose` mirrors `note.update`'s shape exactly: the handler doesn't
create any Task/Schedule rows — it stores a reviewable proposal via
PlanProposalService and returns its id. Nothing changes until the user
approves via POST /plan-proposals/{id}/approve, which replays the stored
items through the existing task.create/schedule.create commands.
"""

from app.commands.args import PlanProposeArgs
from app.commands.schemas import Command, PermissionScope
from app.ai.agents.tool_context import ToolContext
from app.services.plan_proposal_service import PlanProposalService
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def plan_propose_handler(command: Command, ctx: ToolContext) -> dict:
    """Create plan proposal command handler. Does NOT create tasks/events —
    creates a reviewable PlanProposal, pending user approval (matches
    app/commands/handlers/note_commands.py::note_update_handler's
    behavior). No `prev_state`: nothing has changed yet, so nothing to
    revert — this command is registered with revertable=False."""
    args = PlanProposeArgs(**command.args)

    async with ctx.async_db() as db:
        service = PlanProposalService(db)
        proposal = await service.create_proposal(
            user_id=ctx.user_id,
            items=[item.model_dump(mode="json") for item in args.items],
            creator_type="AGENT",
            creator_id=f"agent:{ctx.user_id}",
            conversation_id=command.conversation_id,
        )

        logger.info(f"plan.propose: created proposal {proposal.id} ({len(args.items)} items)")

        return {
            "proposal_id": str(proposal.id),
            "item_count": len(args.items),
            "status": proposal.status,
        }


def register_plan_commands() -> None:
    """Register all plan commands with the global CommandRegistry."""
    from app.commands.registry import get_command_registry

    registry = get_command_registry()

    registry.register(
        name="plan.propose",
        description="Propose a structured set of tasks/events for user review (not yet created — approval required)",
        args_schema=PlanProposeArgs,
        handler=plan_propose_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=False,  # creates a Proposal — nothing to restore, see docstring
    )
