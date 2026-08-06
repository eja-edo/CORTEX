"""
Generate workflow_service's checked-in copy of the event vocabulary
(Milestone 1.9, Task 1.9.1).

`backend/app/events/vocabulary.py` is the single source of truth for event
types. workflow_service is a separate service (own venv/deployment, own
Docker build context scoped to workflow_service/ — see infrastructure/
docker-compose.yml) and deliberately doesn't import the backend package
across that boundary (see workflow_service/tests/test_internal_event_listener.py's
docstring). So instead of a live import, this script serializes the
vocabulary to a JSON file checked into workflow_service's own tree.

Run this after editing backend/app/events/vocabulary.py:

    python -m scripts.generate_event_vocabulary

`tests/unit/test_event_vocabulary.py::test_workflow_vocabulary_is_in_sync`
fails if the checked-in JSON drifts from what this script would currently
produce, so CI catches a forgotten regeneration.
"""

import json
from pathlib import Path

from app.events.vocabulary import EVENT_VOCABULARY

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "workflow_service" / "app" / "triggers" / "event_vocabulary.json"
)


def build_vocabulary_json() -> dict:
    return {
        "_generated_by": "backend/scripts/generate_event_vocabulary.py — do not edit by hand",
        "_source": "backend/app/events/vocabulary.py",
        "event_types": [
            {
                "event_type": e.event_type,
                "description": e.description,
                "has_payload_schema": e.has_payload_schema,
            }
            for e in sorted(EVENT_VOCABULARY.values(), key=lambda e: e.event_type)
        ],
    }


def main() -> None:
    data = build_vocabulary_json()
    OUTPUT_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {len(data['event_types'])} event types to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
