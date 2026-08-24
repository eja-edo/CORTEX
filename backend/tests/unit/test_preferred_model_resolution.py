"""Unit tests for `AgentService._resolve_preferred_model`.

The interesting behaviour is not the happy path but the failure one: this
read happens inside a transaction holding the turn's flushed-but-
uncommitted rows, so a statement that fails must not take the rest of the
turn down with it.
"""

import pytest

from app.ai.agents.agent_service import AgentService
import app.ai.agents.agent_service as agent_service_module


class _FakeSavepoint:
    """Stands in for `session.begin_nested()`: records that it was entered
    and swallows nothing — the real one rolls back to the savepoint and
    re-raises, leaving the outer transaction usable."""

    def __init__(self, recorder):
        self._recorder = recorder

    async def __aenter__(self):
        self._recorder.append("enter")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._recorder.append("rollback" if exc_type else "release")
        return False


class _FakeSession:
    def __init__(self):
        self.savepoints = []

    def begin_nested(self):
        return _FakeSavepoint(self.savepoints)


def _service() -> AgentService:
    service = AgentService.__new__(AgentService)  # no DB, no tool registry
    service.db = _FakeSession()
    return service


@pytest.mark.asyncio
async def test_an_explicitly_chosen_model_wins_without_touching_preferences(monkeypatch):
    called = False

    async def fake_get(db, user_id):
        nonlocal called
        called = True

    monkeypatch.setattr(agent_service_module, "get_chat_model_async", fake_get)
    service = _service()

    assert await service._resolve_preferred_model("gemini/gemma-4-31b-it", "mezon", "u1") == "gemini/gemma-4-31b-it"
    assert called is False


@pytest.mark.asyncio
async def test_the_web_never_reads_the_mezon_choice(monkeypatch):
    """The web has its own picker; a choice made in a DM must not make
    that dropdown describe a model which isn't running."""
    called = False

    async def fake_get(db, user_id):
        nonlocal called
        called = True
        return "gemini/gemma-4-31b-it"

    monkeypatch.setattr(agent_service_module, "get_chat_model_async", fake_get)
    service = _service()

    assert await service._resolve_preferred_model(None, None, "u1") is None
    assert await service._resolve_preferred_model("auto", None, "u1") is None
    assert called is False


@pytest.mark.asyncio
async def test_a_mezon_turn_uses_the_stored_choice(monkeypatch):
    async def fake_get(db, user_id):
        return "gemini/gemma-4-31b-it"

    monkeypatch.setattr(agent_service_module, "get_chat_model_async", fake_get)
    service = _service()

    assert await service._resolve_preferred_model("auto", "mezon", "u1") == "gemini/gemma-4-31b-it"


@pytest.mark.asyncio
async def test_the_read_is_wrapped_in_a_savepoint(monkeypatch):
    """Without one, a failed statement here poisons the transaction the
    turn's own writes are sitting in — Postgres then refuses every
    following command, and the turn dies somewhere unrelated."""
    async def fake_get(db, user_id):
        return None

    monkeypatch.setattr(agent_service_module, "get_chat_model_async", fake_get)
    service = _service()

    await service._resolve_preferred_model("auto", "mezon", "u1")
    assert service.db.savepoints == ["enter", "release"]


@pytest.mark.asyncio
async def test_a_failing_read_falls_back_to_the_default_and_rolls_back_only_itself(monkeypatch):
    # How this actually broke in the wild: the column was missing on an
    # un-migrated database, and the turn died several statements later in
    # update_conversation_timestamp with an error naming a table that had
    # nothing to do with it.
    async def fake_get(db, user_id):
        raise RuntimeError("column user_preferences.chat_model does not exist")

    monkeypatch.setattr(agent_service_module, "get_chat_model_async", fake_get)
    service = _service()

    assert await service._resolve_preferred_model("auto", "mezon", "u1") is None
    assert service.db.savepoints == ["enter", "rollback"]
