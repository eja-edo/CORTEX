# port từ backend/app/ai/tools/empty_result.py
"""Mandatory note on empty results. Measured in the old code: with an empty list and no note the
model invented content 6/6 times; with a note ~5/7 did not. The note must sit in the result, next to
the decision, not in a system prompt thousands of tokens away."""
from typing import Any

_TEMPLATE = (
    "{what} — đây là sự thật, không phải khoảng trống cần lấp. "
    "Không tự nghĩ ra nội dung để điền vào."
)


def empty_note(what: str) -> str:
    return _TEMPLATE.format(what=what)


def is_empty(data: Any) -> bool:
    if data is None or data == "" or data == [] or data == {}:
        return True
    if isinstance(data, dict):
        return all(is_empty(v) for v in data.values())
    return False
