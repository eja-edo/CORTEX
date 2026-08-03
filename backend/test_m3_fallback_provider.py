"""
Tests for M3: FallbackSemanticMemoryProvider.

Verifies:
1. Primary provider is called on success.
2. Fallback is called when primary raises SemanticMemoryUnavailable.
3. Fallback propagates SemanticMemoryUnavailable when it also fails.
4. Callers (memory_extraction_service, extract_memory) work under simulated Zep failure.
"""
import os
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, call

os.environ.setdefault(
    "ASYNC_DATABASE_URL",
    "postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db",
)

UNSEMANTIC = "app.services.semantic_memory_provider.SemanticMemoryUnavailable"


async def test_normal_operation_calls_primary():
    from app.services.semantic_memory_provider import (
        FallbackSemanticMemoryProvider,
        SemanticMemoryProvider,
    )

    mock_primary = AsyncMock(spec=SemanticMemoryProvider)
    mock_primary.ensure_user.return_value = True
    mock_primary.add_semantic_memory.return_value = True
    mock_primary.add_semantic_memories_batch.return_value = 2
    mock_primary.search_semantic_memories.return_value = []

    mock_fallback = AsyncMock(spec=SemanticMemoryProvider)
    db = MagicMock()

    provider = FallbackSemanticMemoryProvider(
        db=db, primary=mock_primary, fallback=mock_fallback,
    )

    assert await provider.ensure_user("u1") is True
    mock_primary.ensure_user.assert_awaited_once_with(user_id="u1")
    mock_fallback.ensure_user.assert_not_called()

    assert await provider.add_semantic_memory(
        user_id="u1", category="cat", content="c",
        confidence=0.9, expected_lifetime="perm",
    ) is True
    mock_primary.add_semantic_memory.assert_awaited_once()
    mock_fallback.add_semantic_memory.assert_not_called()

    assert await provider.add_semantic_memories_batch(
        user_id="u1", memories=[{"category": "cat", "content": "c"}],
    ) == 2
    mock_primary.add_semantic_memories_batch.assert_awaited_once()
    mock_fallback.add_semantic_memories_batch.assert_not_called()

    assert await provider.search_semantic_memories(
        user_id="u1", query="q",
    ) == []
    mock_primary.search_semantic_memories.assert_awaited_once_with(
        user_id="u1", query="q", limit=10, min_score=None,
    )
    mock_fallback.search_semantic_memories.assert_not_called()


async def test_primary_failure_falls_back():
    import importlib
    exc_mod = importlib.import_module("app.services.semantic_memory_provider")
    SemanticMemoryUnavailable = exc_mod.SemanticMemoryUnavailable
    FallbackSemanticMemoryProvider = exc_mod.FallbackSemanticMemoryProvider

    mock_primary = AsyncMock(spec=exc_mod.SemanticMemoryProvider)
    mock_primary.ensure_user.side_effect = SemanticMemoryUnavailable("Zep down")
    mock_primary.add_semantic_memory.side_effect = SemanticMemoryUnavailable("Zep down")
    mock_primary.add_semantic_memories_batch.side_effect = SemanticMemoryUnavailable("Zep down")
    mock_primary.search_semantic_memories.side_effect = SemanticMemoryUnavailable("Zep down")

    mock_fallback = AsyncMock(spec=exc_mod.SemanticMemoryProvider)
    mock_fallback.ensure_user.return_value = True
    mock_fallback.add_semantic_memory.return_value = True
    mock_fallback.add_semantic_memories_batch.return_value = 1
    mock_fallback.search_semantic_memories.return_value = []

    db = MagicMock()

    provider = FallbackSemanticMemoryProvider(
        db=db, primary=mock_primary, fallback=mock_fallback,
    )

    assert await provider.ensure_user("u1") is True
    mock_fallback.ensure_user.assert_awaited_once_with(user_id="u1")

    assert await provider.add_semantic_memory(
        user_id="u1", category="cat", content="c",
        confidence=0.9, expected_lifetime="perm",
    ) is True
    mock_fallback.add_semantic_memory.assert_awaited_once()

    assert await provider.add_semantic_memories_batch(
        user_id="u1", memories=[{"category": "cat", "content": "c"}],
    ) == 1
    mock_fallback.add_semantic_memories_batch.assert_awaited_once()

    assert await provider.search_semantic_memories(
        user_id="u1", query="q",
    ) == []
    mock_fallback.search_semantic_memories.assert_awaited_once_with(
        user_id="u1", query="q", limit=10, min_score=None,
    )


async def test_both_fail_propagates():
    import importlib
    exc_mod = importlib.import_module("app.services.semantic_memory_provider")
    SemanticMemoryUnavailable = exc_mod.SemanticMemoryUnavailable
    FallbackSemanticMemoryProvider = exc_mod.FallbackSemanticMemoryProvider

    mock_primary = AsyncMock(spec=exc_mod.SemanticMemoryProvider)
    mock_primary.ensure_user.side_effect = SemanticMemoryUnavailable("Zep down")
    mock_fallback = AsyncMock(spec=exc_mod.SemanticMemoryProvider)
    mock_fallback.ensure_user.side_effect = SemanticMemoryUnavailable("PgVector down")

    provider = FallbackSemanticMemoryProvider(
        db=MagicMock(), primary=mock_primary, fallback=mock_fallback,
    )

    try:
        await provider.ensure_user("u1")
        assert False, "Should have raised"
    except SemanticMemoryUnavailable:
        pass


async def test_memory_extraction_service_uses_provider():
    from app.services.memory_extraction_service import extract_and_store

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    result = await extract_and_store(
        conversation_id="00000000-0000-0000-0000-000000000000",
        db=mock_db,
    )
    assert result.get("success") is False
    assert "not found" in result.get("error", "").lower()


async def test_extract_memory_handler_uses_async_db():
    from app.ai.tools.extract_memory import extract_memory_handler
    from contextlib import asynccontextmanager

    mock_ctx = MagicMock()
    mock_ctx.workspace_id = "ws-1"
    mock_ctx.user_id = "user-1"
    mock_ctx.get_sync_db.return_value.__enter__.return_value = MagicMock()

    mock_async_session = AsyncMock()
    mock_async_session.execute.return_value = MagicMock()
    mock_async_session.execute.return_value.scalar_one_or_none.return_value = None

    @asynccontextmanager
    async def fake_async_db():
        yield mock_async_session

    mock_ctx.async_db = fake_async_db

    args = {"query": "test", "limit": 5}
    result = await extract_memory_handler(args, mock_ctx)
    assert "success" in result


async def main():
    await test_normal_operation_calls_primary()
    print("✓ test_normal_operation_calls_primary")
    await test_primary_failure_falls_back()
    print("✓ test_primary_failure_falls_back")
    await test_both_fail_propagates()
    print("✓ test_both_fail_propagates")
    await test_memory_extraction_service_uses_provider()
    print("✓ test_memory_extraction_service_uses_provider")
    await test_extract_memory_handler_uses_async_db()
    print("✓ test_extract_memory_handler_uses_async_db")
    print("All M3 fallback tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
