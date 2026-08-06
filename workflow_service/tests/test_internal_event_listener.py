"""
Transport-migration test for Task 1.2.4 (tasks/phase1/02_EVENT_BUS.md).

Verifies that `start_internal_event_listener()` correctly consumes the new
Redis Stream transport (`events:{type}`, consumer group "workflow_service")
that replaced the old `cortex:workflow:events` Pub/Sub channel, and that it
still finds/matches ACTIVE internal_event WorkflowDefinitions and invokes
`_trigger_workflow_instance` with the right data.

`_trigger_workflow_instance` is monkeypatched so this test never actually
starts a Temporal workflow execution (which would run the real
`action.create_note` node against the live Cortex backend and create a real
Note) — that is out of scope here; this test only proves the transport +
DB matching logic, not the full Temporal action pipeline.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient

from app.config import settings
from app.triggers import internal_event_listener as listener_module

pytestmark = pytest.mark.asyncio(loop_scope="session")

STREAM_KEY = "events:note.created"


@pytest.fixture
async def internal_event_workflow(async_client: AsyncClient, auth_headers: dict, valid_definition: dict):
    """Create + activate a workflow triggered by note.created, clean up after."""
    create_resp = await async_client.post(
        "/api/v1/workflows",
        json={
            "name": "test_internal_event_listener migration check",
            "trigger_type": "internal_event",
            "trigger_config": {"event": "note.created"},
            "definition": valid_definition,
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    workflow_id = create_resp.json()["id"]

    activate_resp = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/activate", headers=auth_headers
    )
    assert activate_resp.status_code == 200

    yield workflow_id

    await async_client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)


async def _publish_note_created_envelope(note_id: str) -> str:
    """Mimic backend's EventBus.publish() wire format without importing the
    backend package (different venv/service)."""
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    envelope = {
        "event_id": str(uuid.uuid4()),
        "type": "note.created",
        "source": "test_internal_event_listener",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": None,
        "user_id": None,
        "workspace_id": None,
        "conversation_id": None,
        "payload": {
            "note_id": note_id,
            "workspace_id": str(uuid.uuid4()),
            "title": "Test note from transport migration test",
            "content_type": "markdown",
        },
        "version": "1.0.0",
    }
    message_id = await redis.xadd(STREAM_KEY, {"data": json.dumps(envelope)})
    await redis.aclose()
    return message_id


@pytest.mark.slow
async def test_listener_consumes_stream_and_triggers_matching_workflow(
    internal_event_workflow, monkeypatch
):
    """
    Isolation note (found flaky 2026-08-06, fixed same day): `events:note.created`
    is the real production stream — by the time this test runs, the rest of
    the suite (and any real dev usage) has typically already written
    hundreds of real note.created entries to it. The listener's consumer
    group is named "workflow_service" — the same name production uses, and
    `_ensure_consumer_groups` creates it at id="0" (deliver-from-beginning),
    which is correct for production (a restarted listener must catch up on
    anything it missed) but wrong for this test: if any of that backlog
    accumulated *unread lag* since the last time this specific test ran
    (i.e. other tests created real notes in between), it all gets delivered
    to this run's listener, and every one of those historical notes matches
    this test's temporary workflow (scoped only on event="note.created",
    no other filter) — inflating trigger_mock.call_count above 1.
    Reproduced with call_count == 3 and once == 118 during Milestone 1.9/1.10
    development.

    Fix: use a throwaway consumer group unique to this test run (never the
    shared "workflow_service" name — never perturbs the real listener's
    cursor either), created directly at id="$" (tail — ignore all existing
    backlog) *before* the listener task starts. `_ensure_consumer_groups`
    then just hits BUSYGROUP for this stream (the group already exists) and
    leaves our id="$" cursor alone. Creating it first and fast-forwarding
    *after* a delay was tried and is racy: the listener's own group
    creation (id="0") starts draining backlog immediately, and since
    XREADGROUP only blocks when nothing is available, it can drain a good
    chunk of hundreds of backlogged real entries well before any post-hoc
    SETID call gets a chance to run.
    """
    workflow_id = internal_event_workflow

    test_group = f"test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(listener_module, "CONSUMER_GROUP", test_group)

    trigger_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(listener_module, "_trigger_workflow_instance", trigger_mock)

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    await redis.xgroup_create(STREAM_KEY, test_group, id="$", mkstream=True)

    listener_task = asyncio.create_task(listener_module.start_internal_event_listener())
    try:
        # Let the listener finish (no-op, BUSYGROUP) XGROUP CREATE for all
        # vocabulary streams and enter its blocking XREADGROUP.
        await asyncio.sleep(0.5)

        note_id = str(uuid.uuid4())
        message_id = await _publish_note_created_envelope(note_id)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and trigger_mock.call_count == 0:
            await asyncio.sleep(0.1)

        assert trigger_mock.call_count == 1, "listener did not pick up the event within 5s"

        called_workflow, called_trigger_data = trigger_mock.call_args.args
        assert str(called_workflow.id) == workflow_id
        assert called_trigger_data["note_id"] == note_id
        assert called_trigger_data["title"] == "Test note from transport migration test"
    finally:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        await redis.xdel(STREAM_KEY, message_id)
        try:
            await redis.xgroup_destroy(STREAM_KEY, test_group)
        except Exception:
            pass
        await redis.aclose()


async def _publish_test_envelope(event_type: str) -> str:
    """Same wire-format helper as _publish_note_created_envelope, but for an
    arbitrary event type with an empty payload."""
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    envelope = {
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "source": "test_internal_event_listener",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": None,
        "user_id": None,
        "workspace_id": None,
        "conversation_id": None,
        "payload": {},
        "version": "1.0.0",
    }
    message_id = await redis.xadd(f"events:{event_type}", {"data": json.dumps(envelope)})
    await redis.aclose()
    return message_id


@pytest.mark.slow
async def test_listener_picks_up_new_event_type_without_restart(tmp_path, monkeypatch):
    """Milestone 1.9, Task 1.9.3: adding an event type to the vocabulary
    (simulated here by rewriting the vocabulary file the running listener
    reads from) must be picked up on the next periodic reload — no restart,
    no listener code change.

    Uses fully unique `test.*` event types (never `note.created` or any
    real vocabulary type) so this never collides with the fixed
    "workflow_service" consumer group's backlog on the real streams — the
    shared dev Redis instance has plenty of real `events:note.created`
    traffic from the rest of the test suite, and a fresh consumer group
    reading from id="0" would drain all of that backlog before ever
    reaching this test's assertions.
    """
    run_id = uuid.uuid4().hex[:8]
    initial_event_type = f"test.vocab_reload_initial_{run_id}"
    new_event_type = f"test.vocab_reload_added_{run_id}"

    vocab_path = tmp_path / "event_vocabulary.json"
    vocab_path.write_text(json.dumps({
        "_generated_by": "test",
        "_source": "test",
        "event_types": [
            {"event_type": initial_event_type, "description": "", "has_payload_schema": True},
        ],
    }))

    monkeypatch.setattr(listener_module, "VOCABULARY_PATH", vocab_path)
    monkeypatch.setattr(listener_module, "VOCABULARY_RELOAD_SECONDS", 0.3)

    handle_event_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(listener_module, "_handle_event", handle_event_mock)

    listener_task = asyncio.create_task(listener_module.start_internal_event_listener())
    try:
        # Let it finish initial XGROUP CREATE + enter the blocking read.
        await asyncio.sleep(0.3)

        # Simulate a vocabulary regeneration that adds the new event type.
        vocab_path.write_text(json.dumps({
            "_generated_by": "test",
            "_source": "test",
            "event_types": [
                {"event_type": initial_event_type, "description": "", "has_payload_schema": True},
                {"event_type": new_event_type, "description": "", "has_payload_schema": True},
            ],
        }))

        # Wait past one reload interval so the listener notices the change
        # and creates a consumer group for the new stream.
        await asyncio.sleep(0.6)

        await _publish_test_envelope(new_event_type)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and handle_event_mock.call_count == 0:
            await asyncio.sleep(0.1)

        assert handle_event_mock.call_count == 1, (
            "listener never picked up the new event type after a vocabulary reload"
        )
        called_event_type, _called_data = handle_event_mock.call_args.args
        assert called_event_type == new_event_type
    finally:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await redis.delete(f"events:{initial_event_type}")
        await redis.delete(f"events:{new_event_type}")
        await redis.aclose()
