import json
import re
from typing import Any

from cortex_leads.llm.types import ShapeError

# The closing line of the user turn decides the JSON shape, and naming keys gets bare
# strings back; so the shape is drawn with a concrete example.
# port từ backend/app/services/memory_extraction_prompt.py (response_shape) + AGENTS.md.


def response_shape(example: dict[str, Any], note: str | None = None) -> str:
    """Closing instruction that *draws* the expected JSON object."""
    drawn = json.dumps(example, ensure_ascii=False, indent=2)
    lines = [
        "Trả về DUY NHẤT một JSON object, không văn bản nào khác, không code fence, đúng hình dạng:",
        drawn,
    ]
    if note:
        lines.append(note)
    return "\n".join(lines)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_THINK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)  # reasoning models (MiniMax, …)


def parse_json_object(text: str | None) -> dict[str, Any]:
    """Extract the first JSON object from model text; raise ShapeError otherwise."""
    if not text or not text.strip():
        raise ShapeError("empty response")
    text = _THINK.sub("", text)  # a draft the model only thought about is not its answer
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    decoder = json.JSONDecoder()
    last_non_object: str | None = None
    for cand in candidates:
        for i, ch in enumerate(cand):
            if ch not in "{[":
                continue
            try:
                value, _ = decoder.raw_decode(cand, i)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
            last_non_object = type(value).__name__
    if last_non_object:
        raise ShapeError(f"JSON found but it is a {last_non_object}, not an object")
    raise ShapeError("no JSON object found in response")
