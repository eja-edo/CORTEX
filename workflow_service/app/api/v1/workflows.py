from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import uuid
import secrets
import hashlib
import zoneinfo

from app.database import get_db, AsyncSessionLocal
from app.config import settings
from app.core.ids import uuid7
from app.core.security import get_current_user, CurrentUser
from app.models.workflow import WorkflowDefinition, WorkflowStatus, TriggerType, WorkflowTriggerWebhook, WorkflowTrigger
from app.models.execution import WorkflowInstance, ExecutionStatus
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse, WorkflowListResponse,
    WorkflowTriggerCreate, WorkflowTriggerUpdate, WorkflowTriggerResponse,
    WorkflowConflict,
)
from app.schemas.execution import ManualTriggerRequest
from app.services.workflow_conflicts import find_trigger_conflicts
from app.temporal.client import create_workflow_schedule, delete_workflow_schedule


class ExecuteNodeRequest(BaseModel):
    config: dict[str, Any] = {}
    trigger_data: dict[str, Any] = {}
    previous_outputs: dict[str, Any] = {}

router = APIRouter()


async def _get_workflow_or_404(workflow_id: str, user_id: str, db: AsyncSession) -> WorkflowDefinition:
    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.user_id == user_id,
            WorkflowDefinition.is_deleted == False
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


def _to_response(wf: WorkflowDefinition, *, warnings: list[WorkflowConflict] | None = None) -> WorkflowResponse:
    return WorkflowResponse(
        id=wf.id,
        user_id=wf.user_id,
        workspace_id=wf.workspace_id,
        name=wf.name,
        description=wf.description,
        status=wf.status.value if hasattr(wf.status, 'value') else wf.status,
        version=wf.version,
        trigger_type=wf.trigger_type.value if hasattr(wf.trigger_type, 'value') else wf.trigger_type,
        trigger_config=wf.trigger_config,
        definition=wf.definition,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        warnings=warnings,
    )


async def _conflicts_for_workflow(
    workflow: WorkflowDefinition, db: AsyncSession, *, user_id: str
) -> list[WorkflowConflict]:
    """A3: what `find_trigger_conflicts` finds for this workflow's own
    primary trigger + action nodes, excluding itself. `[]` when the
    trigger isn't `internal_event` or names no event — nothing to check."""
    if workflow.trigger_type != TriggerType.INTERNAL_EVENT:
        return []
    event_type = (workflow.trigger_config or {}).get("event")
    if not event_type:
        return []
    action_types = {
        n.get("type", "")
        for n in (workflow.definition or {}).get("nodes", [])
        if n.get("type", "").startswith("action.")
    }
    conflicts = await find_trigger_conflicts(
        db, user_id=user_id, event_type=event_type, action_types=action_types,
        exclude_workflow_id=workflow.id,
    )
    return [WorkflowConflict(**c.to_dict()) for c in conflicts]


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    workspace_id: str | None = Query(None),
    status: str | None = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(WorkflowDefinition).where(
        WorkflowDefinition.user_id == current_user.user_id,
        WorkflowDefinition.is_deleted == False
    )

    if workspace_id:
        query = query.where(WorkflowDefinition.workspace_id == workspace_id)
    if status:
        query = query.where(WorkflowDefinition.status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(WorkflowDefinition.created_at.desc())

    result = await db.execute(query)
    workflows = result.scalars().all()

    return WorkflowListResponse(
        items=[_to_response(wf) for wf in workflows],
        total=total or 0,
        page=page,
        page_size=page_size
    )


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    data: WorkflowCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workflow = WorkflowDefinition(
        user_id=current_user.user_id,
        workspace_id=data.workspace_id,
        name=data.name,
        description=data.description,
        trigger_type=TriggerType(data.trigger_type.value),
        trigger_config=data.trigger_config,
        definition=data.definition.model_dump(),
        status=WorkflowStatus.DRAFT,
    )

    db.add(workflow)
    await db.flush()

    webhook_url = None
    webhook_secret = None
    if data.trigger_type.value == "webhook":
        webhook_secret = secrets.token_urlsafe(32)
        # Deliberately v4, not the uuid7() used for row ids: this value is a
        # capability URL whose only job is to be unguessable. v7 would spend 48
        # of its 122 random bits on a timestamp and publish the webhook's
        # creation time to anyone holding the URL.
        webhook_path = str(uuid.uuid4()).replace("-", "")

        webhook = WorkflowTriggerWebhook(
            workflow_id=workflow.id,
            webhook_path=webhook_path,
            secret_hash=hashlib.sha256(webhook_secret.encode()).hexdigest(),
        )
        db.add(webhook)
        webhook_url = f"/api/v1/webhooks/{webhook_path}"

    await db.commit()
    await db.refresh(workflow)

    response = _to_response(workflow)
    response.webhook_url = webhook_url
    response.webhook_secret = webhook_secret
    return response


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    return _to_response(workflow)


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    data: WorkflowUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)

    if workflow.status == WorkflowStatus.ACTIVE and data.definition:
        workflow.version += 1

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "definition" and value:
            setattr(workflow, field, value.model_dump() if hasattr(value, 'model_dump') else value)
        elif value is not None:
            setattr(workflow, field, value)

    await db.commit()
    await db.refresh(workflow)
    return _to_response(workflow)


