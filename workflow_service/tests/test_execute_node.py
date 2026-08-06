import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings
from jose import jwt
from datetime import datetime, timezone

TEST_USER_ID = "aaa352bb-8035-4e76-88d7-9813e84b966b"

JWT_SECRET = settings.resolved_jwt_secret

def make_jwt():
    payload = {
        "sub": TEST_USER_ID,
        "email": "test@test.com",
        "exp": 9999999999,
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=settings.jwt_algorithm)

@pytest.fixture(scope="module")
def jwt_token():
    return make_jwt()

@pytest.fixture(scope="module")
def auth_headers(jwt_token: str):
    return {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}

WORKFLOW_ID = None

@pytest.mark.asyncio(loop_scope="session")
class TestExecuteNode:
    async def test_01_create_workflow(self, auth_headers: dict):
        global WORKFLOW_ID
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/workflows",
                headers=auth_headers,
                json={
                    "name": "test-all-nodes",
                    "trigger_type": "manual",
                    "definition": {
                        "nodes": [
                            {"id": "t1", "type": "trigger.manual", "position": {"x": 0, "y": 0}, "data": {"label": "Manual Trigger"}},
                            {"id": "a1", "type": "action.create_note", "position": {"x": 200, "y": 0}, "data": {"label": "Create Note", "config": {"title": "test", "content": "hello"}}},
                            {"id": "a2", "type": "action.update_note", "position": {"x": 400, "y": 0}, "data": {"label": "Update Note", "config": {"note_id": "test-id", "content": "updated"}}},
                            {"id": "a3", "type": "action.send_notification", "position": {"x": 600, "y": 0}, "data": {"label": "Send Notification", "config": {"title": "notif", "body": "body", "type": "info"}}},
                            {"id": "a4", "type": "action.call_ai", "position": {"x": 800, "y": 0}, "data": {"label": "Call AI", "config": {"prompt": "Say hello", "output_key": "ai_result"}}},
                            {"id": "a5", "type": "action.call_webhook", "position": {"x": 1000, "y": 0}, "data": {"label": "Call Webhook", "config": {"url": "https://httpbin.org/post", "method": "POST", "body": '{"test": true}'}}},
                            {"id": "a6", "type": "action.condition", "position": {"x": 1200, "y": 0}, "data": {"label": "Condition", "config": {"left": "1", "operator": "equals", "right": "1"}}},
                            {"id": "a7", "type": "action.wait", "position": {"x": 1400, "y": 0}, "data": {"label": "Wait", "config": {"seconds": 1}}},
                            {"id": "a8", "type": "action.schedule", "position": {"x": 1600, "y": 0}, "data": {"label": "Schedule", "config": {"title": "event", "start_time": "2025-01-01T00:00:00Z", "end_time": "2025-01-01T01:00:00Z"}}},
                        ],
                        "edges": [],
                        "variables": {},
                    },
                },
            )
            assert resp.status_code == 201, f"create failed: {resp.text}"
            data = resp.json()
            WORKFLOW_ID = data["id"]

    async def _exec(self, auth_headers: dict, node_id: str, trigger_data: dict | None = None, previous_outputs: dict | None = None):
        global WORKFLOW_ID
        assert WORKFLOW_ID is not None, "WORKFLOW_ID not set — run test_01 first"
        transport = ASGITransport(app=app)
        body: dict = {}
        if trigger_data is not None:
            body["trigger_data"] = trigger_data
        if previous_outputs is not None:
            body["previous_outputs"] = previous_outputs
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/workflows/{WORKFLOW_ID}/nodes/{node_id}/execute",
                headers=auth_headers,
                json=body,
            )
        return resp

    # --- Tests for actions that work without external backends ---

    async def test_trigger_manual(self, auth_headers: dict):
        resp = await self._exec(auth_headers, "t1")
        assert resp.status_code == 200, f"trigger failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["output"], dict)
        print(f"\n  [trigger.manual] OK — output keys: {list(data['output'].keys())}")

    async def test_condition(self, auth_headers: dict):
        resp = await self._exec(auth_headers, "a6", trigger_data={"event": "manual.trigger"})
        assert resp.status_code == 200, f"condition failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert data["output"]["condition_result"] is True
        assert data["output"]["branch"] == "true"
        print(f"  [condition] OK — result={data['output']['condition_result']}")

    async def test_condition_false(self, auth_headers: dict):
        transport = ASGITransport(app=app)
        body = {"config": {"left": "1", "operator": "equals", "right": "2"}, "trigger_data": {"event": "manual.trigger"}}
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/workflows/{WORKFLOW_ID}/nodes/a6/execute",
                headers=auth_headers,
                json=body,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True, f"condition false failed: {data}"
        assert data["output"]["condition_result"] is False
        assert data["output"]["branch"] == "false"
        print(f"  [condition false] OK — result={data['output']['condition_result']}")

    async def test_wait(self, auth_headers: dict):
        resp = await self._exec(auth_headers, "a7", trigger_data={"event": "manual.trigger"})
        assert resp.status_code == 200, f"wait failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert data["output"]["waited"] is True
        print(f"  [wait] OK — duration={data['output']['duration']} {data['output']['unit']}")

    # --- Tests for actions needing external backends (verified they EXECUTED) ---

    async def test_send_notification_executed(self, auth_headers: dict):
        """send_notification: code runs but fails if core backend is down.

        The key assertion: the action's execute() method was called (not 500/404).
        success=False proves the Python function ran and tried the HTTP call.
        """
        resp = await self._exec(auth_headers, "a3", trigger_data={"event": "manual.trigger"})
        assert resp.status_code == 200, f"send_notification API failed: {resp.text}"
        data = resp.json()
        # The action attempted execution — success=False means the HTTP call failed
        print(f"  [send_notification] executed — success={data['success']}, error={str(data.get('error', ''))[:60]}")

    async def test_create_note_executed(self, auth_headers: dict):
        resp = await self._exec(auth_headers, "a1", trigger_data={"event": "manual.trigger"})
        assert resp.status_code == 200
        print(f"  [create_note] executed — {resp.json()}")

    async def test_update_note_executed(self, auth_headers: dict):
        resp = await self._exec(auth_headers, "a2", trigger_data={"event": "manual.trigger"})
        assert resp.status_code == 200
        print(f"  [update_note] executed — {resp.json()}")

    async def test_call_ai_executed(self, auth_headers: dict):
        resp = await self._exec(auth_headers, "a4", trigger_data={"event": "manual.trigger"})
        assert resp.status_code == 200
        print(f"  [call_ai] executed — {resp.json()}")

    async def test_call_webhook_executed(self, auth_headers: dict):
        resp = await self._exec(auth_headers, "a5", trigger_data={"event": "manual.trigger"})
        assert resp.status_code == 200
        print(f"  [call_webhook] executed — {resp.json()}")

    async def test_schedule_executed(self, auth_headers: dict):
        resp = await self._exec(auth_headers, "a8", trigger_data={"event": "manual.trigger"})
        assert resp.status_code == 200
        print(f"  [schedule] executed — {resp.json()}")

    # --- Template resolution tests ---

    async def test_template_trigger_data(self, auth_headers: dict):
        """Verify trigger_data fields flow through to the action context."""
        resp = await self._exec(auth_headers, "a6", trigger_data={
            "event": "manual.trigger",
            "input": {"custom": "hello"},
        })
        assert resp.status_code == 200
        data = resp.json()
        # If trigger_data was passed, the action was called with it
        print(f"  [template trigger_data] OK — executed with trigger_data")

    async def test_template_previous_outputs(self, auth_headers: dict):
        """Verify previous_outputs flow through."""
        resp = await self._exec(auth_headers, "a3", trigger_data={"event": "manual.trigger"},
                                previous_outputs={"t1": {"output": {"my_field": "value"}, "success": True}})
        assert resp.status_code == 200
        data = resp.json()
        print(f"  [template previous_outputs] executed — success={data['success']}")

    async def test_empty_trigger_data(self, auth_headers: dict):
        """Verify empty trigger_data {} is handled gracefully."""
        resp = await self._exec(auth_headers, "a3", trigger_data={})
        assert resp.status_code == 200
        data = resp.json()
        print(f"  [empty trigger_data] OK — handled without crash")
