from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note, NoteEditProposal, NoteRevision
from app.repositories.notes import NoteRepository
from app.repositories.proposals import ProposalRepository
from app.schemas import NoteEditProposalResponse, NotePatchOp as NotePatchOpSchema
from app.utils.logger import get_logger
from app.utils.note_delta import apply_text_patch

logger = get_logger(__name__)

PROPOSAL_TTL_HOURS = 24


class ProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.proposal_repo = ProposalRepository(session)
        self.note_repo = NoteRepository(session)

    async def create_proposal(
        self,
        *,
        note: Note,
        user_id: UUID,
        old_content: str,
        new_content: str,
        patch: list[dict],
        creator_type: str = "AGENT",
        creator_id: str | None = None,
        conversation_id: UUID | None = None,
    ) -> NoteEditProposal:
        # Supersede older pending proposals for the same note
        await self.proposal_repo.supersede_older_pending(note.id)

        # Find base_revision_id: the latest revision < current checkpoint_version
        base_revision_id = None
        revisions = await self.note_repo.list_revisions_since_checkpoint(
            note.id, note.checkpoint_version - 1
        )
        if revisions:
            base_revision_id = revisions[-1].id

        proposal = NoteEditProposal(
            note_id=note.id,
            base_revision_id=base_revision_id,
            base_version=note.version,
            patch=patch,
            creator_type=creator_type,
            creator_id=creator_id or str(user_id),
            status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=PROPOSAL_TTL_HOURS),
            conversation_id=conversation_id,
        )
        created = await self.proposal_repo.create(proposal)
        await self.session.commit()
        logger.info(
            f"Created proposal {created.id} for note {note.id} "
            f"(base_version={note.version}, creator={creator_type}:{creator_id})"
        )
        return created

    async def get_proposal(
        self, proposal_id: UUID, user_id: UUID
    ) -> NoteEditProposal | None:
        proposal = await self.proposal_repo.get_by_id(proposal_id)
        if proposal is None:
            return None
        # Touch last_viewed_at + extend expiry
        await self.proposal_repo.touch_last_viewed(proposal_id)
        await self.session.commit()
        return proposal

    async def get_proposal_dict(
        self, proposal_id: UUID, user_id: UUID
    ) -> dict | None:
        """Like get_proposal but returns a plain dict to avoid greenlet issues."""
        proposal = await self.proposal_repo.get_by_id(proposal_id)
        if proposal is None:
            return None
        # Pre-extract all fields before session ops that may expire them
        result = {
            "id": proposal.id,
            "note_id": proposal.note_id,
            "base_revision_id": proposal.base_revision_id,
            "base_version": proposal.base_version,
            "patch": list(proposal.patch) if isinstance(proposal.patch, list) else [],
            "creator_type": proposal.creator_type,
            "creator_id": proposal.creator_id,
            "status": proposal.status,
            "approved_by": proposal.approved_by,
            "approved_at": proposal.approved_at,
            "rejected_by": proposal.rejected_by,
            "rejected_at": proposal.rejected_at,
            "last_viewed_at": proposal.last_viewed_at,
            "expires_at": proposal.expires_at,
            "conversation_id": proposal.conversation_id,
            "created_at": proposal.created_at,
            "updated_at": proposal.updated_at,
        }
        # Touch last_viewed_at + extend expiry
        await self.proposal_repo.touch_last_viewed(proposal_id)
        await self.session.commit()
        return result

    async def compute_proposal_content(
        self, proposal_or_data: NoteEditProposal | dict, note: Note
    ) -> tuple[str, str]:
        """Return (old_content, new_content) for a proposal."""
        if isinstance(proposal_or_data, dict):
            base_revision_id = proposal_or_data.get("base_revision_id")
            proposal_patch = proposal_or_data["patch"]
        else:
            base_revision_id = proposal_or_data.base_revision_id
            proposal_patch = proposal_or_data.patch
        note_content = note.content
        note_id = note.id
        checkpoint_version = note.checkpoint_version

        base = note_content
        if base_revision_id:
            rev = await self.session.get(NoteRevision, base_revision_id)
            if rev:
                revisions = await self.note_repo.list_revisions_since_checkpoint(
                    note_id, checkpoint_version
                )
                for r in revisions:
                    if r.version <= rev.version:
                        base = apply_text_patch(base, r.patch)

        patches = []
        if base_revision_id:
            rev = await self.session.get(NoteRevision, base_revision_id)
            if rev:
                patches = rev.patch if isinstance(rev.patch, list) else []

        if patches:
            old_content = apply_text_patch(base, patches)
        else:
            old_content = base
        new_content = apply_text_patch(old_content, proposal_patch)
        return old_content, new_content

    async def approve_proposal(
        self, proposal_id: UUID, user_id: UUID, note_service
    ) -> tuple[NoteEditProposal, Note | None]:
        """
        Approve a proposal: apply patch to note, create revision.
        Returns (proposal, updated_note). Returns None for note if conflict.
        """
        proposal = await self.proposal_repo.get_by_id(proposal_id)
        if proposal is None:
            raise ValueError("Proposal not found")

        if proposal.status == "approved":
            note = await self.note_repo.get_active_by_id_and_user(
                proposal.note_id, user_id
            )
            return proposal, note

        if proposal.status == "rejected":
            raise ValueError("Proposal has already been rejected")

        if proposal.status == "expired":
            raise ValueError("Proposal has expired")

        # Optimistic lock: pending → applying
        acquired = await self.proposal_repo.transition_status(
            proposal_id, "pending", "applying"
        )
        if not acquired:
            raise ValueError("Proposal is already being processed")

        try:
            note = await self.note_repo.get_active_by_id_and_user(
                proposal.note_id, user_id
            )
            if note is None:
                await self.proposal_repo.transition_status(
                    proposal_id, "applying", "pending"
                )
                raise ValueError("Note not found")

            # Version conflict check
            if proposal.base_version != note.version:
                await self.proposal_repo.transition_status(
                    proposal_id, "applying", "pending"
                )
                raise ValueError(
                    f"Version conflict: proposal base_version={proposal.base_version}, "
                    f"current version={note.version}"
                )

            # Compute old content and apply patch
            old_content, new_content = await self.compute_proposal_content(
                proposal, note
            )

            # Apply patch to note via the existing note service
            from app.schemas import NotePatchRequest as NotePatchRequestSchema

            patch_payload = NotePatchRequestSchema(
                version=note.version,
                patch=[NotePatchOpSchema(**op) for op in proposal.patch],
            )
            updated = await note_service.patch_note(
                note_id=proposal.note_id,
                user_id=user_id,
                payload=patch_payload,
            )
            if updated is None:
                await self.proposal_repo.transition_status(
                    proposal_id, "applying", "pending"
                )
                raise ValueError("Failed to apply patch: version conflict or note not found")

            # Mark proposal as approved
            await self.proposal_repo.set_approved(proposal_id, user_id)
            await self.session.commit()

            logger.info(
                f"Approved proposal {proposal_id} for note {note.id} "
                f"(version {proposal.base_version} → {updated.version})"
            )

            return proposal, updated

        except Exception:
            await self.session.rollback()
            await self.proposal_repo.transition_status(
                proposal_id, "applying", "pending"
            )
            raise

    async def reject_proposal(
        self, proposal_id: UUID, user_id: UUID
    ) -> NoteEditProposal:
        proposal = await self.proposal_repo.get_by_id(proposal_id)
        if proposal is None:
            raise ValueError("Proposal not found")

        if proposal.status == "rejected":
            return proposal

        if proposal.status == "approved":
            raise ValueError("Proposal has already been approved")

        if proposal.status == "expired":
            raise ValueError("Proposal has expired")

        await self.proposal_repo.set_rejected(proposal_id, user_id)
        await self.session.commit()
        logger.info(f"Rejected proposal {proposal_id} for note {proposal.note_id}")
        return proposal

    async def list_proposals(
        self,
        user_id: UUID,
        note_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[NoteEditProposal], int]:
        items, total = await self.proposal_repo.list_by_user(
            user_id=user_id,
            note_id=note_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return list(items), total

    @staticmethod
    def to_response(
        proposal: NoteEditProposal,
        old_content: str | None = None,
        new_content: str | None = None,
    ) -> NoteEditProposalResponse:
        return NoteEditProposalResponse(
            id=proposal.id,
            note_id=proposal.note_id,
            base_revision_id=proposal.base_revision_id,
            base_version=proposal.base_version,
            patch=proposal.patch if isinstance(proposal.patch, list) else [],
            creator_type=proposal.creator_type,
            creator_id=proposal.creator_id,
            status=proposal.status,
            approved_by=proposal.approved_by,
            approved_at=proposal.approved_at,
            rejected_by=proposal.rejected_by,
            rejected_at=proposal.rejected_at,
            last_viewed_at=proposal.last_viewed_at,
            expires_at=proposal.expires_at,
            conversation_id=proposal.conversation_id,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
            old_content=old_content,
            new_content=new_content,
        )

    @staticmethod
    def to_response_from_dict(
        proposal_data: dict,
        old_content: str | None = None,
        new_content: str | None = None,
    ) -> NoteEditProposalResponse:
        return NoteEditProposalResponse(
            id=proposal_data["id"],
            note_id=proposal_data["note_id"],
            base_revision_id=proposal_data.get("base_revision_id"),
            base_version=proposal_data["base_version"],
            patch=proposal_data["patch"] if isinstance(proposal_data["patch"], list) else [],
            creator_type=proposal_data["creator_type"],
            creator_id=proposal_data["creator_id"],
            status=proposal_data["status"],
            approved_by=proposal_data.get("approved_by"),
            approved_at=proposal_data.get("approved_at"),
            rejected_by=proposal_data.get("rejected_by"),
            rejected_at=proposal_data.get("rejected_at"),
            last_viewed_at=proposal_data.get("last_viewed_at"),
            expires_at=proposal_data["expires_at"],
            conversation_id=proposal_data.get("conversation_id"),
            created_at=proposal_data["created_at"],
            updated_at=proposal_data["updated_at"],
            old_content=old_content,
            new_content=new_content,
        )