async def _delete_temporal_schedules(trigger_config: dict) -> None:
    ids = trigger_config.get("temporal_schedule_ids", [])
    if not ids:
        single = trigger_config.get("temporal_schedule_id")
        if single:
            ids = [single]
    for sid in ids:
        await delete_workflow_schedule(sid)


async def _supplementary_triggers(workflow_id, db: AsyncSession, *, trigger_type: TriggerType | None = None) -> list[WorkflowTrigger]:
    """All rows in workflow_triggers for a workflow (multi-trigger support) —
    optionally narrowed to one trigger_type. These are *additional* triggers
    on top of the workflow's own primary trigger_type/trigger_config, which
    is untouched by this table."""
    query = select(WorkflowTrigger).where(WorkflowTrigger.workflow_id == workflow_id)
    if trigger_type is not None:
        query = query.where(WorkflowTrigger.trigger_type == trigger_type)
    result = await db.execute(query)
    return list(result.scalars().all())


async def _activate_schedule_trigger(workflow: WorkflowDefinition, trigger_config: dict) -> dict:
    """Create Temporal schedule(s) from trigger_config (a `schedules` list,
    legacy single `cron`, or a one-time `run_at`) and return trigger_config
    updated with `temporal_schedule_ids`. Shared by the workflow's primary
    trigger and any supplementary SCHEDULE-type WorkflowTrigger row — the
    Temporal/DB side of "create a schedule" was already keyed purely by
    workflow_id/ids, not by "the" trigger_type, so this needed no new
    plumbing, just extracting what activate_workflow already did inline."""
    trigger_config = dict(trigger_config or {})

    # Remove any existing schedules first
    await _delete_temporal_schedules(trigger_config)
    trigger_config.pop("temporal_schedule_ids", None)
    trigger_config.pop("temporal_schedule_id", None)

    # Support multiple schedules from the new frontend config
    schedules = trigger_config.get("schedules")
    old_cron = trigger_config.get("cron")
    run_at = trigger_config.get("run_at")
    tz_name = trigger_config.get("timezone", "UTC")

    temporal_ids: list[str] = []

    if isinstance(schedules, list) and schedules:
        for entry in schedules:
            cron = entry.get("cron")
            if cron:
                sid = await create_workflow_schedule(
                    workflow_id=str(workflow.id),
                    cron=cron,
                    timezone=tz_name,
                    user_id=str(workflow.user_id),
                    schedule_id=entry.get("schedule_id"),
                )
                temporal_ids.append(sid)
    elif old_cron:
        sid = await create_workflow_schedule(
            workflow_id=str(workflow.id),
            cron=old_cron,
            timezone=tz_name,
            user_id=str(workflow.user_id),
            schedule_id=trigger_config.get("schedule_id"),
        )
        temporal_ids.append(sid)
    elif run_at:
        # One-time: schedule a single execution at run_at time
        from app.temporal.client import get_temporal_client
        from app.temporal.workflows import CortexWorkflow, CortexWorkflowInput

        run_dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
        delay = (run_dt - datetime.now(timezone.utc)).total_seconds()
        if delay > 0:
            instance_id = str(uuid7())
            temporal_workflow_id = f"cortex-wf-scheduled-{instance_id}"

            async with AsyncSessionLocal() as session:
                instance = WorkflowInstance(
                    id=instance_id,
                    workflow_id=workflow.id,
                    user_id=workflow.user_id,
                    status=ExecutionStatus.PENDING,
                    trigger_data={"event": "schedule.trigger", "schedule_id": trigger_config.get("schedule_id"), "run_at": run_at},
                )
                session.add(instance)
                await session.commit()

            client = await get_temporal_client()
            await client.start_workflow(
                CortexWorkflow.run,
                CortexWorkflowInput(
                    instance_id=instance_id,
                    workflow_id=str(workflow.id),
                    user_id=str(workflow.user_id),
                    workspace_id=str(workflow.workspace_id) if workflow.workspace_id else None,
                    definition=workflow.definition,
                    trigger_data={
                        "event": "schedule.trigger",
                        "schedule_id": trigger_config.get("schedule_id"),
                        "timestamp": run_dt.isoformat(),
                        "timezone": tz_name,
                    },
                ),
                id=temporal_workflow_id,
                task_queue=settings.temporal_task_queue,
                start_delay=timedelta(seconds=delay),
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Schedule trigger requires 'schedules', 'cron', or 'run_at' in trigger_config",
        )

    if temporal_ids:
        trigger_config["temporal_schedule_ids"] = temporal_ids

    return trigger_config


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)

    # Remove Temporal cron schedules if any — primary trigger, then any
    # supplementary ones (multi-trigger support).
    await _delete_temporal_schedules(workflow.trigger_config or {})
    for trigger in await _supplementary_triggers(workflow.id, db):
        await _delete_temporal_schedules(trigger.trigger_config or {})

    workflow.is_deleted = True
    workflow.status = WorkflowStatus.ARCHIVED
    await db.commit()


