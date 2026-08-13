"""
Real end-to-end tests through Temporal — no mocking of `_trigger_workflow_instance`,
no bypassing Temporal via the /nodes/{node_id}/execute debug endpoint (unlike
test_flow_integration.py and test_full_report.py, both of which explicitly
avoid Temporal). This is the first test in the suite that actually exercises
client.start_workflow() -> a real Worker -> the execute_action activity ->
CortexWorkflow's own orchestration logic.

Starts its own Worker for the duration of each test (same pattern
test_internal_event_listener.py uses for start_internal_event_listener():
asyncio.create_task + cancel in finally) rather than depending on a
workflow_service process already running somewhere with a worker attached.
"""

import asyncio
import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.execution import ExecutionStatus, WorkflowInstance
from app.temporal.worker import start_worker_background

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _create_and_activate_manual_workflow(async_client: AsyncClient, auth_headers: dict, definition: dict) -> str:
    create_resp = await async_client.post(
        "/api/v1/workflows",
        json={"name": f"e2e_{uuid.uuid4().hex[:8]}", "trigger_type": "manual", "definition": definition},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    workflow_id = create_resp.json()["id"]

    activate_resp = await async_client.post(f"/api/v1/workflows/{workflow_id}/activate", headers=auth_headers)
    assert activate_resp.status_code == 200
    return workflow_id


async def _wait_for_terminal_status(instance_id: str, timeout_seconds: float = 20.0) -> WorkflowInstance:
    deadline = time.monotonic() + timeout_seconds
    async with AsyncSessionLocal() as db:
        while time.monotonic() < deadline:
            result = await db.execute(
                select(WorkflowInstance).where(WorkflowInstance.id == uuid.UUID(instance_id))
            )
            instance = result.scalar_one_or_none()
            if instance is not None and instance.status in (
                ExecutionStatus.COMPLETED, ExecutionStatus.FAILED,
            ):
                return instance
            await asyncio.sleep(0.5)
            db.expire_all()
    raise AssertionError(f"WorkflowInstance {instance_id} did not reach a terminal status within {timeout_seconds}s")


@pytest.mark.slow
async def test_manual_trigger_completes_through_real_temporal_worker(
    async_client: AsyncClient, auth_headers: dict,
):
    definition = {
        "nodes": [
            {"id": "t1", "type": "trigger.manual", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "a1", "type": "action.test_success", "position": {"x": 200, "y": 0}, "data": {"config": {}}},
        ],
        "edges": [{"id": "e1", "source": "t1", "target": "a1"}],
        "variables": {},
    }
    workflow_id = await _create_and_activate_manual_workflow(async_client, auth_headers, definition)

    worker_task = start_worker_background()
    try:
        await asyncio.sleep(1)  # let the worker connect and start polling

        trigger_resp = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/trigger", json={"input_data": {}}, headers=auth_headers,
        )
        assert trigger_resp.status_code == 202
        instance_id = trigger_resp.json()["instance_id"]

        instance = await _wait_for_terminal_status(instance_id)

        assert instance.status == ExecutionStatus.COMPLETED, instance.error_message
        assert instance.temporal_workflow_id is not None
        assert instance.temporal_workflow_id.startswith("cortex-wf-")
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)


@pytest.mark.slow
async def test_action_reporting_failure_fails_the_instance(
    async_client: AsyncClient, auth_headers: dict,
):
    """Regression test for the workflows.py fix: action.condition with an
    unknown operator returns ActionResult(success=False, ...) without
    raising. Before the fix, CortexWorkflow.run() didn't check `.success`
    at all, so this instance would incorrectly end up COMPLETED."""
    definition = {
        "nodes": [
            {"id": "t1", "type": "trigger.manual", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "a1", "type": "action.condition", "position": {"x": 200, "y": 0},
                "data": {"config": {"left": "x", "operator": "not_a_real_operator", "right": "y"}},
            },
        ],
        "edges": [{"id": "e1", "source": "t1", "target": "a1"}],
        "variables": {},
    }
    workflow_id = await _create_and_activate_manual_workflow(async_client, auth_headers, definition)

    worker_task = start_worker_background()
    try:
        await asyncio.sleep(1)

        trigger_resp = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/trigger", json={"input_data": {}}, headers=auth_headers,
        )
        assert trigger_resp.status_code == 202
        instance_id = trigger_resp.json()["instance_id"]

        instance = await _wait_for_terminal_status(instance_id)

        assert instance.status == ExecutionStatus.FAILED
        assert instance.error_message and "Unknown operator" in instance.error_message
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)
