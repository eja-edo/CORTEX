"""Unit tests for Milestone 1.9 — unified event vocabulary.

Backend and workflow_service used to each hardcode their own event type
list, and the lists had already drifted (see vocabulary.py's docstring).
These tests guard the two invariants that make the fix actually hold:
  1. Every event type with a real payload schema is in the vocabulary
     (nothing the backend publishes is invisible to it).
  2. The checked-in workflow_service JSON matches what the generator would
     currently produce from vocabulary.py (catches "edited vocabulary.py,
     forgot to regenerate").
"""

import json

from app.events.payloads import EVENT_PAYLOAD_REGISTRY
from app.events.vocabulary import EVENT_VOCABULARY, all_event_types, implemented_event_types
from app.services.notification_subscribers import DIRECT_DELIVERY_HANDLERS
from scripts.generate_event_vocabulary import OUTPUT_PATH, build_vocabulary_json


def test_every_payload_registry_type_is_in_vocabulary():
    """Nothing the backend actually publishes should be missing from the
    vocabulary — that was exactly the original bug (tool.executed etc. were
    published but invisible to workflow_service)."""
    assert set(EVENT_PAYLOAD_REGISTRY.keys()) <= set(EVENT_VOCABULARY.keys())


def test_implemented_event_types_matches_payload_registry():
    assert set(implemented_event_types()) == set(EVENT_PAYLOAD_REGISTRY.keys())


def test_all_event_types_is_sorted_and_a_superset():
    types = all_event_types()
    assert types == sorted(types)
    assert set(implemented_event_types()) <= set(types)


def test_reserved_events_have_no_payload_schema():
    """asset.uploaded/asset.processed are kept as reserved placeholders —
    nothing publishes them yet (see vocabulary.py docstring)."""
    assert EVENT_VOCABULARY["asset.uploaded"].has_payload_schema is False
    assert EVENT_VOCABULARY["asset.processed"].has_payload_schema is False
    assert "asset.uploaded" not in implemented_event_types()


def test_direct_delivery_handlers_are_all_known_event_types():
    """A3: every event `notification_subscribers.py` handles directly must
    be a real vocabulary entry — same "nothing invisible" invariant as
    `test_every_payload_registry_type_is_in_vocabulary`, for the registry
    workflow_service's conflict detector reads."""
    assert set(DIRECT_DELIVERY_HANDLERS.keys()) <= set(EVENT_VOCABULARY.keys())


def test_has_direct_backend_delivery_matches_the_handler_registry():
    generated = {e["event_type"] for e in build_vocabulary_json()["event_types"] if e["has_direct_backend_delivery"]}
    assert generated == set(DIRECT_DELIVERY_HANDLERS.keys())


def test_workflow_vocabulary_is_in_sync():
    """The checked-in workflow_service/app/triggers/event_vocabulary.json
    must match what the generator would produce right now. If this fails,
    someone edited vocabulary.py and forgot to re-run
    `python -m scripts.generate_event_vocabulary`."""
    on_disk = json.loads(OUTPUT_PATH.read_text())
    fresh = build_vocabulary_json()
    assert on_disk == fresh


def test_every_directly_delivered_event_has_a_payload_schema():
    """`task.at_risk` shipped without one: `TaskAtRiskPayload` existed but
    was never added to EVENT_PAYLOAD_REGISTRY, so the generated
    `event_vocabulary.json` advertised `has_payload_schema: false` to
    workflow_service and the payload went unvalidated.

    Anything the backend delivers itself is, by definition, an event the
    backend really publishes — so it must have a registered schema. This
    catches the next one automatically.
    """
    from app.services.notification_subscribers import DIRECT_DELIVERY_HANDLERS

    missing = sorted(set(DIRECT_DELIVERY_HANDLERS) - set(EVENT_PAYLOAD_REGISTRY))
    assert not missing, f"directly-delivered events with no payload schema: {missing}"
