import asyncio

from temporalio.worker import Worker

from app.config import settings
from app.temporal.client import get_temporal_client
from app.temporal.workflows import CortexWorkflow
from app.temporal.scheduled_workflow import ScheduledExecutionWorkflow
from app.temporal.activities import (
    execute_action,
    update_step_status,
    update_instance_status,
    notify_completion,
)
from app.temporal.activities.trigger_scheduled_execution import trigger_scheduled_execution


async def run_worker():
    client = await get_temporal_client()

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[CortexWorkflow, ScheduledExecutionWorkflow],
        activities=[
            execute_action,
            update_step_status,
            update_instance_status,
            notify_completion,
            trigger_scheduled_execution,
        ],
    )

    print(
        f"[TemporalWorker] Starting worker on task queue: "
        f"{settings.temporal_task_queue}"
    )
    await worker.run()


def start_worker_background() -> asyncio.Task:
    return asyncio.create_task(run_worker())