@router.post("/{workflow_id}/activate", response_model=WorkflowResponse)
async def activate_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)

    definition = workflow.definition
    nodes = definition.get("nodes", [])
    trigger_nodes = [n for n in nodes if n.get("type", "").startswith("trigger.")]
    action_nodes = [n for n in nodes if n.get("type", "").startswith("action.")]

    if not trigger_nodes:
        raise HTTPException(status_code=400, detail="Workflow must have at least one trigger node")
    if not action_nodes:
        raise HTTPException(status_code=400, detail="Workflow must have at least one action node")

    if workflow.trigger_type == TriggerType.SCHEDULE:
        workflow.trigger_config = await _activate_schedule_trigger(workflow, workflow.trigger_config or {})

    # Activate any supplementary SCHEDULE triggers too (multi-trigger support).
    for trigger in await _supplementary_triggers(workflow.id, db, trigger_type=TriggerType.SCHEDULE):
        if trigger.is_active:
            trigger.trigger_config = await _activate_schedule_trigger(workflow, trigger.trigger_config or {})

    workflow.status = WorkflowStatus.ACTIVE
    await db.commit()
    await db.refresh(workflow)

    # A3: computed *after* commit, against the now-ACTIVE row, so a
    # self-comparison can't occur through a stale pre-commit status — the
    # workflow being activated already matches its own query criteria by
    # the time this runs, which is exactly why `_conflicts_for_workflow`
    # excludes it by id rather than relying on status timing.
    warnings = await _conflicts_for_workflow(workflow, db, user_id=current_user.user_id)
    return _to_response(workflow, warnings=warnings)


@router.get("/{workflow_id}/conflicts", response_model=list[WorkflowConflict])
async def get_workflow_conflicts(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """A3 M2: on-demand check, independent of activation — lets the editor
    (or a future 4.5 audit page) warn before the user even hits Activate."""
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    return await _conflicts_for_workflow(workflow, db, user_id=current_user.user_id)


@router.post("/{workflow_id}/pause", response_model=WorkflowResponse)
async def pause_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)

    # Remove Temporal cron schedules if trigger type is schedule
    trigger_config = workflow.trigger_config or {}
    await _delete_temporal_schedules(trigger_config)
    trigger_config.pop("temporal_schedule_ids", None)
    trigger_config.pop("temporal_schedule_id", None)
    workflow.trigger_config = trigger_config

    # Same cleanup for any supplementary SCHEDULE triggers (multi-trigger support).
    for trigger in await _supplementary_triggers(workflow.id, db, trigger_type=TriggerType.SCHEDULE):
        supp_config = dict(trigger.trigger_config or {})
        await _delete_temporal_schedules(supp_config)
        supp_config.pop("temporal_schedule_ids", None)
        supp_config.pop("temporal_schedule_id", None)
        trigger.trigger_config = supp_config

    workflow.status = WorkflowStatus.PAUSED
    await db.commit()
    await db.refresh(workflow)
    return _to_response(workflow)


