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
from app.core.security import get_current_user, CurrentUser
from app.models.workflow import WorkflowDefinition, WorkflowStatus, TriggerType, WorkflowTriggerWebhook
from app.models.execution import WorkflowInstance, ExecutionStatus
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse, WorkflowListResponse
)
from app.schemas.execution import ManualTriggerRequest
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


def _to_response(wf: WorkflowDefinition) -> WorkflowResponse:
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
    )


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

@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)

    # Remove Temporal cron schedules if any
    trigger_config = workflow.trigger_config or {}
    await _delete_temporal_schedules(trigger_config)

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

    # Create Temporal schedule(s) if trigger type is schedule
    trigger_config = workflow.trigger_config or {}
    if workflow.trigger_type == TriggerType.SCHEDULE:
        # Remove any existing schedules first
        await _delete_temporal_schedules(trigger_config)
        trigger_config.pop("temporal_schedule_ids", None)
        trigger_config.pop("temporal_schedule_id", None)

        # Support multiple schedules from the new frontend config
        schedules = trigger_config.get("schedules")
        old_cron = trigger_config.get("cron")
        run_at = trigger_config.get("run_at")
        timezone = trigger_config.get("timezone", "UTC")

        temporal_ids: list[str] = []

        if isinstance(schedules, list) and schedules:
            for i, entry in enumerate(schedules):
                cron = entry.get("cron")
                if cron:
                    sid = await create_workflow_schedule(
                        workflow_id=str(workflow.id),
                        cron=cron,
                        timezone=timezone,
                        user_id=str(workflow.user_id),
                        schedule_id=entry.get("schedule_id"),
                    )
                    temporal_ids.append(sid)
        elif old_cron:
            sid = await create_workflow_schedule(
                workflow_id=str(workflow.id),
                cron=old_cron,
                timezone=timezone,
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
                instance_id = str(uuid.uuid4())
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
                        definition=workflow.definition,
                        trigger_data={
                            "event": "schedule.trigger",
                            "schedule_id": trigger_config.get("schedule_id"),
                            "timestamp": run_dt.isoformat(),
                            "timezone": trigger_config.get("timezone", "UTC"),
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

        workflow.trigger_config = trigger_config

    workflow.status = WorkflowStatus.ACTIVE
    await db.commit()
    await db.refresh(workflow)
    return _to_response(workflow)


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

    workflow.status = WorkflowStatus.PAUSED
    await db.commit()
    await db.refresh(workflow)
    return _to_response(workflow)


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

    # Auto-populate trigger_data for schedule-triggered workflows so
    # {{trigger.timestamp}} / {{trigger.timezone}} resolve correctly.
    resolved_trigger = data.trigger_data
    if not resolved_trigger and workflow.trigger_type == TriggerType.SCHEDULE:
        trigger_config = workflow.trigger_config or {}
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

    context = ActionContext(
        user_id=str(workflow.user_id),
        workflow_id=str(workflow.id),
        instance_id="",
        node_id=node_id,
        trigger_data=resolved_trigger,
        previous_outputs=data.previous_outputs,
        node_id_labels=node_id_labels,
    )

    result = await action.execute(data.config, context)

    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
    }
