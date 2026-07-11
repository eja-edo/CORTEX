"""
Temporal activity functions for workflow execution.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from temporalio import activity

from app.actions import action_registry
from app.actions.base import ActionContext, ActionResult
from app.database import AsyncSessionLocal
from app.models.execution import (
    WorkflowStepExecution,
    WorkflowInstance,
    ExecutionStatus,
)


@dataclass
class ExecuteActionInput:
    action_type: str
    config: dict
    user_id: str
    workflow_id: str
    instance_id: str
    node_id: str
    trigger_data: dict
    previous_outputs: dict
    node_id_labels: dict | None = None
    workspace_id: str | None = None


@dataclass
class UpdateStepStatusInput:
    instance_id: str
    node_id: str
    node_type: str | None = None
    status: str = "RUNNING"
    input_data: dict | None = None
    output_data: dict | None = None
    error: str | None = None
    error_message: str | None = None


@dataclass
class UpdateInstanceStatusInput:
    instance_id: str
    status: str
    temporal_workflow_id: str | None = None
    temporal_run_id: str | None = None
    error_message: str | None = None
    output: dict | None = None


@dataclass
class NotifyCompletionInput:
    instance_id: str
    workflow_id: str
    status: str
    output: dict | None = None
    error: str | None = None
    user_id: str | None = None
    error_message: str | None = None


@activity.defn
async def execute_action(input: ExecuteActionInput) -> ActionResult:
    action = action_registry.get(input.action_type)
    if not action:
        raise ValueError(f"Unknown action type: {input.action_type}")

    context = ActionContext(
        user_id=input.user_id,
        workflow_id=input.workflow_id,
        instance_id=input.instance_id,
        node_id=input.node_id,
        trigger_data=input.trigger_data,
        previous_outputs=input.previous_outputs,
        node_id_labels=input.node_id_labels,
        workspace_id=input.workspace_id,
    )

    return await action.execute(input.config, context)


@activity.defn
async def update_step_status(input: UpdateStepStatusInput):
    async with AsyncSessionLocal() as db:
        stmt = select(WorkflowStepExecution).where(
            WorkflowStepExecution.instance_id == input.instance_id,
            WorkflowStepExecution.node_id == input.node_id,
        )
        result = await db.execute(stmt)
        step = result.scalar_one_or_none()

        if not step:
            step = WorkflowStepExecution(
                id=str(uuid.uuid4()),
                instance_id=input.instance_id,
                node_id=input.node_id,
                node_type=input.node_type or "",
                status=input.status,
                output_data=input.output_data,
                error_message=input.error,
                started_at=datetime.now(timezone.utc),
            )
            db.add(step)
        else:
            step.status = input.status
            if input.output_data is not None:
                step.output_data = input.output_data
            if input.error is not None:
                step.error_message = input.error
            if input.status in ("COMPLETED", "FAILED"):
                step.completed_at = datetime.now(timezone.utc)

        await db.commit()


@activity.defn
async def update_instance_status(input: UpdateInstanceStatusInput):
    async with AsyncSessionLocal() as db:
        stmt = select(WorkflowInstance).where(WorkflowInstance.id == input.instance_id)
        result = await db.execute(stmt)
        instance = result.scalar_one_or_none()
        if instance:
            instance.status = input.status
            if input.temporal_workflow_id is not None:
                instance.temporal_workflow_id = input.temporal_workflow_id
            if input.temporal_run_id is not None:
                instance.temporal_run_id = input.temporal_run_id
            if input.output is not None:
                instance.output = input.output
            if input.error_message is not None:
                instance.error_message = input.error_message
            if input.status in ("COMPLETED", "FAILED"):
                instance.completed_at = datetime.now(timezone.utc)
            await db.commit()


@activity.defn
async def notify_completion(input: NotifyCompletionInput):
    print(
        f"[WorkflowComplete] instance={input.instance_id} "
        f"workflow={input.workflow_id} status={input.status}"
        + (f" error={input.error}" if input.error else "")
    )


__all__ = [
    "ExecuteActionInput",
    "UpdateStepStatusInput",
    "UpdateInstanceStatusInput",
    "NotifyCompletionInput",
    "execute_action",
    "update_step_status",
    "update_instance_status",
    "notify_completion",
]
