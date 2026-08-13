from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.tool_context import ToolContext
from app.models import PlanProposal
from app.repositories.plan_proposals import PlanProposalRepository
from app.schemas import PlanProposalItemResult, PlanProposalResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

PLAN_PROPOSAL_TTL_HOURS = 24


class PlanProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PlanProposalRepository(session)

    async def create_proposal(
        self,
        *,
        user_id: UUID,
        items: list[dict],
        creator_type: str = "AGENT",
        creator_id: str | None = None,
        conversation_id: UUID | None = None,
    ) -> PlanProposal:
        proposal = PlanProposal(
            user_id=user_id,
            items=items,
            creator_type=creator_type,
            creator_id=creator_id or str(user_id),
            status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=PLAN_PROPOSAL_TTL_HOURS),
            conversation_id=conversation_id,
        )
        created = await self.repo.create(proposal)
        await self.session.commit()
        logger.info(f"Created plan proposal {created.id} for user {user_id} ({len(items)} items)")
        return created

    async def get_proposal(self, proposal_id: UUID, user_id: UUID) -> PlanProposal | None:
        proposal = await self.repo.get_by_id(proposal_id)
        if proposal is None or proposal.user_id != user_id:
            return None
        return proposal

    async def list_proposals(
        self, user_id: UUID, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[PlanProposal], int]:
        items, total = await self.repo.list_by_user(user_id=user_id, status=status, limit=limit, offset=offset)
        return list(items), total

    async def reject_proposal(self, proposal_id: UUID, user_id: UUID) -> PlanProposal:
        proposal = await self.repo.get_by_id(proposal_id)
        if proposal is None or proposal.user_id != user_id:
            raise ValueError("Proposal not found")

        if proposal.status == "rejected":
            return proposal
        if proposal.status == "approved":
            raise ValueError("Proposal has already been approved")
        if proposal.status == "expired":
            raise ValueError("Proposal has expired")

        await self.repo.set_rejected(proposal_id)
        await self.session.commit()
        logger.info(f"Rejected plan proposal {proposal_id}")
        return proposal

    async def approve_proposal(
        self,
        proposal_id: UUID,
        user_id: UUID,
        ctx: ToolContext,
        items_override: list[dict] | None,
    ) -> tuple[PlanProposal, list[PlanProposalItemResult]]:
        """Best-effort approval: each item is an independent task.create/
        schedule.create Command. One item failing has no bearing on whether
        another item should exist, so a failure doesn't abort the loop —
        it's recorded in the per-item results instead. Requires parent
        task items to appear before their children in the item list.
        """
        from app.commands.registry import get_command_registry
        from app.commands.schemas import Command

        proposal = await self.repo.get_by_id(proposal_id)
        if proposal is None or proposal.user_id != user_id:
            raise ValueError("Proposal not found")

        if proposal.status == "rejected":
            raise ValueError("Proposal has already been rejected")
        if proposal.status == "expired":
            raise ValueError("Proposal has expired")

        effective_items = items_override if items_override is not None else list(proposal.items)

        registry = get_command_registry()
        task_key_to_id: dict[str, str] = {}
        event_key_to_id: dict[str, str] = {}
        results: list[PlanProposalItemResult] = []

        for item in effective_items:
            key = item["key"]
            item_type = item["type"]
            try:
                if item_type == "task":
                    parent_task_id = None
                    parent_key = item.get("parent_key")
                    if parent_key:
                        if parent_key not in task_key_to_id:
                            results.append(PlanProposalItemResult(
                                key=key, type="task", outcome="failed",
                                error="parent task was not created",
                            ))
                            continue
                        parent_task_id = task_key_to_id[parent_key]

                    related_event_id = None
                    related_event_key = item.get("related_event_key")
                    if related_event_key:
                        if related_event_key not in event_key_to_id:
                            results.append(PlanProposalItemResult(
                                key=key, type="task", outcome="failed",
                                error="linked event was not created",
                            ))
                            continue
                        related_event_id = event_key_to_id[related_event_key]

                    command = Command(
                        command_name="task.create",
                        args={
                            "title": item["title"],
                            "due_date": item.get("due_date"),
                            "priority": item.get("priority"),
                            "description": item.get("description"),
                            "parent_task_id": parent_task_id,
                            "related_event_id": related_event_id,
                        },
                        requested_by=user_id,
                        conversation_id=proposal.conversation_id,
                        source="API",
                    )
                else:
                    command = Command(
                        command_name="schedule.create",
                        args={
                            "title": item["title"],
                            "schedule_type": "PERSONAL",
                            "start_time": item.get("start_time"),
                            "end_time": item.get("end_time"),
                            "location": item.get("location"),
                            "description": item.get("description"),
                            "recurrence": item.get("recurrence"),
                        },
                        requested_by=user_id,
                        conversation_id=proposal.conversation_id,
                        source="API",
                    )

                result = await registry.execute(command, ctx)
                if not result.success:
                    results.append(PlanProposalItemResult(key=key, type=item_type, outcome="failed", error=result.error))
                    continue

                created_id = result.data["id"]
                if item_type == "task":
                    task_key_to_id[key] = created_id
                else:
                    event_key_to_id[key] = created_id
                results.append(PlanProposalItemResult(key=key, type=item_type, outcome="created", id=created_id))
            except Exception as exc:
                logger.error(f"plan proposal {proposal_id} item {key} failed: {exc}", exc_info=True)
                results.append(PlanProposalItemResult(key=key, type=item_type, outcome="failed", error=str(exc)))

        await self.repo.set_approved(proposal_id)
        await self.session.commit()

        created_count = sum(1 for r in results if r.outcome == "created")
        logger.info(f"Approved plan proposal {proposal_id}: {created_count}/{len(results)} items created")
        return proposal, results

    @staticmethod
    def to_response(proposal: PlanProposal) -> PlanProposalResponse:
        return PlanProposalResponse(
            id=proposal.id,
            user_id=proposal.user_id,
            conversation_id=proposal.conversation_id,
            items=proposal.items if isinstance(proposal.items, list) else [],
            status=proposal.status,
            creator_type=proposal.creator_type,
            creator_id=proposal.creator_id,
            created_at=proposal.created_at,
            expires_at=proposal.expires_at,
            approved_at=proposal.approved_at,
            rejected_at=proposal.rejected_at,
        )
