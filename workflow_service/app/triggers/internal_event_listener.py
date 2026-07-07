import asyncio
import json
import redis.asyncio as aioredis
from sqlalchemy import select

from app.config import settings
from app.models.workflow import WorkflowDefinition, WorkflowStatus, TriggerType
from app.database import AsyncSessionLocal

REDIS_CHANNEL = "cortex:workflow:events"

SUPPORTED_EVENTS = [
    "note.created",
    "note.updated",
    "note.deleted",
    "schedule.created",
    "schedule.updated",
    "schedule.completed",
    "asset.uploaded",
    "asset.processed",
]


async def start_internal_event_listener():
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(REDIS_CHANNEL)

    print(f"[TriggerEngine] Listening on Redis channel: {REDIS_CHANNEL}")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue

        try:
            event_data = json.loads(message["data"])
            event_type = event_data.get("event")

            if event_type not in SUPPORTED_EVENTS:
                continue

            await _handle_event(event_type, event_data)

        except Exception as e:
            print(f"[TriggerEngine] Error handling event: {e}")


async def _handle_event(event_type: str, event_data: dict):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkflowDefinition).where(
                WorkflowDefinition.status == WorkflowStatus.ACTIVE,
                WorkflowDefinition.trigger_type == TriggerType.INTERNAL_EVENT,
                WorkflowDefinition.is_deleted == False
            )
        )
        workflows = result.scalars().all()

        for workflow in workflows:
            trigger_config = workflow.trigger_config
            configured_event = trigger_config.get("event")

            if configured_event != event_type:
                continue

            filters = trigger_config.get("filters", {})
            if not _matches_filters(event_data, filters):
                continue

            await _trigger_workflow_instance(workflow, event_data)
            print(f"[TriggerEngine] Triggered workflow {workflow.id} for event {event_type}")


def _matches_filters(event_data: dict, filters: dict) -> bool:
    for key, value in filters.items():
        if event_data.get(key) != value:
            return False
    return True


async def _trigger_workflow_instance(workflow: WorkflowDefinition, trigger_data: dict):
    from app.temporal.client import start_workflow_execution

    instance_id = await start_workflow_execution(workflow, trigger_data)
    print(
        f"[TriggerEngine] Triggered workflow {workflow.id} "
        f"instance={instance_id}"
    )
