"""Milestone 4.0: System Workflow Reference Model.

System workflows are WorkflowDefinition rows owned by SYSTEM_WORKFLOW_USER_ID
instead of being copied per workspace. These tests create such rows directly
via the DB session (a real user can never create one through the public
/api/v1/workflows API, since that endpoint always assigns the authenticated
user's own id) and exercise the settings/fork/gating machinery around them.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.workflow import (
    SYSTEM_WORKFLOW_USER_ID,
    TriggerType,
    WorkflowDefinition,
    WorkflowStatus,
    WorkspaceWorkflowSetting,
)
from app.services.system_workflows import is_system_workflow_active_for_workspace
from app.triggers import internal_event_listener as listener_module

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _create_system_workflow(event_type: str, valid_definition: dict) -> uuid.UUID:
    workflow_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(WorkflowDefinition(
            id=workflow_id,
            user_id=SYSTEM_WORKFLOW_USER_ID,
            workspace_id=None,
            name=f"system_test_{workflow_id.hex[:8]}",
            status=WorkflowStatus.ACTIVE,
            trigger_type=TriggerType.INTERNAL_EVENT,
            trigger_config={"event": event_type},
            definition=valid_definition,
        ))
        await db.commit()
    return workflow_id


async def _cleanup_workflow(workflow_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkspaceWorkflowSetting).where(
                (WorkspaceWorkflowSetting.workflow_id == workflow_id)
                | (WorkspaceWorkflowSetting.forked_workflow_id == workflow_id)
            )
        )
        for setting in result.scalars().all():
            await db.delete(setting)
        wf = await db.get(WorkflowDefinition, workflow_id)
        if wf is not None:
            await db.delete(wf)
        await db.commit()


async def test_no_settings_row_means_active_by_default(valid_definition):
    workflow_id = await _create_system_workflow(f"test.default_{uuid.uuid4().hex[:8]}", valid_definition)
    try:
        async with AsyncSessionLocal() as db:
            active = await is_system_workflow_active_for_workspace(
                db, workflow_id=workflow_id, workspace_id=uuid.uuid4(),
            )
        assert active is True
    finally:
        await _cleanup_workflow(workflow_id)


async def test_disabling_system_workflow_stops_it_firing_for_that_workspace(
    async_client: AsyncClient, auth_headers: dict, valid_definition, monkeypatch
):
    event_type = f"test.disable_{uuid.uuid4().hex[:8]}"
    workflow_id = await _create_system_workflow(event_type, valid_definition)
    disabled_workspace = uuid.uuid4()
    other_workspace = uuid.uuid4()

    try:
        resp = await async_client.post(
            f"/api/v1/system-workflows/{workflow_id}/settings",
            json={"workspace_id": str(disabled_workspace), "enabled": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        trigger_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(listener_module, "_trigger_workflow_instance", trigger_mock)

        await listener_module._handle_event(event_type, {"workspace_id": str(disabled_workspace)})
        assert trigger_mock.call_count == 0

        await listener_module._handle_event(event_type, {"workspace_id": str(other_workspace)})
        assert trigger_mock.call_count == 1
    finally:
        await _cleanup_workflow(workflow_id)


async def test_forking_system_workflow_moves_execution_to_the_fork(
    async_client: AsyncClient, auth_headers: dict, valid_definition, monkeypatch
):
    event_type = f"test.fork_{uuid.uuid4().hex[:8]}"
    workflow_id = await _create_system_workflow(event_type, valid_definition)
    workspace_id = uuid.uuid4()
    fork_id = None

    try:
        resp = await async_client.post(
            f"/api/v1/system-workflows/{workflow_id}/fork",
            json={
                "workspace_id": str(workspace_id),
                "definition": valid_definition,
                "name": "My custom version",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        fork = resp.json()
        fork_id = uuid.UUID(fork["id"])
        assert fork["name"] == "My custom version"

        async with AsyncSessionLocal() as db:
            active = await is_system_workflow_active_for_workspace(
                db, workflow_id=workflow_id, workspace_id=workspace_id,
            )
        assert active is False, "system definition must stop firing once forked for this workspace"

        trigger_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(listener_module, "_trigger_workflow_instance", trigger_mock)

        await listener_module._handle_event(event_type, {"workspace_id": str(workspace_id)})

        assert trigger_mock.call_count == 1
        (triggered_workflow, _data), _ = trigger_mock.call_args
        assert triggered_workflow.id == fork_id
    finally:
        if fork_id is not None:
            await async_client.delete(f"/api/v1/workflows/{fork_id}", headers=auth_headers)
        await _cleanup_workflow(workflow_id)


async def test_settings_lookup_cost_does_not_scale_with_workspace_count(valid_definition, monkeypatch):
    """Milestone 4.0 M5: N settings rows (simulating N workspaces overriding
    the same system workflow) must not change how many rows _handle_event's
    own SQL query returns for one event -- it's still exactly 1 (the system
    definition), and the per-workspace settings check only ever runs once
    per matched workflow, not once per workspace in the table."""
    event_type = f"test.scale_{uuid.uuid4().hex[:8]}"
    workflow_id = await _create_system_workflow(event_type, valid_definition)

    workspace_ids = [uuid.uuid4() for _ in range(200)]
    try:
        async with AsyncSessionLocal() as db:
            for ws_id in workspace_ids:
                db.add(WorkspaceWorkflowSetting(
                    id=uuid.uuid4(), workspace_id=ws_id, workflow_id=workflow_id, enabled=True,
                ))
            await db.commit()

        gate_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(listener_module, "is_system_workflow_active_for_workspace", gate_mock)
        trigger_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(listener_module, "_trigger_workflow_instance", trigger_mock)

        await listener_module._handle_event(event_type, {"workspace_id": str(workspace_ids[0])})

        assert trigger_mock.call_count == 1
        assert gate_mock.call_count == 1, (
            "settings gate should run once per matched system workflow, not once per settings row"
        )
    finally:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WorkspaceWorkflowSetting).where(WorkspaceWorkflowSetting.workflow_id == workflow_id)
            )
            for setting in result.scalars().all():
                await db.delete(setting)
            await db.commit()
        await _cleanup_workflow(workflow_id)
