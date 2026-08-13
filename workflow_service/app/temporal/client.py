import uuid

from temporalio.client import Client, Schedule, ScheduleSpec, ScheduleActionStartWorkflow, SchedulePolicy, ScheduleOverlapPolicy

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.execution import WorkflowInstance, ExecutionStatus
from app.models.workflow import WorkflowDefinition
from app.temporal.workflows import CortexWorkflow, CortexWorkflowInput

_client: Client | None = None


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
        )
    return _client


async def close_temporal_client():
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def start_workflow_execution(
    workflow: WorkflowDefinition, trigger_data: dict
) -> str:
    from sqlalchemy import select

    instance_id = str(uuid.uuid4())
    temporal_workflow_id = f"cortex-wf-{instance_id}"

    async with AsyncSessionLocal() as db:
        instance = WorkflowInstance(
            id=instance_id,
            workflow_id=workflow.id,
            user_id=workflow.user_id,
            status=ExecutionStatus.PENDING,
            trigger_data=trigger_data,
        )
        db.add(instance)
        await db.commit()

    client = await get_temporal_client()
    try:
        await client.start_workflow(
            CortexWorkflow.run,
            CortexWorkflowInput(
                instance_id=instance_id,
                workflow_id=str(workflow.id),
                user_id=str(workflow.user_id),
                workspace_id=str(workflow.workspace_id) if workflow.workspace_id else None,
                definition=workflow.definition,
                trigger_data=trigger_data,
            ),
            id=temporal_workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:
        # Without this, a Temporal-unreachable failure here leaves the
        # WorkflowInstance row committed above stuck at PENDING forever —
        # no temporal_workflow_id ever gets set, and nothing cleans it up.
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WorkflowInstance).where(WorkflowInstance.id == uuid.UUID(instance_id))
            )
            inst = result.scalar_one_or_none()
            if inst:
                inst.status = ExecutionStatus.FAILED
                inst.error_message = f"Failed to start Temporal workflow: {e}"[:2000]
                await db.commit()
        raise

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkflowInstance).where(
                WorkflowInstance.id == uuid.UUID(instance_id)
            )
        )
        inst = result.scalar_one_or_none()
        if inst:
            inst.temporal_workflow_id = temporal_workflow_id
            await db.commit()

    return instance_id


async def create_workflow_schedule(
    workflow_id: str,
    cron: str,
    timezone: str,
    user_id: str,
    schedule_id: str | None = None,
) -> str:
    """Create a Temporal cron schedule that triggers the workflow periodically."""
    client = await get_temporal_client()
    temporal_schedule_id = f"cortex-schedule-{workflow_id}"

    from app.temporal.scheduled_workflow import ScheduledExecutionWorkflow

    await client.create_schedule(
        temporal_schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                ScheduledExecutionWorkflow.run,
                args=[{
                    "workflow_id": workflow_id,
                    "user_id": user_id,
                    "schedule_id": schedule_id,
                    "timezone": timezone,
                }],
                id=f"{temporal_schedule_id}-exec",
                task_queue=settings.temporal_task_queue,
            ),
            spec=ScheduleSpec(
                cron_expressions=[cron],
                time_zone_name=timezone,
            ),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        ),
    )
    return temporal_schedule_id


async def update_workflow_schedule(
    temporal_schedule_id: str,
    cron: str,
    timezone: str,
    workflow_id: str,
    user_id: str,
    schedule_id: str | None = None,
) -> None:
    """Update an existing Temporal cron schedule by replacing it."""
    await delete_workflow_schedule(temporal_schedule_id)
    await create_workflow_schedule(
        workflow_id=workflow_id,
        cron=cron,
        timezone=timezone,
        user_id=user_id,
        schedule_id=schedule_id,
    )


async def delete_workflow_schedule(temporal_schedule_id: str) -> None:
    """Delete a Temporal cron schedule, stopping future triggers."""
    try:
        client = await get_temporal_client()
        handle = client.get_schedule_handle(temporal_schedule_id)
        await handle.delete()
    except Exception as exc:
        # Not-found is expected (schedule already gone) and fine to ignore,
        # but logging unconditionally beats silently swallowing every other
        # failure too (e.g. Temporal unreachable) — a leaked schedule with
        # no trace anywhere is exactly the kind of silent failure this
        # audit exists to catch.
        print(f"[Temporal] Failed to delete schedule {temporal_schedule_id}: {exc}")
