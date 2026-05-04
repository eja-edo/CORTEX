"""Workspace management API endpoints."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pydantic import model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import User, Workspace, WorkspaceMember, WorkspaceRole
from app.services.workspace_permission import WorkspacePermission

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# --- Schemas ---

class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)


class WorkspaceResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    is_personal: bool
    my_role: str  # role of the requesting user

    class Config:
        from_attributes = True


class AddMemberRequest(BaseModel):
    user_id: Optional[UUID] = None
    email: Optional[str] = Field(None, min_length=1, max_length=255)
    role: str = Field(default="viewer", pattern="^(editor|viewer)$")

    @model_validator(mode="after")
    def validate_member_identifier(self):
        if self.user_id is None and not self.email:
            raise ValueError("Either user_id or email is required")
        return self


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(editor|viewer)$")


class MemberResponse(BaseModel):
    user_id: UUID
    role: str
    joined_at: datetime

    class Config:
        from_attributes = True


# --- Endpoints ---

@router.post("", response_model=WorkspaceResponse, status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new workspace. Creator becomes the owner."""
    workspace = Workspace(
        owner_id=current_user.id,
        name=payload.name,
    )
    db.add(workspace)
    db.flush()

    # Owner is automatically added as member
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=current_user.id,
        role=WorkspaceRole.OWNER,
    )
    db.add(member)
    db.commit()
    db.refresh(workspace)

    return {
        "id": workspace.id,
        "owner_id": workspace.owner_id,
        "name": workspace.name,
        "is_personal": workspace.is_personal,
        "my_role": "owner"
    }


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all workspaces the current user is a member of."""
    members = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == current_user.id
    ).all()

    result = []
    for m in members:
        ws = db.query(Workspace).filter(Workspace.id == m.workspace_id).first()
        if ws:
            result.append({
                "id": ws.id,
                "owner_id": ws.owner_id,
                "name": ws.name,
                "is_personal": ws.is_personal,
                "my_role": m.role.value
            })

    return result


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update workspace name. Only owner can update."""
    member = WorkspacePermission.require_member(workspace_id, current_user.id, db)
    WorkspacePermission.require_owner(member)

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if payload.name:
        ws.name = payload.name
    ws.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ws)
    
    return {
        "id": ws.id,
        "owner_id": ws.owner_id,
        "name": ws.name,
        "is_personal": ws.is_personal,
        "my_role": member.role.value
    }


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete a workspace. Only owner can delete. Personal workspaces cannot be deleted."""
    member = WorkspacePermission.require_member(workspace_id, current_user.id, db)
    WorkspacePermission.require_owner(member)

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if ws.is_personal:
        raise HTTPException(status_code=400, detail="Cannot delete personal workspace")

    db.delete(ws)  # CASCADE will delete members, notes, assets
    db.commit()
    return None


# --- Member endpoints ---

@router.post("/{workspace_id}/members", status_code=201)
def add_member(
    workspace_id: UUID,
    payload: AddMemberRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Add a user to workspace. Only owner can add members."""
    member = WorkspacePermission.require_member(workspace_id, current_user.id, db)
    WorkspacePermission.require_owner(member)

    # Resolve the invited user by id first, then by email for the current UI flow.
    target_user = None
    if payload.user_id is not None:
        target_user = db.query(User).filter(User.id == payload.user_id).first()
    elif payload.email:
        normalized_email = payload.email.strip().lower()
        target_user = db.query(User).filter(func.lower(User.email) == normalized_email).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = WorkspacePermission.get_member(workspace_id, target_user.id, db)
    if existing:
        raise HTTPException(status_code=409, detail="User already a member")

    new_member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=target_user.id,
        role=WorkspaceRole(payload.role),
        invited_by=current_user.id,
    )
    db.add(new_member)
    db.commit()
    return {"message": "Member added"}


@router.patch("/{workspace_id}/members/{user_id}")
def update_member_role(
    workspace_id: UUID,
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update a member's role. Only owner can change roles."""
    requester = WorkspacePermission.require_member(workspace_id, current_user.id, db)
    WorkspacePermission.require_owner(requester)

    target = WorkspacePermission.get_member(workspace_id, user_id, db)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == WorkspaceRole.OWNER:
        raise HTTPException(status_code=400, detail="Cannot change owner role")

    target.role = WorkspaceRole(payload.role)
    db.commit()
    return {"message": "Role updated"}


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(
    workspace_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Remove a member from workspace. Only owner can remove members. Cannot remove owner."""
    requester = WorkspacePermission.require_member(workspace_id, current_user.id, db)
    WorkspacePermission.require_owner(requester)

    target = WorkspacePermission.get_member(workspace_id, user_id, db)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == WorkspaceRole.OWNER:
        raise HTTPException(status_code=400, detail="Cannot remove workspace owner")

    db.delete(target)
    db.commit()
    return None
