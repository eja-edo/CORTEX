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
    # Short, user-facing label for the Trigger Catalog (Milestone 4.2) —
    # `description` above is for developers reading this file, not for a
    # workflow builder dropdown. See event_vocabulary.json's
    # `label_vi`/generate_event_vocabulary.py.
    label_vi: str


def _entry(event_type: str, description: str, published_by: str, label_vi: str) -> EventVocabularyEntry:
    return EventVocabularyEntry(
        event_type=event_type,
        description=description,
        published_by=published_by,
        has_payload_schema=event_type in EVENT_PAYLOAD_REGISTRY,
        label_vi=label_vi,
    )


EVENT_VOCABULARY: dict[str, EventVocabularyEntry] = {
    e.event_type: e
    for e in [
        _entry("note.created", "A note was created", "app.services.notes.NoteService", "Ghi chú mới được tạo"),
        _entry("note.updated", "A note was updated (metadata or content patch)", "app.services.notes.NoteService", "Ghi chú được cập nhật"),
        _entry("note.deleted", "A note was soft-deleted", "app.services.notes.NoteService", "Ghi chú bị xoá"),
        _entry("schedule.created", "A schedule was created", "app.services.schedule_service", "Lịch mới được tạo"),
        _entry("schedule.updated", "A schedule was updated", "app.services.schedule_service", "Lịch được cập nhật"),
        _entry("schedule.completed", "A schedule transitioned to completed", "app.services.schedule_service", "Lịch hoàn thành"),
        _entry("schedule.reminder.due", "A reminder fired", "app.services.reminder_worker.ReminderWorker", "Đến giờ nhắc lịch"),
        _entry("task.created", "A task was created", "app.services.tasks.TaskService", "Việc mới được tạo"),
        _entry("task.updated", "A task changed (carries fields_changed)", "app.services.tasks.TaskService", "Việc được cập nhật"),
        _entry("task.completed", "A task transitioned to done — published instead of task.updated for that transition", "app.services.tasks.TaskService", "Việc hoàn thành"),
        _entry("task.deleted", "A task was deleted", "app.services.tasks.TaskService", "Việc bị xoá"),
        _entry("task.overdue", "A task transitioned into overdue (polled, not from a mutation)", "app.services.state_evaluator.StateEvaluator", "Việc quá hạn"),
        _entry("task.due_soon", "An open task entered its due-soon window, not yet in_progress (polled)", "app.services.state_evaluator.StateEvaluator", "Việc sắp đến hạn"),
        _entry("task.stale", "An open, undated task went untouched past the staleness threshold (polled)", "app.services.state_evaluator.StateEvaluator", "Việc bị bỏ quên (không hạn, lâu không động tới)"),
        _entry("task.blocked_cascade", "An overdue task has at least one open subtask (polled)", "app.services.state_evaluator.StateEvaluator", "Việc trễ hạn còn việc con chưa xong"),
        _entry("schedule.starts_soon", "A schedule entered its starts-soon lookahead window (polled)", "app.services.state_evaluator.StateEvaluator", "Lịch sắp bắt đầu"),
        _entry("day.review", "A user still has open tasks as the day reaches its review hour (polled)", "app.services.state_evaluator.StateEvaluator", "Cuối ngày còn việc chưa xong"),
        _entry("conversation.message.created", "A chat message was saved", "app.ai.agents.conversation_store.ConversationStore", "Có tin nhắn mới trong hội thoại"),
        _entry("tool.executed", "An AI tool call finished", "app.ai.agents.tool_execution_service.ToolExecutionService", "AI vừa thực hiện xong một thao tác"),
        _entry("google_calendar.synced", "A Google Calendar sync batch finished", "app.services.google_sync_worker.GoogleSyncWorker", "Đồng bộ Google Calendar xong"),
        # Reserved: workflow_service's public trigger-type API already lists
        # these (workflow_service/app/api/v1/actions.py) but nothing in the
        # backend publishes them yet — the asset/upload pipeline predates
        # the event bus and hasn't been wired to it (out of scope for
        # Phase 1's event bus work). Kept in the vocabulary so workflow_service
        # doesn't silently listen on undefined event types, and so wiring
        # them up later is a one-line addition, not a rediscovery.
        _entry("asset.uploaded", "Reserved — not yet published by any backend service", "none (reserved)", "Tệp được tải lên (chưa dùng được)"),
        _entry("asset.processed", "Reserved — not yet published by any backend service", "none (reserved)", "Tệp xử lý xong (chưa dùng được)"),
    ]
}


def all_event_types() -> list[str]:
    """All known event types, sorted for a stable, diff-friendly order."""
    return sorted(EVENT_VOCABULARY.keys())


def implemented_event_types() -> list[str]:
    """Event types that actually have a payload schema (i.e. something in
    the backend really publishes them today) — excludes reserved entries."""
    return sorted(t for t, e in EVENT_VOCABULARY.items() if e.has_payload_schema)
