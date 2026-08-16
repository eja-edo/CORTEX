import pytest
from httpx import AsyncClient

from app.models.workflow import TriggerType

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestActionsCatalog:
    async def test_list_actions(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/actions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data
        assert "triggers" in data
        assert len(data["actions"]) == 15  # All 15 built-in action types
        assert len(data["triggers"]) == 3

    async def test_list_actions_no_auth_returns_403(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/actions")
        assert resp.status_code == 403

    async def test_actions_contain_create_note(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/actions", headers=auth_headers)
        types = {a["type"] for a in resp.json()["actions"]}
        assert "action.create_note" in types
        assert "action.send_notification" in types
        assert "action.request_attention" in types
        assert "action.call_api" in types
        assert "action.extract_html" in types
        assert "action.get_schedules" in types
        assert "action.create_task" in types
        assert "action.update_task" in types

    async def test_triggers_contain_expected_types(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/actions", headers=auth_headers)
        types = {t["type"] for t in resp.json()["triggers"]}
        assert "trigger.internal_event" in types
        assert "trigger.webhook" in types
        assert "trigger.manual" in types


class TestTriggerCatalog:
    """Milestone 4.2 — GET /api/v1/actions/triggers/catalog."""

    async def test_requires_auth(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/actions/triggers/catalog")
        assert resp.status_code == 403

    async def test_returns_every_implemented_event_with_a_label(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/actions/triggers/catalog", headers=auth_headers)
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) > 0

        by_event = {e["event_type"]: e for e in entries}
        assert "task.overdue" in by_event
        assert by_event["task.overdue"]["label_vi"]
        assert by_event["task.overdue"]["has_direct_backend_delivery"] is True

        # Reserved events (asset.uploaded/processed) have no payload schema
        # yet — must not appear as a pickable trigger.
        assert "asset.uploaded" not in by_event
        assert "asset.processed" not in by_event

    async def test_sorted_by_event_type(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/actions/triggers/catalog", headers=auth_headers)
        event_types = [e["event_type"] for e in resp.json()]
        assert event_types == sorted(event_types)

    async def test_catalog_grows_without_a_new_trigger_type(self, async_client: AsyncClient, auth_headers: dict):
        """Bản 2's 4.2 M4: the catalog is data (rows in a JSON file), not
        code — a 20th entry must not require a 5th `TriggerType`. Everything
        new is `INTERNAL_EVENT`; only `trigger_config["event"]` changes."""
        resp = await async_client.get("/api/v1/actions/triggers/catalog", headers=auth_headers)
        assert len(resp.json()) >= 15
        assert len(TriggerType) == 4
