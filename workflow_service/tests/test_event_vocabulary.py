"""Unit tests for Milestone 1.9 — workflow_service side of the shared event
vocabulary. Plain sync tests (no Redis, no DB) — kept out of
test_internal_event_listener.py because that module applies a session-scope
asyncio mark to every test in the file.
"""

from app.triggers import internal_event_listener as listener_module


def test_load_supported_events_reads_real_vocabulary_file():
    """SUPPORTED_EVENTS is no longer hardcoded here — it's generated from
    backend/app/events/vocabulary.py. This just checks the checked-in file
    is present, well-formed, and actually has entries (an empty list would
    mean the listener silently does nothing)."""
    events = listener_module.load_supported_events()
    assert "note.created" in events
    assert "tool.executed" in events  # was missing from the old hardcoded list
    assert events == sorted(events)


def test_load_implemented_event_types_excludes_reserved():
    implemented = listener_module.load_implemented_event_types()
    assert "asset.uploaded" not in implemented  # reserved, nothing publishes it
    assert "note.created" in implemented
