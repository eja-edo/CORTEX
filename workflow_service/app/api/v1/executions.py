from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import uuid

from app.database import get_db
from app.core.security import get_current_user, CurrentUser
from app.models.execution import WorkflowInstance, WorkflowStepExecution, ExecutionStatus
from app.models.workflow import WorkflowDefinition
from app.schemas.execution import ExecutionResponse, StepExecutionResponse, ExecutionListResponse
from app.temporal.client import get_temporal_client
from temporalio.service import RPCError

router = APIRouter()


def _instance_to_response(instance: WorkflowInstance) -> ExecutionResponse:
    return ExecutionResponse(
        id=instance.id,
        workflow_id=instance.workflow_id,
        status=instance.status.value,
        temporal_workflow_id=instance.temporal_workflow_id,
        trigger_data=instance.trigger_data,
        output=instance.output,
        error_message=instance.error_message,
        started_at=instance.started_at,
        completed_at=instance.completed_at,
        created_at=instance.created_at,
    )


def _step_to_response(step: WorkflowStepExecution) -> StepExecutionResponse:
    return StepExecutionResponse(
        id=step.id,
        node_id=step.node_id,
        node_type=step.node_type,
        status=step.status.value,
        input_data=step.input_data,
        output_data=step.output_data,
        error_message=step.error_message,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


async def _verify_workflow_ownership(
    workflow_id: str, user_id: str, db: AsyncSession
) -> bool:
    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == uuid.UUID(workflow_id),
            WorkflowDefinition.user_id == uuid.UUID(user_id),
        )
    )
    return result.scalar_one_or_none() is not None


@router.get("", response_model=ExecutionListResponse)
async def list_executions(
    workflow_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(WorkflowInstance).where(
        WorkflowInstance.user_id == uuid.UUID(current_user.user_id),
    )

    if workflow_id:
        query = query.where(
            WorkflowInstance.workflow_id == uuid.UUID(workflow_id)
        )
    if status_filter:
        query = query.where(
            WorkflowInstance.status == ExecutionStatus(status_filter)
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    query = (
        query.offset((page - 1) * page_size)
        .limit(page_size)
        .order_by(desc(WorkflowInstance.created_at))
    )
    result = await db.execute(query)
    instances = result.scalars().all()

    return ExecutionListResponse(
        items=[_instance_to_response(i) for i in instances],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/{instance_id}", response_model=ExecutionResponse)
async def get_execution(
    instance_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WorkflowInstance)
        .options(selectinload(WorkflowInstance.steps))
        .where(WorkflowInstance.id == uuid.UUID(instance_id))
    )
    instance = result.scalar_one_or_none()

    if not instance:
        raise HTTPException(status_code=404, detail="Execution not found")

    ok = await _verify_workflow_ownership(
        str(instance.workflow_id), current_user.user_id, db
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Execution not found")

    response = _instance_to_response(instance)
    response.steps = [_step_to_response(s) for s in instance.steps]
    return response


@router.post("/{instance_id}/cancel")
async def cancel_execution(
    instance_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WorkflowInstance).where(
            WorkflowInstance.id == uuid.UUID(instance_id)
        )
    )
    instance = result.scalar_one_or_none()

    if not instance:
        raise HTTPException(status_code=404, detail="Execution not found")

    ok = await _verify_workflow_ownership(
        str(instance.workflow_id), current_user.user_id, db
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Execution not found")

    if instance.status not in (
        ExecutionStatus.PENDING,
        ExecutionStatus.RUNNING,
        ExecutionStatus.WAITING,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel execution with status: {instance.status.value}",
        )

    if instance.temporal_workflow_id:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(instance.temporal_workflow_id)
        try:
            await handle.cancel()
        except RPCError:
            pass

    instance.status = ExecutionStatus.CANCELLED
    instance.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(instance)

    return _instance_to_response(instance)
