from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any


NotePatchOp = dict[str, Any]


def build_text_patch(old_text: str, new_text: str) -> list[NotePatchOp]:
    if old_text == new_text:
        return []

    matcher = SequenceMatcher(a=old_text, b=new_text)
    patch: list[NotePatchOp] = []

    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            patch.append({"op": "delete", "pos": old_start, "length": old_end - old_start})
        elif tag == "insert":
            patch.append({"op": "insert", "pos": old_start, "text": new_text[new_start:new_end]})
        elif tag == "replace":
            patch.append({"op": "replace", "pos": old_start, "length": old_end - old_start, "text": new_text[new_start:new_end]})

    return patch


def apply_text_patch(text: str, patch: list[NotePatchOp]) -> str:
    if not patch:
        return text

    current = text
    for op in sorted(patch, key=lambda item: item.get("pos", 0), reverse=True):
        operation = op.get("op")
        pos = int(op.get("pos", 0))
        if pos < 0 or pos > len(current):
            raise ValueError("Patch position out of range")

        if operation == "delete":
            length = int(op.get("length", 0))
            if length < 0:
                raise ValueError("Patch length must be non-negative")
            current = current[:pos] + current[pos + length :]
        elif operation == "insert":
            current = current[:pos] + str(op.get("text", "")) + current[pos:]
        elif operation == "replace":
            length = int(op.get("length", 0))
            if length < 0:
                raise ValueError("Patch length must be non-negative")
            current = current[:pos] + str(op.get("text", "")) + current[pos + length :]
        else:
            raise ValueError(f"Unsupported patch operation: {operation}")

    return current
