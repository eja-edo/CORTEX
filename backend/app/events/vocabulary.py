"""
Event vocabulary: the single source of truth for "what event types exist
in the system" (Milestone 1.9).

Before this, there were two independently-maintained lists that had already
drifted: `EVENT_PAYLOAD_REGISTRY` here in the backend (10 types) and
`SUPPORTED_EVENTS` hardcoded in `workflow_service/app/triggers/
internal_event_listener.py` (8 types, only 6 overlapping). Backend published
3 event types workflow_service never listened for (silently — a workflow
triggered on `tool.executed` would just never fire, no error anywhere), and
workflow_service listened for 2 types (`asset.uploaded`/`asset.processed`)
that nothing in the backend actually publishes yet.

`EVENT_VOCABULARY` here is now the only place that decides which event
types exist. `EVENT_PAYLOAD_REGISTRY` (payloads.py) stays the source of
truth for *validated* payload shapes — vocabulary entries reference it via
`has_payload_schema`, they don't duplicate it.

workflow_service is a separate service with its own venv/deployment (see
workflow_service/tests/test_internal_event_listener.py's docstring — it
already avoids importing the backend package directly). So this module
can't be imported live across the process boundary; instead
`backend/scripts/generate_event_vocabulary.py` serializes it to a checked-in
JSON file (`workflow_service/app/triggers/event_vocabulary.json`) that
workflow_service reads. Run the generator after editing this file — a test
(`test_workflow_vocabulary_is_in_sync`) fails CI if the checked-in JSON
drifts from this module.
"""

from dataclasses import dataclass

from app.events.payloads import EVENT_PAYLOAD_REGISTRY


@dataclass(frozen=True)
class EventVocabularyEntry:
    event_type: str
    description: str
    published_by: str
    has_payload_schema: bool


def _entry(event_type: str, description: str, published_by: str) -> EventVocabularyEntry:
    return EventVocabularyEntry(
        event_type=event_type,
        description=description,
        published_by=published_by,
        has_payload_schema=event_type in EVENT_PAYLOAD_REGISTRY,
    )


EVENT_VOCABULARY: dict[str, EventVocabularyEntry] = {
    e.event_type: e
    for e in [
        _entry("note.created", "A note was created", "app.services.notes.NoteService"),
        _entry("note.updated", "A note was updated (metadata or content patch)", "app.services.notes.NoteService"),
        _entry("note.deleted", "A note was soft-deleted", "app.services.notes.NoteService"),
        _entry("schedule.created", "A schedule was created", "app.services.schedule_service"),
        _entry("schedule.updated", "A schedule was updated", "app.services.schedule_service"),
        _entry("schedule.completed", "A schedule transitioned to completed", "app.services.schedule_service"),
        _entry("schedule.reminder.due", "A reminder fired", "app.services.reminder_worker.ReminderWorker"),
        _entry("conversation.message.created", "A chat message was saved", "app.ai.agents.conversation_store.ConversationStore"),
        _entry("tool.executed", "An AI tool call finished", "app.ai.agents.tool_execution_service.ToolExecutionService"),
        _entry("google_calendar.synced", "A Google Calendar sync batch finished", "app.services.google_sync_worker.GoogleSyncWorker"),
        # Reserved: workflow_service's public trigger-type API already lists
        # these (workflow_service/app/api/v1/actions.py) but nothing in the
        # backend publishes them yet — the asset/upload pipeline predates
        # the event bus and hasn't been wired to it (out of scope for
        # Phase 1's event bus work). Kept in the vocabulary so workflow_service
        # doesn't silently listen on undefined event types, and so wiring
        # them up later is a one-line addition, not a rediscovery.
        _entry("asset.uploaded", "Reserved — not yet published by any backend service", "none (reserved)"),
        _entry("asset.processed", "Reserved — not yet published by any backend service", "none (reserved)"),
    ]
}


def all_event_types() -> list[str]:
    """All known event types, sorted for a stable, diff-friendly order."""
    return sorted(EVENT_VOCABULARY.keys())


def implemented_event_types() -> list[str]:
    """Event types that actually have a payload schema (i.e. something in
    the backend really publishes them today) — excludes reserved entries."""
    return sorted(t for t, e in EVENT_VOCABULARY.items() if e.has_payload_schema)
