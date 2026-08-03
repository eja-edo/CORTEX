"""
Tests for M3: ZepMemoryProvider class extraction.

Verifies:
1. The class raises SemanticMemoryUnavailable when Zep API fails.
2. The legacy shims continue to return sentinels under the same condition.
3. Successful search returns content, not fact.
4. Timeout is passed to the Zep client.
"""
import os
import asyncio
import httpx
from unittest.mock import patch, MagicMock, ANY

os.environ.setdefault(
    "ASYNC_DATABASE_URL",
    "postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db",
)

SEMANTIC_MEMORY_UNAVAILABLE = "app.services.semantic_memory_provider.SemanticMemoryUnavailable"
ZEP_MEMORY = "app.services.zep_memory"


async def test_class_ensure_user_raises_on_failure():
    from app.services.zep_memory import ZepMemoryProvider

    prov = ZepMemoryProvider()
    with patch(f"{ZEP_MEMORY}._get_client") as mock_gc:
        fake = MagicMock()
        fake.user.add.side_effect = httpx.HTTPError("Zep API unreachable")
        mock_gc.return_value = fake

        import importlib
        exc_mod = importlib.import_module("app.services.semantic_memory_provider")
        try:
            await prov.ensure_user(user_id="test-ws")
            assert False, "Should have raised"
        except exc_mod.SemanticMemoryUnavailable:
            pass


async def test_class_add_semantic_memory_raises_on_failure():
    from app.services.zep_memory import (
        ZepMemoryProvider,
        _dedupe_cache,
    )
    _dedupe_cache.clear()

    prov = ZepMemoryProvider()
    with patch(f"{ZEP_MEMORY}._get_client") as mock_gc:
        fake = MagicMock()
        fake.graph.add.side_effect = httpx.HTTPError("Zep unreachable")
        mock_gc.return_value = fake

        with patch(f"{ZEP_MEMORY}.search_semantic_memories") as mock_search:
            mock_search.return_value = []

            import importlib
            exc_mod = importlib.import_module("app.services.semantic_memory_provider")
            try:
                await prov.add_semantic_memory(
                    user_id="test-ws", category="project",
                    content="test", confidence=0.9,
                    expected_lifetime="permanent",
                )
                assert False, "Should have raised"
            except exc_mod.SemanticMemoryUnavailable:
                pass


async def test_class_search_semantic_memories_raises_on_failure():
    from app.services.zep_memory import ZepMemoryProvider

    prov = ZepMemoryProvider()
    with patch(f"{ZEP_MEMORY}._get_client") as mock_gc:
        fake = MagicMock()
        fake.graph.search.side_effect = httpx.HTTPError("Zep unreachable")
        mock_gc.return_value = fake

        import importlib
        exc_mod = importlib.import_module("app.services.semantic_memory_provider")
        try:
            await prov.search_semantic_memories(
                user_id="test-ws", query="test"
            )
            assert False, "Should have raised"
        except exc_mod.SemanticMemoryUnavailable:
            pass


async def test_shim_ensure_user_returns_false_on_failure():
    from app.services.zep_memory import ensure_user

    with patch(f"{ZEP_MEMORY}._get_client") as mock_gc:
        fake = MagicMock()
        fake.user.add.side_effect = httpx.HTTPError("Zep API unreachable")
        mock_gc.return_value = fake

        result = await ensure_user(user_id="test-ws")
        assert result is False


async def test_shim_add_semantic_memory_returns_false_on_failure():
    from app.services.zep_memory import add_semantic_memory, _dedupe_cache
    _dedupe_cache.clear()

    with patch(f"{ZEP_MEMORY}._get_client") as mock_gc:
        fake = MagicMock()
        fake.graph.add.side_effect = httpx.HTTPError("Zep unreachable")
        mock_gc.return_value = fake

        result = await add_semantic_memory(
            user_id="test-ws", category="project",
            content="test", confidence=0.9,
            expected_lifetime="permanent",
        )
        assert result is False


