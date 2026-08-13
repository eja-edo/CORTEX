"""Unit tests for GET /agent/models.

Calls the route function directly (no HTTP layer, no DB) — it only reads
the static model_catalog, so this is enough to lock in the response shape
and confirm disabled catalogue entries are excluded.
"""

import pytest

from app.api.agent import list_models, AvailableModel
from app.ai.agents.model_catalog import enabled_models


@pytest.mark.asyncio
async def test_list_models_returns_enabled_catalogue_entries():
    result = await list_models(current_user=None)

    assert result == [AvailableModel(id=m.id, label=m.label) for m in enabled_models()]
    assert all(isinstance(m, AvailableModel) for m in result)


@pytest.mark.asyncio
async def test_list_models_excludes_disabled_entries(monkeypatch):
    import app.api.agent as agent_module
    from app.ai.agents.model_catalog import ModelSpec

    fake_catalog = [
        ModelSpec(id="on", label="On", enabled=True),
        ModelSpec(id="off", label="Off", enabled=False),
    ]
    monkeypatch.setattr(agent_module, "enabled_models", lambda: [m for m in fake_catalog if m.enabled])

    result = await list_models(current_user=None)

    assert [m.id for m in result] == ["on"]
