import uuid
from datetime import datetime, timezone

from temporalio import activity

from app.models.workflow import WorkflowDefinition
from app.database import AsyncSessionLocal
from app.temporal.client import start_workflow_execution
from sqlalchemy import select


@activity.defn(name="trigger-scheduled-execution")
async def trigger_scheduled_execution(input: dict) -> str:
    workflow_id = input["workflow_id"]
    schedule_id = input.get("schedule_id")
    timezone_name = input.get("timezone", "UTC")

    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.id == uuid.UUID(workflow_id))
        )
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise Exception(f"Workflow {workflow_id} not found")

    instance_id = await start_workflow_execution(
        workflow,
        trigger_data={
            "event": "schedule.trigger",
            "schedule_id": schedule_id,
            "timestamp": timestamp,
            "timezone": timezone_name,
        },
    )
    return instance_id
