"""Unit tests for the `chat_model` preference — the Mezon `*model` command's
backing store.

The route function is called directly (no HTTP, no DB): the only branch
worth pinning here is validation against the catalogue, which is what
separates "a model you can pick" from "a string that gets silently
ignored at request time".
"""

import pytest
from fastapi import HTTPException

import app.api.user_preferences as prefs_api
from app.schemas import ChatModelUpdate


class _User:
    id = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_a_catalogue_model_is_stored(monkeypatch):
    saved = {}

    async def fake_set(db, user_id, *, chat_model):
        saved["user_id"] = user_id
        saved["chat_model"] = chat_model
        return type("P", (), {"quiet_hours_start": None, "quiet_hours_end": None, "chat_model": chat_model})()

    monkeypatch.setattr(prefs_api, "enabled_model_ids", lambda: ["free_auto", "gemini/gemma-4-31b-it"])
    monkeypatch.setattr(prefs_api, "set_chat_model_async", fake_set)

    result = await prefs_api.update_chat_model(
        ChatModelUpdate(chat_model="gemini/gemma-4-31b-it"),
        current_user=_User(),
        db=None,
    )

    assert saved["chat_model"] == "gemini/gemma-4-31b-it"
    assert result.chat_model == "gemini/gemma-4-31b-it"


@pytest.mark.asyncio
async def test_a_model_outside_the_catalogue_is_rejected_not_stored(monkeypatch):
    """A stale client's id must fail loudly. Stored, it would be dropped by
    `ModelClient._resolve` at request time and the user would be left
    looking at a choice that never takes effect."""
    called = False

    async def fake_set(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(prefs_api, "enabled_model_ids", lambda: ["free_auto"])
    monkeypatch.setattr(prefs_api, "set_chat_model_async", fake_set)

    with pytest.raises(HTTPException) as exc_info:
        await prefs_api.update_chat_model(
            ChatModelUpdate(chat_model="đã-gỡ-khỏi-catalog"),
            current_user=_User(),
            db=None,
        )

    assert exc_info.value.status_code == 400
    assert called is False


@pytest.mark.asyncio
async def test_null_clears_the_choice_without_touching_the_catalogue(monkeypatch):
    """Clearing must not be validated against the catalogue — "no choice"
    is always valid, including after the model someone picked was retired."""
    saved = {}

    async def fake_set(db, user_id, *, chat_model):
        saved["chat_model"] = chat_model
        return type("P", (), {"quiet_hours_start": None, "quiet_hours_end": None, "chat_model": None})()

    monkeypatch.setattr(prefs_api, "enabled_model_ids", lambda: [])
    monkeypatch.setattr(prefs_api, "set_chat_model_async", fake_set)

    result = await prefs_api.update_chat_model(
        ChatModelUpdate(chat_model=None), current_user=_User(), db=None
    )

    assert saved["chat_model"] is None
    assert result.chat_model is None
