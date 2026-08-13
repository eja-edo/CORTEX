"""System Workflow Reference Model (Milestone 4.0).

System workflows (Cortex's own built-in behavior) are ordinary
WorkflowDefinition rows owned by SYSTEM_WORKFLOW_USER_ID instead of being
copied into every workspace. A workspace's relationship to a system workflow
— disabled, or forked into a private copy — lives in exactly one row of
workspace_workflow_settings. No row means "enabled, not forked": a brand new
workspace gets the default behavior with zero rows written anywhere.
"""

from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    SYSTEM_WORKFLOW_USER_ID,
    TriggerType,
    WorkflowDefinition,
    WorkflowStatus,
    WorkspaceWorkflowSetting,
)


async def list_system_workflow_definitions(db: AsyncSession) -> list[WorkflowDefinition]:
    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.user_id == SYSTEM_WORKFLOW_USER_ID,
            WorkflowDefinition.is_deleted == False,
        )
    )
    return list(result.scalars().all())


async def _get_setting(
    db: AsyncSession, *, workspace_id: UUID, workflow_id: UUID
) -> Optional[WorkspaceWorkflowSetting]:
    result = await db.execute(
        select(WorkspaceWorkflowSetting).where(
            WorkspaceWorkflowSetting.workspace_id == workspace_id,
            WorkspaceWorkflowSetting.workflow_id == workflow_id,
        )
    )
    return result.scalar_one_or_none()


async def is_system_workflow_active_for_workspace(
    db: AsyncSession, *, workflow_id: UUID, workspace_id: Optional[UUID]
) -> bool:
    """No settings row -> active (default-on). A settings row disables it,
    or marks it forked -- once forked, the fork itself is a normal
    WorkflowDefinition row that the caller's own trigger query already
    matches, so the system definition must stop firing for that workspace."""
    if workspace_id is None:
        # An event with no workspace context can't be gated per-workspace;
        # fail open so system workflows keep working exactly as before this
        # milestone for events that don't carry workspace_id yet.
        return True

    setting = await _get_setting(db, workspace_id=workspace_id, workflow_id=workflow_id)
    if setting is None:
        return True
    return setting.enabled and setting.forked_workflow_id is None


async def set_workspace_workflow_enabled(
    db: AsyncSession, *, workspace_id: UUID, workflow_id: UUID, enabled: bool
) -> WorkspaceWorkflowSetting:
    setting = await _get_setting(db, workspace_id=workspace_id, workflow_id=workflow_id)
    if setting is None:
        setting = WorkspaceWorkflowSetting(
            id=uuid4(), workspace_id=workspace_id, workflow_id=workflow_id, enabled=enabled,
        )
        db.add(setting)
    else:
        setting.enabled = enabled

    await db.commit()
    await db.refresh(setting)
    return setting


async def fork_system_workflow(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    workflow_id: UUID,
    user_id: UUID,
    definition: dict[str, Any],
    name: Optional[str] = None,
    description: Optional[str] = None,
    trigger_config: Optional[dict[str, Any]] = None,
) -> WorkflowDefinition:
    """Copy-on-write (Milestone 4.0 M3): the first edit of a system workflow
    for a workspace creates a private copy owned by the editing user and
    marks the settings row as forked. From then on the fork is a plain
    workflow -- it matches _handle_event's normal WHERE clause on its own,
    no special-cased execution path needed."""
    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.user_id == SYSTEM_WORKFLOW_USER_ID,
            WorkflowDefinition.is_deleted == False,
        )
    )
    system_workflow = result.scalar_one_or_none()
    if system_workflow is None:
        raise ValueError(f"System workflow {workflow_id} not found")

    fork = WorkflowDefinition(
        id=uuid4(),
        user_id=user_id,
        workspace_id=workspace_id,
        name=name or system_workflow.name,
        description=description if description is not None else system_workflow.description,
        status=WorkflowStatus.ACTIVE,
        trigger_type=system_workflow.trigger_type,
        trigger_config=trigger_config if trigger_config is not None else dict(system_workflow.trigger_config),
        definition=definition,
    )
    db.add(fork)
    await db.flush()

    setting = await _get_setting(db, workspace_id=workspace_id, workflow_id=workflow_id)
    if setting is None:
        setting = WorkspaceWorkflowSetting(
            id=uuid4(), workspace_id=workspace_id, workflow_id=workflow_id,
        )
        db.add(setting)
    setting.forked_workflow_id = fork.id

    await db.commit()
    await db.refresh(fork)
    return fork


async def resolve_effective_workflows(db: AsyncSession, workspace_id: UUID) -> list[dict[str, Any]]:
    """Effective state of every system workflow for a workspace -- what a
    settings/audit UI (Milestone 4.5, not built yet) would list."""
    system_workflows = await list_system_workflow_definitions(db)
    effective = []
    for wf in system_workflows:
        setting = await _get_setting(db, workspace_id=workspace_id, workflow_id=wf.id)
        enabled = setting.enabled if setting is not None else True
        forked_workflow_id = setting.forked_workflow_id if setting is not None else None
        effective.append({
            "id": wf.id,
            "name": wf.name,
            "description": wf.description,
            "enabled": enabled,
            "is_forked": forked_workflow_id is not None,
            "forked_workflow_id": forked_workflow_id,
        })
    return effective