async def _get_workflow_trigger_or_404(
    workflow_id: str, trigger_id: str, user_id: str, db: AsyncSession
) -> tuple[WorkflowDefinition, WorkflowTrigger]:
    workflow = await _get_workflow_or_404(workflow_id, user_id, db)
    result = await db.execute(
        select(WorkflowTrigger).where(
            WorkflowTrigger.id == trigger_id,
            WorkflowTrigger.workflow_id == workflow.id,
        )
    )
    trigger = result.scalar_one_or_none()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return workflow, trigger


def _to_trigger_response(
    trigger: WorkflowTrigger, webhook_url: str | None = None, webhook_secret: str | None = None
) -> WorkflowTriggerResponse:
    return WorkflowTriggerResponse(
        id=trigger.id,
        workflow_id=trigger.workflow_id,
        trigger_type=trigger.trigger_type.value if hasattr(trigger.trigger_type, "value") else trigger.trigger_type,
        trigger_config=trigger.trigger_config,
        is_active=trigger.is_active,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        created_at=trigger.created_at,
        updated_at=trigger.updated_at,
    )


@router.post("/{workflow_id}/triggers", response_model=WorkflowTriggerResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow_trigger(
    workflow_id: str,
    data: WorkflowTriggerCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a supplementary trigger to a workflow — on top of, not instead
    of, its primary trigger_type/trigger_config (multi-trigger support)."""
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)

    trigger = WorkflowTrigger(
        workflow_id=workflow.id,
        trigger_type=TriggerType(data.trigger_type.value),
        trigger_config=data.trigger_config,
    )
    db.add(trigger)
    await db.flush()

    webhook_url = None
    webhook_secret = None
    if data.trigger_type.value == "webhook":
        webhook_secret = secrets.token_urlsafe(32)
        # Deliberately v4, not the uuid7() used for row ids: this value is a
        # capability URL whose only job is to be unguessable. v7 would spend 48
        # of its 122 random bits on a timestamp and publish the webhook's
        # creation time to anyone holding the URL.
        webhook_path = str(uuid.uuid4()).replace("-", "")
        webhook = WorkflowTriggerWebhook(
            workflow_id=workflow.id,
            trigger_id=trigger.id,
            webhook_path=webhook_path,
            secret_hash=hashlib.sha256(webhook_secret.encode()).hexdigest(),
        )
        db.add(webhook)
        webhook_url = f"/api/v1/webhooks/{webhook_path}"
    elif data.trigger_type.value == "schedule" and workflow.status == WorkflowStatus.ACTIVE:
        # Workflow is already running — a schedule added now should take
        # effect immediately, not wait for the next activate call.
        trigger.trigger_config = await _activate_schedule_trigger(workflow, trigger.trigger_config or {})

    await db.commit()
    await db.refresh(trigger)

    return _to_trigger_response(trigger, webhook_url=webhook_url, webhook_secret=webhook_secret)


@router.get("/{workflow_id}/triggers", response_model=list[WorkflowTriggerResponse])
async def list_workflow_triggers(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    triggers = await _supplementary_triggers(workflow.id, db)
    return [_to_trigger_response(t) for t in triggers]


@router.patch("/{workflow_id}/triggers/{trigger_id}", response_model=WorkflowTriggerResponse)
async def update_workflow_trigger(
    workflow_id: str,
    trigger_id: str,
    data: WorkflowTriggerUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _workflow, trigger = await _get_workflow_trigger_or_404(workflow_id, trigger_id, current_user.user_id, db)

    if data.trigger_config is not None:
        trigger.trigger_config = data.trigger_config
    if data.is_active is not None:
        trigger.is_active = data.is_active

    await db.commit()
    await db.refresh(trigger)
    return _to_trigger_response(trigger)


@router.delete("/{workflow_id}/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow_trigger(
    workflow_id: str,
    trigger_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _workflow, trigger = await _get_workflow_trigger_or_404(workflow_id, trigger_id, current_user.user_id, db)

    await _delete_temporal_schedules(trigger.trigger_config or {})

    webhook_result = await db.execute(
        select(WorkflowTriggerWebhook).where(WorkflowTriggerWebhook.trigger_id == trigger.id)
    )
    for webhook in webhook_result.scalars().all():
        webhook.is_active = False

    await db.delete(trigger)
    await db.commit()


@router.post("/{workflow_id}/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_workflow(
    workflow_id: str,
    data: ManualTriggerRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    if workflow.status != WorkflowStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Workflow is not active")

    from app.temporal.client import start_workflow_execution, create_workflow_schedule, delete_workflow_schedule

    trigger_data: dict = {"event": "manual.trigger", "input": data.input_data}
    if workflow.trigger_type == TriggerType.SCHEDULE:
        tz_name = (workflow.trigger_config or {}).get("timezone", "UTC")
        now = datetime.now(timezone.utc)
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
            local_now = now.astimezone(tz)
            timestamp = local_now.isoformat()
        except Exception:
            timestamp = now.isoformat()
        trigger_data["timestamp"] = timestamp
        trigger_data["timezone"] = tz_name
    instance_id = await start_workflow_execution(workflow, trigger_data)
    return {"instance_id": instance_id, "workflow_id": str(workflow.id)}


@router.post("/{workflow_id}/nodes/{node_id}/execute")
async def execute_node(
    workflow_id: str,
    node_id: str,
    data: ExecuteNodeRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)

    definition = workflow.definition or {}
    nodes = definition.get("nodes", [])

    node_def = next((n for n in nodes if n.get("id") == node_id), None)
    if not node_def:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found in workflow definition")

    node_type = node_def.get("type", "")
    if not node_type or not (node_type.startswith("action.") or node_type.startswith("ai.") or node_type.startswith("trigger.")):
        raise HTTPException(status_code=400, detail="Only action/ai/trigger nodes can be executed")

    # For trigger nodes, return simplified output
    if node_type.startswith("trigger."):
        if node_type == "trigger.schedule":
            config = data.config
            timezone_name = config.get("timezone", "UTC")
            now = datetime.now(timezone.utc)
            try:
                tz = zoneinfo.ZoneInfo(timezone_name)
                local_now = now.astimezone(tz)
                timestamp = local_now.isoformat()
            except Exception:
                timestamp = now.isoformat()
            return {
                "success": True,
                "output": {
                    "timestamp": timestamp,
                    "timezone": timezone_name,
                },
                "error": None,
            }
        return {
            "success": True,
            "output": data.config,
            "error": None,
        }

    from app.actions.registry import action_registry
    from app.actions.base import ActionContext

    action = action_registry.get(node_type)
    if not action:
        raise HTTPException(status_code=400, detail=f"No action registered for type: {node_type}")

    node_id_labels = {}
    for n in nodes:
        label = n.get("data", {}).get("label", "")
        if label:
            node_id_labels[label] = n.get("id", "")

    # Auto-populate trigger_data when empty so templates resolve correctly.
    resolved_trigger = data.trigger_data
    if not resolved_trigger:
        trigger_config = workflow.trigger_config or {}
        if workflow.trigger_type == TriggerType.SCHEDULE:
            tz_name = trigger_config.get("timezone", "UTC")
            now = datetime.now(timezone.utc)
            try:
                tz = zoneinfo.ZoneInfo(tz_name)
                local_now = now.astimezone(tz)
                timestamp = local_now.isoformat()
            except Exception:
                timestamp = now.isoformat()
            resolved_trigger = {
                "event": "schedule.trigger",
                "schedule_id": trigger_config.get("schedule_id"),
                "timestamp": timestamp,
                "timezone": tz_name,
            }
        elif workflow.trigger_type == TriggerType.MANUAL:
            resolved_trigger = {"event": "manual.trigger", "input": {}}
        elif workflow.trigger_type == TriggerType.WEBHOOK:
            resolved_trigger = {"event": "webhook.received"}
        elif workflow.trigger_type == TriggerType.INTERNAL_EVENT:
            resolved_trigger = {"event": trigger_config.get("event", "unknown.event")}

    context = ActionContext(
        user_id=str(workflow.user_id),
        workflow_id=str(workflow.id),
        instance_id="",
        node_id=node_id,
        trigger_data=resolved_trigger,
        previous_outputs=data.previous_outputs,
        node_id_labels=node_id_labels,
        workspace_id=str(workflow.workspace_id) if workflow.workspace_id else None,
    )

    result = await action.execute(data.config, context)

    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
    }