async def test_shim_add_semantic_memories_batch_returns_zero_on_failure():
    from app.services.zep_memory import add_semantic_memories_batch, _dedupe_cache
    _dedupe_cache.clear()

    with patch(f"{ZEP_MEMORY}._get_client") as mock_gc:
        fake = MagicMock()
        fake.graph.add.side_effect = httpx.HTTPError("Zep unreachable")
        mock_gc.return_value = fake

        result = await add_semantic_memories_batch(
            user_id="test-ws",
            memories=[{"category": "project", "content": "test"}],
        )
        assert result == 0


async def test_shim_search_semantic_memories_returns_empty_list_on_failure():
    from app.services.zep_memory import search_semantic_memories

    with patch(f"{ZEP_MEMORY}._get_client") as mock_gc:
        fake = MagicMock()
        fake.graph.search.side_effect = httpx.HTTPError("Zep unreachable")
        mock_gc.return_value = fake

        result = await search_semantic_memories(
            user_id="test-ws", query="test"
        )
        assert result == []


async def test_search_returns_content_not_fact():
    from app.services.zep_memory import (
        ZepMemoryProvider,
        _dedupe_cache,
    )
    _dedupe_cache.clear()

    prov = ZepMemoryProvider()

    fake_edge = MagicMock()
    fake_edge.fact = "some memory fact"
    fake_edge.name = "some name"
    fake_edge.score = 0.95
    fake_edge.attributes = {
        "category": "preference",
        "content": "some memory fact",
    }

    fake_results = MagicMock()
    fake_results.edges = [fake_edge]
    fake_results.nodes = []

    with patch(f"{ZEP_MEMORY}._get_client") as mock_gc:
        fake_client = MagicMock()
        fake_client.graph.search.return_value = fake_results
        mock_gc.return_value = fake_client

        results = await prov.search_semantic_memories(
            user_id="test-ws", query="memory", limit=10,
        )
        assert len(results) >= 1
        r = results[0]
        assert "content" in r, "Result must contain 'content'"
        assert r["content"] == "some memory fact"
        assert "fact" not in r, "Result must NOT contain 'fact'"


async def test_timeout_passed_to_client():
    from app.services.zep_memory import _get_client

    with patch(f"{ZEP_MEMORY}.Zep") as mock_zep:
        _get_client(timeout=42.0)
        mock_zep.assert_called_once_with(api_key=ANY, timeout=42.0)


async def test_timeout_default_is_10():
    from app.services.zep_memory import ZEP_CLIENT_TIMEOUT
    assert ZEP_CLIENT_TIMEOUT == 10.0, (
        f"Expected default timeout 10.0, got {ZEP_CLIENT_TIMEOUT}"
    )


async def main():
    await test_class_ensure_user_raises_on_failure()
    print("✓ test_class_ensure_user_raises_on_failure")
    await test_class_add_semantic_memory_raises_on_failure()
    print("✓ test_class_add_semantic_memory_raises_on_failure")
    await test_class_search_semantic_memories_raises_on_failure()
    print("✓ test_class_search_semantic_memories_raises_on_failure")
    await test_shim_ensure_user_returns_false_on_failure()
    print("✓ test_shim_ensure_user_returns_false_on_failure")
    await test_shim_add_semantic_memory_returns_false_on_failure()
    print("✓ test_shim_add_semantic_memory_returns_false_on_failure")
    await test_shim_add_semantic_memories_batch_returns_zero_on_failure()
    print("✓ test_shim_add_semantic_memories_batch_returns_zero_on_failure")
    await test_shim_search_semantic_memories_returns_empty_list_on_failure()
    print("✓ test_shim_search_semantic_memories_returns_empty_list_on_failure")
    await test_search_returns_content_not_fact()
    print("✓ test_search_returns_content_not_fact")
    await test_timeout_passed_to_client()
    print("✓ test_timeout_passed_to_client")
    await test_timeout_default_is_10()
    print("✓ test_timeout_default_is_10")
    print("All M3 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
