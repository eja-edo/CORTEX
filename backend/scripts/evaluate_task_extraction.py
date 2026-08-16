"""
Measure task extraction against the labelled set (Milestone 2.3, M1/M2).

Runs the **real** prompt against the **real** model over
`tests/data/task_extraction_dataset.json` and reports precision and recall.
It is a script and not a test because it costs money and needs a live
model; CI covers the deterministic half (the validator) in
`tests/unit/test_task_extraction_rules.py`.

    python -m scripts.evaluate_task_extraction
    python -m scripts.evaluate_task_extraction --no-validator

**The acceptance threshold is precision ≥ 0.90.** Recall is measured and
reported but deliberately has no threshold in this first version: a task
Cortex invents costs the user's trust in the feature, a task it misses
costs much less. If precision comes in under the bar, tighten the prompt —
adding examples, sharpening the two conditions — rather than lowering the
bar.

`--no-validator` reports the prompt's own precision with the deterministic
guard switched off. Useful for prompt work: it separates "the prompt got
better" from "the guard caught more".

Renamed from `evaluate_commitment_extraction.py` when Commitment was folded
into Task (see task_extraction.py's docstring). The dataset this script
reads does not exist yet in this tree — `commitment_extraction_dataset.json`
and its labels were written for the old three-condition Commitment rules
and would misgrade the two-condition Task rules. Rebuilding a ≥50-item
labelled set (real Vietnamese/English/mixed conversations, hand-labelled)
is 2.3 M1 and hasn't been redone since the rename; this script is wired
correctly but has nothing to run against until that dataset exists.
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.ai.agents.model_client import ModelClient
from app.ai.agents.provider_types import GenerationConfig, Message
from app.services.memory_extraction_prompt import build_extraction_messages
from app.services.memory_extraction_service import _parse_extraction_response
from app.services.task_extraction import validate_candidate

DATASET_PATH = Path(__file__).resolve().parent.parent / "tests" / "data" / "task_extraction_dataset.json"
PRECISION_THRESHOLD = 0.90


async def _extract(client: ModelClient, text: str) -> list[dict]:
    """Run one sentence through the production prompt path."""
    messages = build_extraction_messages(
        conversation_text=f"User: {text}",
        existing_summary=None,
        include_tasks=True,
    )
    _, response = await client.generate(
        messages=[Message(role=m["role"], content=m["content"]) for m in messages],
        config=GenerationConfig(temperature=0.2, max_output_tokens=2048),
        estimated_tokens=1500,
    )
    if not response or not response.content:
        return []
    parsed = _parse_extraction_response(response.content)
    return (parsed or {}).get("tasks") or []


async def main(use_validator: bool = True) -> int:
    if not DATASET_PATH.exists():
        print(
            f"No dataset at {DATASET_PATH}.\n"
            "This is 2.3 M1 (≥50 labelled real conversations, Vietnamese/English/"
            "mixed) and hasn't been rebuilt since Commitment was folded into Task — "
            "the old commitment_extraction_dataset.json used a three-condition rule "
            "set (it required a named counterparty) that no longer matches "
            "task_extraction.py's two conditions, so it can't be reused as-is.\n"
            'Expected shape: {"items": [{"id": ..., "text": ..., "language": '
            '"vi"|"en"|"mixed", "is_task": true|false}, ...]}'
        )
        return 2

    dataset = json.loads(DATASET_PATH.read_text())
    items = dataset["items"]
    client = ModelClient()

    true_positives = 0
    false_positives = 0
    false_negatives = 0
    mistakes: list[str] = []

    for item in items:
        try:
            raw_candidates = await _extract(client, item["text"])
        except Exception as exc:  # pragma: no cover - script path
            print(f"  ! {item['id']}: extraction failed: {exc}")
            continue

        if use_validator:
            accepted = [c for c in raw_candidates if validate_candidate(c)[0] is not None]
        else:
            accepted = raw_candidates

        predicted = bool(accepted)
        actual = item["is_task"]

        if predicted and actual:
            true_positives += 1
        elif predicted and not actual:
            false_positives += 1
            mistakes.append(f"  FP [{item['language']}] {item['text']!r}")
        elif not predicted and actual:
            false_negatives += 1
            mistakes.append(f"  FN [{item['language']}] {item['text']!r}")

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0

    print(f"\nItems: {len(items)}   (validator: {'on' if use_validator else 'off'})")
    print(f"TP={true_positives}  FP={false_positives}  FN={false_negatives}")
    print(f"precision = {precision:.3f}   (threshold {PRECISION_THRESHOLD})")
    print(f"recall    = {recall:.3f}   (no threshold in this version — by design)")

    if mistakes:
        print("\nMistakes:")
        print("\n".join(mistakes))

    if precision < PRECISION_THRESHOLD:
        print(
            f"\nFAIL: precision {precision:.3f} < {PRECISION_THRESHOLD}. "
            "Tighten the prompt — do not lower the threshold."
        )
        return 1

    print("\nPASS")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-validator",
        action="store_true",
        help="Measure the prompt alone, with the deterministic guard disabled",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(use_validator=not args.no_validator)))
