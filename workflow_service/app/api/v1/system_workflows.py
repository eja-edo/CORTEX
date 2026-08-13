"""Minimal API surface for the System Workflow Reference Model (Milestone
4.0). Not the Workflow List UI (Milestone 4.5, not built yet) -- just enough
to enable/disable/fork a system workflow per workspace and to inspect the
resolved state, so this milestone is testable and usable ahead of any UI."""

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, CurrentUser
from app.database import get_db
from app.schemas.workflow import WorkflowDefinitionSchema, WorkflowResponse
from app.api.v1.workflows import _to_response
from app.services.system_workflows import (
    fork_system_workflow,
    resolve_effective_workflows,
    set_workspace_workflow_enabled,
)

router = APIRouter()


class EffectiveWorkflowResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    enabled: bool
    is_forked: bool
    forked_workflow_id: Optional[UUID]


class SetEnabledRequest(BaseModel):
    workspace_id: UUID
    enabled: bool


class ForkRequest(BaseModel):
    workspace_id: UUID
    definition: WorkflowDefinitionSchema
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_config: Optional[dict[str, Any]] = None


@router.get("", response_model=list[EffectiveWorkflowResponse])
async def list_effective_system_workflows(
    workspace_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await resolve_effective_workflows(db, workspace_id)


@router.post("/{workflow_id}/settings", response_model=EffectiveWorkflowResponse)
async def update_system_workflow_setting(
    workflow_id: UUID,
    data: SetEnabledRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await set_workspace_workflow_enabled(
        db, workspace_id=data.workspace_id, workflow_id=workflow_id, enabled=data.enabled,
    )
    effective = await resolve_effective_workflows(db, data.workspace_id)
    match = next((wf for wf in effective if wf["id"] == workflow_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="System workflow not found")
    return match


@router.post("/{workflow_id}/fork", response_model=WorkflowResponse)
async def fork_system_workflow_endpoint(
    workflow_id: UUID,
    data: ForkRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        fork = await fork_system_workflow(
            db,
            workspace_id=data.workspace_id,
            workflow_id=workflow_id,
            user_id=current_user.user_id,
            definition=data.definition.model_dump(),
            name=data.name,
            description=data.description,
            trigger_config=data.trigger_config,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(fork)
