"""
Multi-trigger workflows: a workflow can have supplementary triggers (rows
in `workflow_triggers`) on top of its primary trigger_type/trigger_config,
which stays unchanged for backward compatibility. See app/api/v1/workflows.py
(create/list/update/delete trigger endpoints, _activate_schedule_trigger)
and app/triggers/internal_event_listener.py (_handle_event matching both
primary and supplementary internal_event triggers).
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.triggers import internal_event_listener as listener_module

from .conftest import TEST_USER_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _create_manual_workflow(async_client: AsyncClient, auth_headers: dict, valid_definition: dict, name: str) -> str:
    create_resp = await async_client.post(
        "/api/v1/workflows",
        json={"name": name, "trigger_type": "manual", "definition": valid_definition},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    return create_resp.json()["id"]


class TestCreateListDeleteTrigger:
    async def test_create_supplementary_internal_event_trigger(
        self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict
    ):
        workflow_id = await _create_manual_workflow(
            async_client, auth_headers, valid_definition, f"multi_trigger_{uuid.uuid4().hex[:8]}",
        )
        try:
            resp = await async_client.post(
                f"/api/v1/workflows/{workflow_id}/triggers",
                json={"trigger_type": "internal_event", "trigger_config": {"event": "note.created"}},
                headers=auth_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["trigger_type"] == "internal_event"
            assert data["is_active"] is True
            assert data["workflow_id"] == workflow_id

            list_resp = await async_client.get(f"/api/v1/workflows/{workflow_id}/triggers", headers=auth_headers)
            assert list_resp.status_code == 200
            assert len(list_resp.json()) == 1
        finally:
            await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)

    async def test_create_supplementary_webhook_trigger_returns_distinct_secret(
        self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict
    ):
        workflow_id = await _create_manual_workflow(
            async_client, auth_headers, valid_definition, f"multi_trigger_webhook_{uuid.uuid4().hex[:8]}",
        )
        try:
            resp = await async_client.post(
                f"/api/v1/workflows/{workflow_id}/triggers",
                json={"trigger_type": "webhook", "trigger_config": {}},
                headers=auth_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["webhook_url"] is not None
            assert data["webhook_secret"] is not None
            assert data["webhook_url"].startswith("/api/v1/webhooks/")
        finally:
            await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)

    async def test_update_trigger_config_and_deactivate(
        self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict
    ):
        workflow_id = await _create_manual_workflow(
            async_client, auth_headers, valid_definition, f"multi_trigger_update_{uuid.uuid4().hex[:8]}",
        )
        try:
            create_resp = await async_client.post(
                f"/api/v1/workflows/{workflow_id}/triggers",
                json={"trigger_type": "internal_event", "trigger_config": {"event": "note.created"}},
                headers=auth_headers,
            )
            trigger_id = create_resp.json()["id"]

            patch_resp = await async_client.patch(
                f"/api/v1/workflows/{workflow_id}/triggers/{trigger_id}",
                json={"is_active": False},
                headers=auth_headers,
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["is_active"] is False
        finally:
            await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)

    async def test_delete_one_supplementary_trigger_leaves_others_intact(
        self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict
    ):
        workflow_id = await _create_manual_workflow(
            async_client, auth_headers, valid_definition, f"multi_trigger_delete_{uuid.uuid4().hex[:8]}",
        )
        try:
            resp_a = await async_client.post(
                f"/api/v1/workflows/{workflow_id}/triggers",
                json={"trigger_type": "internal_event", "trigger_config": {"event": "note.created"}},
                headers=auth_headers,
            )
            resp_b = await async_client.post(
                f"/api/v1/workflows/{workflow_id}/triggers",
                json={"trigger_type": "internal_event", "trigger_config": {"event": "task.created"}},
                headers=auth_headers,
            )
            trigger_a_id = resp_a.json()["id"]
            trigger_b_id = resp_b.json()["id"]

            del_resp = await async_client.delete(
                f"/api/v1/workflows/{workflow_id}/triggers/{trigger_a_id}", headers=auth_headers,
            )
            assert del_resp.status_code == 204

            list_resp = await async_client.get(f"/api/v1/workflows/{workflow_id}/triggers", headers=auth_headers)
            remaining_ids = {t["id"] for t in list_resp.json()}
            assert remaining_ids == {trigger_b_id}
        finally:
            await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)


class TestSupplementaryTriggerActivation:
    async def test_supplementary_schedule_trigger_on_active_workflow_creates_temporal_schedule(
        self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict, monkeypatch
    ):
        """Adding a schedule trigger to an already-ACTIVE workflow must take
        effect immediately (not wait for a future activate call)."""
        workflow_id = await _create_manual_workflow(
            async_client, auth_headers, valid_definition, f"multi_trigger_schedule_{uuid.uuid4().hex[:8]}",
        )
        activate_resp = await async_client.post(f"/api/v1/workflows/{workflow_id}/activate", headers=auth_headers)
        assert activate_resp.status_code == 200

        schedule_mock = AsyncMock(return_value="temporal-schedule-id-123")
        monkeypatch.setattr("app.api.v1.workflows.create_workflow_schedule", schedule_mock)
        monkeypatch.setattr("app.api.v1.workflows.delete_workflow_schedule", AsyncMock(return_value=None))

        try:
            resp = await async_client.post(
                f"/api/v1/workflows/{workflow_id}/triggers",
                json={"trigger_type": "schedule", "trigger_config": {"cron": "0 9 * * *", "timezone": "UTC"}},
                headers=auth_headers,
            )
            assert resp.status_code == 201
            assert schedule_mock.call_count == 1
            assert resp.json()["trigger_config"]["temporal_schedule_ids"] == ["temporal-schedule-id-123"]
        finally:
            await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)


class TestHandleEventMatchesSupplementaryTriggers:
    async def test_supplementary_trigger_fires_alongside_different_primary(
        self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict, monkeypatch
    ):
        event_type = f"test.supplementary_{uuid.uuid4().hex[:8]}"
        workflow_id = await _create_manual_workflow(
            async_client, auth_headers, valid_definition, f"supp_fires_{uuid.uuid4().hex[:8]}",
        )
        await async_client.post(f"/api/v1/workflows/{workflow_id}/activate", headers=auth_headers)

        trigger_resp = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/triggers",
            json={"trigger_type": "internal_event", "trigger_config": {"event": event_type}},
            headers=auth_headers,
        )
        assert trigger_resp.status_code == 201

        trigger_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(listener_module, "_trigger_workflow_instance", trigger_mock)

        try:
            # user_id must match the workflow's owner (TEST_USER_ID) —
            # personal (no workspace_id) triggers only fire on their own
            # owner's events, see _event_belongs_to_workflow_owner.
            await listener_module._handle_event(event_type, {"user_id": str(TEST_USER_ID)})

            assert trigger_mock.call_count == 1
            called_workflow, _ = trigger_mock.call_args.args
            assert str(called_workflow.id) == workflow_id
        finally:
            await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)

    async def test_two_supplementary_triggers_same_event_different_filters(
        self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict, monkeypatch
    ):
        event_type = f"test.filters_{uuid.uuid4().hex[:8]}"
        workflow_id = await _create_manual_workflow(
            async_client, auth_headers, valid_definition, f"supp_filters_{uuid.uuid4().hex[:8]}",
        )
        await async_client.post(f"/api/v1/workflows/{workflow_id}/activate", headers=auth_headers)

        await async_client.post(
            f"/api/v1/workflows/{workflow_id}/triggers",
            json={"trigger_type": "internal_event", "trigger_config": {"event": event_type, "filters": {"kind": "a"}}},
            headers=auth_headers,
        )
        await async_client.post(
            f"/api/v1/workflows/{workflow_id}/triggers",
            json={"trigger_type": "internal_event", "trigger_config": {"event": event_type, "filters": {"kind": "b"}}},
            headers=auth_headers,
        )

        trigger_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(listener_module, "_trigger_workflow_instance", trigger_mock)

        try:
            await listener_module._handle_event(
                event_type, {"kind": "a", "user_id": str(TEST_USER_ID)},
            )
            assert trigger_mock.call_count == 1

            await listener_module._handle_event(
                event_type, {"kind": "neither", "user_id": str(TEST_USER_ID)},
            )
            assert trigger_mock.call_count == 1  # unchanged — matches neither filter
        finally:
            await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)

    async def test_supplementary_trigger_respects_cross_tenant_ownership_check(
        self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict, monkeypatch
    ):
        """Supplementary triggers must not reopen the cross-tenant leak
        fixed for primary triggers — same ownership check applies."""
        event_type = f"test.supp_ownership_{uuid.uuid4().hex[:8]}"
        workflow_id = await _create_manual_workflow(
            async_client, auth_headers, valid_definition, f"supp_owner_{uuid.uuid4().hex[:8]}",
        )
        await async_client.post(f"/api/v1/workflows/{workflow_id}/activate", headers=auth_headers)
        await async_client.post(
            f"/api/v1/workflows/{workflow_id}/triggers",
            json={"trigger_type": "internal_event", "trigger_config": {"event": event_type}},
            headers=auth_headers,
        )

        trigger_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(listener_module, "_trigger_workflow_instance", trigger_mock)

        try:
            other_user_id = str(uuid.uuid4())
            await listener_module._handle_event(event_type, {"user_id": other_user_id})

            assert trigger_mock.call_count == 0
        finally:
            await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)
