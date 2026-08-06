import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestWebhookWorkflow:
    WEBHOOK_WF_PAYLOAD = {
        "name": "Webhook WF",
        "trigger_type": "webhook",
        "definition": {
            "nodes": [
                {"id": "t1", "type": "trigger.webhook", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "a1", "type": "action.create_note", "position": {"x": 200, "y": 0}, "data": {}},
            ],
            "edges": [{"id": "e1", "source": "t1", "target": "a1"}],
            "variables": {},
        },
    }

    async def _create_and_activate(self, client: AsyncClient, headers: dict) -> tuple[str, str, str]:
        create_resp = await client.post("/api/v1/workflows", json=self.WEBHOOK_WF_PAYLOAD, headers=headers)
        assert create_resp.status_code == 201
        data = create_resp.json()
        wf_id = data["id"]
        webhook_url = data["webhook_url"]
        secret = data["webhook_secret"]

        await client.post(f"/api/v1/workflows/{wf_id}/activate", headers=headers)
        return wf_id, webhook_url, secret

    async def test_webhook_with_correct_secret(self, async_client: AsyncClient, auth_headers: dict):
        _, url, secret = await self._create_and_activate(async_client, auth_headers)
        resp = await async_client.post(url, json={"test": True}, headers={"X-Webhook-Secret": secret})
        assert resp.status_code == 202

    async def test_webhook_wrong_secret(self, async_client: AsyncClient, auth_headers: dict):
        _, url, _ = await self._create_and_activate(async_client, auth_headers)
        resp = await async_client.post(url, json={"test": True}, headers={"X-Webhook-Secret": "wrong"})
        assert resp.status_code == 401

    async def test_webhook_no_secret(self, async_client: AsyncClient, auth_headers: dict):
        _, url, _ = await self._create_and_activate(async_client, auth_headers)
        resp = await async_client.post(url, json={"test": True})
        assert resp.status_code == 202

    async def test_webhook_not_active_returns_409(self, async_client: AsyncClient, auth_headers: dict):
        create_resp = await async_client.post("/api/v1/workflows", json=self.WEBHOOK_WF_PAYLOAD, headers=auth_headers)
        url = create_resp.json()["webhook_url"]

        resp = await async_client.post(url, json={"test": True})
        assert resp.status_code == 409

    async def test_webhook_not_found(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/webhooks/nonexistentpath1234567890", json={"test": True})
        assert resp.status_code == 404
