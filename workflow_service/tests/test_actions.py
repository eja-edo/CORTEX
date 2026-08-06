import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestActionsCatalog:
    async def test_list_actions(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/actions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data
        assert "triggers" in data
        assert len(data["actions"]) == 9  # All 9 built-in action types
        assert len(data["triggers"]) == 3

    async def test_list_actions_no_auth_returns_403(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/actions")
        assert resp.status_code == 403

    async def test_actions_contain_create_note(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/actions", headers=auth_headers)
        types = {a["type"] for a in resp.json()["actions"]}
        assert "action.create_note" in types
        assert "action.send_notification" in types

    async def test_triggers_contain_expected_types(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/actions", headers=auth_headers)
        types = {t["type"] for t in resp.json()["triggers"]}
        assert "trigger.internal_event" in types
        assert "trigger.webhook" in types
        assert "trigger.manual" in types
