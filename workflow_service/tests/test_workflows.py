import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestCreateWorkflow:
    async def test_create_internal_event(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        resp = await async_client.post(
            "/api/v1/workflows",
            json={
                "name": "Test WF",
                "trigger_type": "internal_event",
                "trigger_config": {"event": "note.created"},
                "definition": valid_definition,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test WF"
        assert data["status"] == "draft"
        assert data["version"] == 1
        assert data["trigger_type"] == "internal_event"
        assert "id" in data

    async def test_create_webhook_returns_secret(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        resp = await async_client.post(
            "/api/v1/workflows",
            json={
                "name": "Webhook WF",
                "trigger_type": "webhook",
                "definition": valid_definition,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["webhook_url"] is not None
        assert data["webhook_secret"] is not None
        assert data["webhook_url"].startswith("/api/v1/webhooks/")

    async def test_create_manual_no_trigger_config(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Manual WF", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["trigger_type"] == "manual"

    async def test_create_missing_name_returns_422(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        resp = await async_client.post(
            "/api/v1/workflows",
            json={"trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestListWorkflows:
    async def test_list(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        await async_client.post(
            "/api/v1/workflows",
            json={"name": "WF1", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        await async_client.post(
            "/api/v1/workflows",
            json={"name": "WF2", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )

        resp = await async_client.get("/api/v1/workflows", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total"] >= 2
        assert len(data["items"]) >= 2

    async def test_list_pagination(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        resp = await async_client.get("/api/v1/workflows?page=1&page_size=1", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 1
        assert len(data["items"]) <= 1

    async def test_list_no_auth_returns_403(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/workflows")
        assert resp.status_code == 403


class TestGetWorkflow:
    async def test_get_by_id(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Get Test", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]

        resp = await async_client.get(f"/api/v1/workflows/{wf_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Get Test"

    async def test_get_not_found(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/workflows/00000000-0000-0000-0000-000000000000", headers=auth_headers)
        assert resp.status_code == 404

    async def test_get_wrong_user_returns_404(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Wrong User", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]

        from jose import jwt as _jwt
        other_token = _jwt.encode(
            {"sub": "ffffffff-ffff-ffff-ffff-ffffffffffff", "exp": 9999999999},
            "change-this-in-production-super-secret-key",
            algorithm="HS256",
        )
        resp = await async_client.get(
            f"/api/v1/workflows/{wf_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404


class TestUpdateWorkflow:
    async def test_update_name(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Old Name", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]

        resp = await async_client.patch(
            f"/api/v1/workflows/{wf_id}",
            json={"name": "New Name"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_update_definition_bumps_version_when_active(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Version Bump", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]
        assert create_resp.json()["version"] == 1

        await async_client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)

        new_definition = {**valid_definition, "variables": {"key": "val"}}
        resp = await async_client.patch(
            f"/api/v1/workflows/{wf_id}",
            json={"definition": new_definition},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 2


class TestActivateWorkflow:
    async def test_activate_valid(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Activate Me", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]

        resp = await async_client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    async def test_activate_no_trigger_nodes_returns_400(self, async_client: AsyncClient, auth_headers: dict):
        definition = {
            "nodes": [{"id": "a1", "type": "action.create_note", "position": {"x": 0, "y": 0}, "data": {}}],
            "edges": [],
            "variables": {},
        }
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "No Trigger", "trigger_type": "manual", "definition": definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]

        resp = await async_client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)
        assert resp.status_code == 400

    async def test_activate_no_action_nodes_returns_400(self, async_client: AsyncClient, auth_headers: dict):
        definition = {
            "nodes": [{"id": "t1", "type": "trigger.manual", "position": {"x": 0, "y": 0}, "data": {}}],
            "edges": [],
            "variables": {},
        }
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "No Action", "trigger_type": "manual", "definition": definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]

        resp = await async_client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)
        assert resp.status_code == 400

    async def test_pause_workflow(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Pause Me", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]

        await async_client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)
        resp = await async_client.post(f"/api/v1/workflows/{wf_id}/pause", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"


class TestDeleteWorkflow:
    async def test_soft_delete_returns_204(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Delete Me", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]

        resp = await async_client.delete(f"/api/v1/workflows/{wf_id}", headers=auth_headers)
        assert resp.status_code == 204

    async def test_deleted_workflow_returns_404(self, async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
        create_resp = await async_client.post(
            "/api/v1/workflows",
            json={"name": "Gone", "trigger_type": "manual", "definition": valid_definition},
            headers=auth_headers,
        )
        wf_id = create_resp.json()["id"]

        await async_client.delete(f"/api/v1/workflows/{wf_id}", headers=auth_headers)
        resp = await async_client.get(f"/api/v1/workflows/{wf_id}", headers=auth_headers)
        assert resp.status_code == 404
