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

`_handle_event` / `_matches_filters` / `_trigger_workflow_instance` are
unchanged from the previous implementation; only the ingestion transport
and vocabulary source changed.
"""

import asyncio
import json
import time
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy import select

from app.config import settings
from app.models.workflow import WorkflowDefinition, WorkflowStatus, TriggerType
from app.database import AsyncSessionLocal

STREAM_PREFIX = "events:"
CONSUMER_GROUP = "workflow_service"
CONSUMER_NAME = "listener-1"

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
                        event_data = dict(envelope.get("payload") or {})
                        if envelope.get("user_id"):
                            event_data.setdefault("user_id", envelope["user_id"])
                        await _handle_event(event_type, event_data)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"[TriggerEngine] Error handling event: {e}")
                    finally:
                        await redis.xack(stream_key, CONSUMER_GROUP, message_id)
    finally:
        await redis.aclose()


async def _handle_event(event_type: str, event_data: dict):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkflowDefinition).where(
                WorkflowDefinition.status == WorkflowStatus.ACTIVE,
                WorkflowDefinition.trigger_type == TriggerType.INTERNAL_EVENT,
                WorkflowDefinition.is_deleted == False
            )
        )
        workflows = result.scalars().all()

        for workflow in workflows:
            trigger_config = workflow.trigger_config
            configured_event = trigger_config.get("event")

            if configured_event != event_type:
                continue

            filters = trigger_config.get("filters", {})
            if not _matches_filters(event_data, filters):
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
