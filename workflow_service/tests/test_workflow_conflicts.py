"""Milestone A3: workflow trigger conflict detection.

Real incident this guards against: a user-created workflow triggering on
`task.overdue` with an `action.request_attention` node duplicated the
backend's own direct delivery for that event (`notification_subscribers.py`)
— every overdue task fired two notifications. See
`app/services/workflow_conflicts.py`'s module docstring and
`docs/planning-v3.md`'s A3 section.

`task.overdue` is used below as the real, checked-in event with
`has_direct_backend_delivery: true` (see `app/triggers/event_vocabulary.json`)
— not a synthetic `test.*` event, since the whole point is the overlap with
a real backend path.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.workflow import TriggerType, WorkflowDefinition, WorkflowStatus
from app.services.workflow_conflicts import _action_types, find_trigger_conflicts

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _definition(*, trigger_type: str = "trigger.internal_event", action_types: list[str]) -> dict:
    nodes = [{"id": "t1", "type": trigger_type, "position": {"x": 0, "y": 0}, "data": {}}]
    nodes += [
        {"id": f"a{i}", "type": at, "position": {"x": 200, "y": i * 100}, "data": {}}
        for i, at in enumerate(action_types)
    ]
    edges = [{"id": f"e{i}", "source": "t1", "target": f"a{i}"} for i in range(len(action_types))]
    return {"nodes": nodes, "edges": edges, "variables": {}}


async def _create(async_client: AsyncClient, auth_headers: dict, *, name: str, event_type: str, action_types: list[str]) -> str:
    resp = await async_client.post(
        "/api/v1/workflows",
        json={
            "name": name,
            "trigger_type": "internal_event",
            "trigger_config": {"event": event_type},
            "definition": _definition(action_types=action_types),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _cleanup(*workflow_ids: str) -> None:
    async with AsyncSessionLocal() as db:
        for wf_id in workflow_ids:
            wf = await db.get(WorkflowDefinition, uuid.UUID(wf_id))
            if wf is not None:
                await db.delete(wf)
        await db.commit()


class TestActionTypesHelper:
    # Trivially async only so the module-level `pytestmark` (needed for the
    # API/DB tests below) doesn't warn about a sync test under an asyncio mark.
    async def test_excludes_action_wait(self):
        definition = _definition(action_types=["action.request_attention", "action.wait"])
        assert _action_types(definition) == {"action.request_attention"}

    async def test_ignores_trigger_nodes(self):
        definition = _definition(action_types=["action.create_note"])
        assert _action_types(definition) == {"action.create_note"}

    async def test_empty_definition_is_empty_set(self):
        assert _action_types(None) == set()
        assert _action_types({}) == set()


class TestBackendDirectConflict:
    async def test_activating_on_task_overdue_with_request_attention_warns(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        wf_id = await _create(
            async_client, auth_headers,
            name="Duplicate of backend overdue handler",
            event_type="task.overdue",
            action_types=["action.request_attention"],
        )
        try:
            resp = await async_client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)
            assert resp.status_code == 200
            warnings = resp.json()["warnings"]
            assert warnings is not None
            kinds = {w["kind"] for w in warnings}
            assert "backend_direct" in kinds
            backend_warning = next(w for w in warnings if w["kind"] == "backend_direct")
            assert backend_warning["event_type"] == "task.overdue"
            assert backend_warning["action_type"] == "action.request_attention"
        finally:
            await _cleanup(wf_id)

    async def test_different_action_type_on_same_event_has_no_backend_direct_warning(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        wf_id = await _create(
            async_client, auth_headers,
            name="Overdue note-taker",
            event_type="task.overdue",
            action_types=["action.create_note"],
        )
        try:
            resp = await async_client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)
            assert resp.status_code == 200
            warnings = resp.json()["warnings"]
            assert all(w["kind"] != "backend_direct" for w in warnings)
        finally:
            await _cleanup(wf_id)

    async def test_event_without_direct_delivery_has_no_backend_direct_warning(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        # note.created has no direct backend subscriber (see
        # notification_subscribers.py's DIRECT_DELIVERY_HANDLERS).
        wf_id = await _create(
            async_client, auth_headers,
            name="React to new notes",
            event_type="note.created",
            action_types=["action.request_attention"],
        )
        try:
            resp = await async_client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)
            assert resp.status_code == 200
            assert resp.json()["warnings"] == []
        finally:
            await _cleanup(wf_id)


class TestWorkflowVsWorkflowConflict:
    async def test_two_active_workflows_same_event_same_action_conflict(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        event_type = f"test.conflict_{uuid.uuid4().hex[:8]}"
        first_id = await _create(
            async_client, auth_headers, name="First responder",
            event_type=event_type, action_types=["action.create_note"],
        )
        second_id = None
        try:
            activate_first = await async_client.post(f"/api/v1/workflows/{first_id}/activate", headers=auth_headers)
            assert activate_first.json()["warnings"] == []

            second_id = await _create(
                async_client, auth_headers, name="Second responder",
                event_type=event_type, action_types=["action.create_note"],
            )
            activate_second = await async_client.post(f"/api/v1/workflows/{second_id}/activate", headers=auth_headers)
            assert activate_second.status_code == 200
            warnings = activate_second.json()["warnings"]
            assert len(warnings) == 1
            assert warnings[0]["kind"] == "workflow"
            assert warnings[0]["event_type"] == event_type
            assert warnings[0]["action_type"] == "action.create_note"
            assert warnings[0]["conflicting_workflow_id"] == first_id
        finally:
            await _cleanup(*(wf_id for wf_id in (first_id, second_id) if wf_id))

    async def test_does_not_conflict_with_itself(self, async_client: AsyncClient, auth_headers: dict):
        event_type = f"test.self_{uuid.uuid4().hex[:8]}"
        wf_id = await _create(
            async_client, auth_headers, name="Solo",
            event_type=event_type, action_types=["action.create_note"],
        )
        try:
            resp = await async_client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)
            assert resp.json()["warnings"] == []
        finally:
            await _cleanup(wf_id)

    async def test_different_action_types_same_event_do_not_conflict(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        event_type = f"test.diffaction_{uuid.uuid4().hex[:8]}"
        first_id = await _create(
            async_client, auth_headers, name="Notes",
            event_type=event_type, action_types=["action.create_note"],
        )
        second_id = None
        try:
            await async_client.post(f"/api/v1/workflows/{first_id}/activate", headers=auth_headers)
            second_id = await _create(
                async_client, auth_headers, name="Tasks",
                event_type=event_type, action_types=["action.create_task"],
            )
            resp = await async_client.post(f"/api/v1/workflows/{second_id}/activate", headers=auth_headers)
            assert resp.json()["warnings"] == []
        finally:
            await _cleanup(*(wf_id for wf_id in (first_id, second_id) if wf_id))

    async def test_paused_workflow_does_not_conflict(self, async_client: AsyncClient, auth_headers: dict):
        event_type = f"test.paused_{uuid.uuid4().hex[:8]}"
        first_id = await _create(
            async_client, auth_headers, name="Will be paused",
            event_type=event_type, action_types=["action.create_note"],
        )
        second_id = None
        try:
            await async_client.post(f"/api/v1/workflows/{first_id}/activate", headers=auth_headers)
            await async_client.post(f"/api/v1/workflows/{first_id}/pause", headers=auth_headers)

            second_id = await _create(
                async_client, auth_headers, name="Only active one",
                event_type=event_type, action_types=["action.create_note"],
            )
            resp = await async_client.post(f"/api/v1/workflows/{second_id}/activate", headers=auth_headers)
            assert resp.json()["warnings"] == [], "a paused workflow isn't a live duplication risk"
        finally:
            await _cleanup(*(wf_id for wf_id in (first_id, second_id) if wf_id))


class TestConflictsEndpoint:
    async def test_get_conflicts_works_without_activating(self, async_client: AsyncClient, auth_headers: dict):
        wf_id = await _create(
            async_client, auth_headers, name="Draft overdue duplicate",
            event_type="task.overdue", action_types=["action.request_attention"],
        )
        try:
            resp = await async_client.get(f"/api/v1/workflows/{wf_id}/conflicts", headers=auth_headers)
            assert resp.status_code == 200
            kinds = {w["kind"] for w in resp.json()}
            assert "backend_direct" in kinds
        finally:
            await _cleanup(wf_id)

    async def test_manual_trigger_has_no_conflicts(self, async_client: AsyncClient, auth_headers: dict, valid_definition):
        resp_create = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Manual", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        wf_id = resp_create.json()["id"]
        try:
            resp = await async_client.get(f"/api/v1/workflows/{wf_id}/conflicts", headers=auth_headers)
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            await _cleanup(wf_id)


class TestFindTriggerConflictsService:
    """Direct service-level tests, for cases awkward to set up through the
    API (excluding a specific id, checking the raw dataclass)."""

    async def test_exclude_workflow_id_omits_that_workflow_even_if_matching(self, auth_headers):
        event_type = f"test.exclude_{uuid.uuid4().hex[:8]}"
        user_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as db:
            wf = WorkflowDefinition(
                user_id=user_id,
                name="self",
                status=WorkflowStatus.ACTIVE,
                trigger_type=TriggerType.INTERNAL_EVENT,
                trigger_config={"event": event_type},
                definition=_definition(action_types=["action.request_attention"]),
            )
            db.add(wf)
            await db.commit()
            await db.refresh(wf)

            try:
                conflicts = await find_trigger_conflicts(
                    db, user_id=user_id, event_type=event_type,
                    action_types={"action.request_attention"},
                    exclude_workflow_id=wf.id,
                )
                assert conflicts == []

                conflicts_without_exclude = await find_trigger_conflicts(
                    db, user_id=user_id, event_type=event_type,
                    action_types={"action.request_attention"},
                )
                assert len(conflicts_without_exclude) == 1
                assert conflicts_without_exclude[0].conflicting_workflow_id == wf.id
            finally:
                await db.delete(wf)
                await db.commit()

    async def test_no_action_types_returns_empty(self):
        async with AsyncSessionLocal() as db:
            assert await find_trigger_conflicts(
                db, user_id=str(uuid.uuid4()), event_type="task.overdue", action_types=set(),
            ) == []
