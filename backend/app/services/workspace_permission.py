"""Workspace permission helper for role-based access control."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import WorkspaceMember, WorkspaceRole


class WorkspacePermission:
    """
    Helper to check workspace permissions. Used in all workspace-related endpoints.
    
    Usage:
        member = WorkspacePermission.require_member(workspace_id, user_id, db)
        WorkspacePermission.require_editor(member)
    """

    @staticmethod
    def get_member(workspace_id: UUID, user_id: UUID, db: Session) -> WorkspaceMember | None:
        """Get workspace member if exists, otherwise return None."""
        return db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        ).first()

    @staticmethod
    def require_member(workspace_id: UUID, user_id: UUID, db: Session) -> WorkspaceMember:
        """User must be a member of the workspace — used for read operations."""
        member = WorkspacePermission.get_member(workspace_id, user_id, db)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this workspace"
            )
        return member

    @staticmethod
    def require_editor(member: WorkspaceMember) -> None:
        """User must be editor or owner — used for write operations."""
        if member.role not in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Editor access required"
            )

    @staticmethod
    def require_owner(member: WorkspaceMember) -> None:
        """User must be owner — used for admin operations."""
        if member.role != WorkspaceRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owner access required"
            )

    @staticmethod
    def can_read(member: WorkspaceMember) -> bool:
        """Check if member can read workspace content."""
        return member.role in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR, WorkspaceRole.VIEWER)

    @staticmethod
    def can_write(member: WorkspaceMember) -> bool:
        """Check if member can write to workspace."""
        return member.role in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR)

    @staticmethod
    def can_manage(member: WorkspaceMember) -> bool:
        """Check if member can manage workspace (owner only)."""
        return member.role == WorkspaceRole.OWNER
