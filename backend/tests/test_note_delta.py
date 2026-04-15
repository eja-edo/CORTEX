from __future__ import annotations

import pytest

from app.services.notes import PATCH_COMPACTION_THRESHOLD, NoteService
from app.utils.note_delta import apply_text_patch, build_text_patch


def test_build_and_apply_text_patch_roundtrip_cases() -> None:
    cases = [
        ("", "hello"),
        ("hello", "hello world"),
        ("alpha beta gamma", "alpha gamma"),
        ("line1\nline2\nline3", "line1\nline2 updated\nline3"),
        ("abc123xyz", "abc-123-xyz"),
    ]

    for old_text, new_text in cases:
        patch = build_text_patch(old_text, new_text)
        assert apply_text_patch(old_text, patch) == new_text


def test_build_text_patch_no_changes_returns_empty() -> None:
    assert build_text_patch("no-change", "no-change") == []


def test_apply_text_patch_supports_mixed_ops() -> None:
    original = "abcdefgh"
    patch = [
        {"op": "replace", "pos": 2, "length": 2, "text": "XY"},
        {"op": "insert", "pos": 8, "text": "-tail"},
        {"op": "delete", "pos": 0, "length": 1},
    ]

    assert apply_text_patch(original, patch) == "bXYefgh-tail"


def test_apply_text_patch_rejects_invalid_position() -> None:
    with pytest.raises(ValueError, match="Patch position out of range"):
        apply_text_patch("abc", [{"op": "insert", "pos": 99, "text": "x"}])


def test_apply_text_patch_rejects_unknown_operation() -> None:
    with pytest.raises(ValueError, match="Unsupported patch operation"):
        apply_text_patch("abc", [{"op": "move", "pos": 0, "text": "x"}])


def test_note_compaction_threshold_behavior() -> None:
    service = NoteService(session=None)  # type: ignore[arg-type]

    assert service._should_compact(checkpoint_version=1, current_version=1 + PATCH_COMPACTION_THRESHOLD)
    assert not service._should_compact(checkpoint_version=1, current_version=PATCH_COMPACTION_THRESHOLD)
