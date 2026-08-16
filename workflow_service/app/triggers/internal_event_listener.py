"""
Internal event trigger — listens for Cortex domain events and starts matching
workflows.

Transport (2026-08-06): migrated from Redis Pub/Sub (`cortex:workflow:events`)
to Redis Streams (`events:{type}`), consumed via a dedicated consumer group
("workflow_service"). This is the same EventBus/stream format published by
`backend/app/events/event_bus.py` (see tasks/phase1/02_EVENT_BUS.md, Task
1.2.4). The old Pub/Sub publisher (`backend/app/services/redis/
workflow_event_publisher.py`) had zero callers and has been removed —
nothing publishes to `cortex:workflow:events` anymore.

Vocabulary (2026-08-06, Milestone 1.9): the event type list used to be a
hardcoded `SUPPORTED_EVENTS` here that had already drifted from the
backend's own `EVENT_PAYLOAD_REGISTRY` — 3 event types the backend
publishes were never listened for here, and this listened for 2 the backend
never publishes. `SUPPORTED_EVENTS` is now generated from
`backend/app/events/vocabulary.py` (the single source of truth) via
`backend/scripts/generate_event_vocabulary.py` into the checked-in
`event_vocabulary.json` next to this file — see that module's docstring for
why this is a generated file rather than a live cross-service import.
The listener also reloads that file periodically (`VOCABULARY_RELOAD_SECONDS`)
and creates consumer groups for any newly-appeared event types on the fly,
so adding an event type to the vocabulary + regenerating the JSON is enough
— no listener code change and no restart required (Task 1.9.3).

`_matches_filters` / `_trigger_workflow_instance` are unchanged from the
original implementation; only the ingestion transport and vocabulary source
changed. `_handle_event` itself has since been updated: Milestone 4.0 M2
moved event-type matching into the SQL WHERE clause, and M1 added a
per-workspace enable/fork check for system-owned workflow rows.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy import select

from app.config import settings
from app.models.workflow import WorkflowDefinition, WorkflowStatus, TriggerType, SYSTEM_WORKFLOW_USER_ID, WorkflowTrigger
from app.database import AsyncSessionLocal
from app.services.system_workflows import is_system_workflow_active_for_workspace

STREAM_PREFIX = "events:"
CONSUMER_GROUP = "workflow_service"
CONSUMER_NAME = "listener-1"

# Retry + DLQ for _handle_event failures (Milestone 4.1 M3), mirroring the
# backend's own EventBus mechanism (backend/app/events/event_bus.py's
# MAX_RETRIES/RETRY_DELAYS/DLQ pattern) rather than inventing a second one.
# Own DLQ stream, not the backend's, to avoid mixing dlq_metadata shapes
# from two different retry mechanisms in the same Redis stream.
MAX_RETRIES = 3
RETRY_DELAYS = [1, 5, 15]
DLQ_STREAM = "events:dead-letter-workflow"

VOCABULARY_PATH = Path(__file__).parent / "event_vocabulary.json"
VOCABULARY_RELOAD_SECONDS = 30


def load_supported_events() -> list[str]:
    """Read the full event type list (including reserved/not-yet-implemented
    entries) from the generated vocabulary file — used by the consumer loop,
    which just needs to know which streams to create groups for.

    Raises if the file is missing/malformed rather than silently falling
    back to an empty list — an empty SUPPORTED_EVENTS would mean the
    listener starts and does nothing, with no error anywhere, exactly the
    kind of silent failure this milestone exists to eliminate.
    """
    with open(VOCABULARY_PATH) as f:
        data = json.load(f)
    return sorted(entry["event_type"] for entry in data["event_types"])


def load_implemented_event_types() -> list[str]:
    """Event types with `has_payload_schema: true` — i.e. something in the
    backend actually publishes them today. Used by the public trigger-catalog
    API (app/api/v1/actions.py) so users can't build a workflow trigger on an
    event type nothing will ever emit."""
    with open(VOCABULARY_PATH) as f:
        data = json.load(f)
    return sorted(
        entry["event_type"] for entry in data["event_types"] if entry["has_payload_schema"]
    )


def load_trigger_catalog() -> list[dict]:
    """Milestone 4.2 — the same `has_payload_schema` set as
    `load_implemented_event_types()`, but with the fields a workflow
    builder UI needs to render a real list instead of bare event-type
    strings: `label_vi` (short user-facing label, generated from
    `backend/app/events/vocabulary.py`) and `has_direct_backend_delivery`
    (A3 — warn before the user even picks this trigger, not just at
    activate). Replaces the frontend's own hardcoded `EVENT_TYPES` array
    (`InternalEventTriggerConfig.tsx`), which was exactly the kind of
    second, independently-maintained list 1.9 already fixed once between
    the backend and workflow_service."""
    with open(VOCABULARY_PATH) as f:
        data = json.load(f)
    return sorted(
        (
            {
                "event_type": entry["event_type"],
                "label_vi": entry["label_vi"],
                "has_direct_backend_delivery": entry["has_direct_backend_delivery"],
            }
            for entry in data["event_types"]
            if entry["has_payload_schema"]
        ),
        key=lambda e: e["event_type"],
    )


async def _ensure_consumer_groups(redis: aioredis.Redis, event_types: list[str]) -> None:
    for event_type in event_types:
        stream_key = f"{STREAM_PREFIX}{event_type}"
        try:
            await redis.xgroup_create(stream_key, CONSUMER_GROUP, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise


async def start_internal_event_listener():
    """
    Consume `events:{type}` Redis Streams via a dedicated consumer group and
    trigger matching workflows. Runs until cancelled (see app/main.py lifespan).

    The vocabulary (which event types to listen on) is reloaded every
    VOCABULARY_RELOAD_SECONDS; newly-added types get their consumer group
    created and are added to the next XREADGROUP call without restarting
    this loop.
    """
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    supported_events = load_supported_events()
    await _ensure_consumer_groups(redis, supported_events)
    streams = {f"{STREAM_PREFIX}{t}": ">" for t in supported_events}

    print(f"[TriggerEngine] Listening on Redis Streams: {supported_events}")

    last_reload = time.monotonic()

    try:
        while True:
            if time.monotonic() - last_reload >= VOCABULARY_RELOAD_SECONDS:
                last_reload = time.monotonic()
                try:
                    reloaded = load_supported_events()
                except Exception as e:
                    print(f"[TriggerEngine] Vocabulary reload failed, keeping current list: {e}")
                    reloaded = supported_events

                added = sorted(set(reloaded) - set(supported_events))
                removed = sorted(set(supported_events) - set(reloaded))
                if added or removed:
                    if added:
                        await _ensure_consumer_groups(redis, added)
                    supported_events = reloaded
                    streams = {f"{STREAM_PREFIX}{t}": ">" for t in supported_events}
                    print(
                        f"[TriggerEngine] Vocabulary reloaded — added={added} removed={removed} "
                        f"now_listening={supported_events}"
                    )

            try:
                result = await redis.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=CONSUMER_NAME,
                    streams=streams,
                    count=10,
                    block=5000,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[TriggerEngine] xreadgroup error: {e}")
                await asyncio.sleep(1)
                continue

            for stream_key, messages in result or []:
                event_type = stream_key.removeprefix(STREAM_PREFIX)
                for message_id, fields in messages:
                    try:
                        envelope = json.loads(fields["data"])
                    except (KeyError, json.JSONDecodeError) as e:
                        print(f"[TriggerEngine] Malformed message {message_id}, acking and dropping: {e}")
                        await redis.xack(stream_key, CONSUMER_GROUP, message_id)
                        continue

                    event_data = dict(envelope.get("payload") or {})
                    if envelope.get("user_id"):
                        event_data.setdefault("user_id", envelope["user_id"])
                    if envelope.get("workspace_id"):
                        event_data.setdefault("workspace_id", envelope["workspace_id"])

                    last_error: Exception | None = None
                    for attempt in range(MAX_RETRIES):
                        try:
                            await _handle_event(event_type, event_data)
                            last_error = None
                            break
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            last_error = e
                            print(
                                f"[TriggerEngine] _handle_event failed "
                                f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}"
                            )
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAYS[attempt])

                    if last_error is not None:
                        await _send_to_dlq(redis, envelope, last_error)

                    await redis.xack(stream_key, CONSUMER_GROUP, message_id)
    finally:
        await redis.aclose()


async def _send_to_dlq(redis: aioredis.Redis, envelope: dict, error: Exception) -> None:
    """Last resort after MAX_RETRIES failures: record the event + error
    instead of silently dropping it (the previous behavior — `xack` ran in
    `finally` regardless of outcome). Mirrors backend's EventBus._send_to_dlq
    shape (backend/app/events/event_bus.py) without importing across the
    service boundary (see this module's docstring for why)."""
    dlq_data = {
        **envelope,
        "dlq_metadata": {
            "failed_handler": "_handle_event",
            "error": str(error),
            "error_type": type(error).__name__,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "original_event_id": envelope.get("event_id"),
            "retry_count": MAX_RETRIES,
        },
    }
    try:
        await redis.xadd(DLQ_STREAM, {"data": json.dumps(dlq_data)})
        print(f"[TriggerEngine] Event sent to DLQ: {envelope.get('type')} ({envelope.get('event_id')})")
    except Exception as dlq_exc:
        print(f"[TriggerEngine] CRITICAL: failed to send event to DLQ: {dlq_exc}")


def _event_belongs_to_workflow_owner(workflow: WorkflowDefinition, event_data: dict) -> bool:
    """A non-system workflow only fires on data it's actually allowed to
    see. `Workspace`/`WorkspaceMember` (backend/app/models.py) is a real
    shared, multi-user entity, so a workspace-scoped workflow reacting to
    any member's action is intentional (team automation) — not a workflow
    matching purely on event_type with no ownership check at all, which is
    what let user A's workflow run on user B's data as long as the event
    type happened to match.

    workspace_id set on the workflow -> same workspace, any member.
    workspace_id unset (the common case for workflows made via the UI) ->
    same user as the workflow owner. No data to compare -> fail closed.

    No backend event publisher currently sets `workspace_id` on
    `EventEnvelope` — every domain entity behind today's event types (Task,
    Note, Schedule, ...) is user-scoped only, with no workspace_id column at
    all (see e.g. `Task` in backend/app/models.py). So a workspace-scoped
    workflow would otherwise never fire from a real event: the event's
    workspace_id is always None, which can never equal a real UUID. Falling
    back to the same user-ownership check as a personal workflow when the
    event carries no workspace_id keeps this at least as restrictive as the
    non-workspace branch below (no cross-user leak) while making
    workspace-scoped workflows over today's event types actually work."""
    if workflow.workspace_id is not None:
        event_workspace_id = event_data.get("workspace_id")
        if event_workspace_id is not None:
            return str(event_workspace_id) == str(workflow.workspace_id)

    event_user_id = event_data.get("user_id")
    return event_user_id is not None and str(event_user_id) == str(workflow.user_id)


async def _handle_event(event_type: str, event_data: dict):
    async with AsyncSessionLocal() as db:
        # Match on trigger_config->>'event' in SQL (Milestone 4.0 M2) instead
        # of loading every ACTIVE internal_event workflow and filtering in
        # Python — the old version scanned the whole table on every event.
        primary_result = await db.execute(
            select(WorkflowDefinition).where(
                WorkflowDefinition.status == WorkflowStatus.ACTIVE,
                WorkflowDefinition.trigger_type == TriggerType.INTERNAL_EVENT,
                WorkflowDefinition.is_deleted == False,
                WorkflowDefinition.trigger_config["event"].as_string() == event_type,
            )
        )
        matches = [(wf, wf.trigger_config) for wf in primary_result.scalars().all()]

        # Supplementary triggers (multi-trigger support): a workflow whose
        # primary trigger is something else (or even another internal_event
        # with different filters) can still react to this event type via a
        # row in workflow_triggers. Each row carries its own trigger_config,
        # so it's matched — and its own `filters` applied — independently
        # of the workflow's primary trigger.
        supplementary_result = await db.execute(
            select(WorkflowDefinition, WorkflowTrigger.trigger_config)
            .join(WorkflowTrigger, WorkflowTrigger.workflow_id == WorkflowDefinition.id)
            .where(
                WorkflowDefinition.status == WorkflowStatus.ACTIVE,
                WorkflowDefinition.is_deleted == False,
                WorkflowTrigger.trigger_type == TriggerType.INTERNAL_EVENT,
                WorkflowTrigger.is_active == True,
                WorkflowTrigger.trigger_config["event"].as_string() == event_type,
            )
        )
        matches.extend(supplementary_result.all())

        for workflow, trigger_config in matches:
            filters = trigger_config.get("filters", {})
            if not _matches_filters(event_data, filters):
                continue

            if workflow.user_id == SYSTEM_WORKFLOW_USER_ID:
                # Milestone 4.0 M1: a system workflow can be disabled or
                # forked per workspace. Its fork (if any) is a normal row
                # that already matched the WHERE clause above on its own.
                workspace_id = event_data.get("workspace_id")
                active = await is_system_workflow_active_for_workspace(
                    db, workflow_id=workflow.id, workspace_id=workspace_id,
                )
                if not active:
                    continue
            elif not _event_belongs_to_workflow_owner(workflow, event_data):
                continue

            await _trigger_workflow_instance(workflow, event_data)
            print(f"[TriggerEngine] Triggered workflow {workflow.id} for event {event_type}")


def _matches_filters(event_data: dict, filters: dict) -> bool:
    for key, value in filters.items():
        if event_data.get(key) != value:
            return False
    return True


async def _trigger_workflow_instance(workflow: WorkflowDefinition, trigger_data: dict):
    from app.temporal.client import start_workflow_execution

    instance_id = await start_workflow_execution(workflow, trigger_data)
    print(
        f"[TriggerEngine] Triggered workflow {workflow.id} "
        f"instance={instance_id}"
    )
