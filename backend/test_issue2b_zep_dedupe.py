"""
Tests for Issue 2b: dedupe semantic memories before inserting into Zep.

Verifies the in-process LRU check and the Zep similarity-search check
both prevent duplicate memory additions.
"""
import os
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

os.environ.setdefault(
    'ASYNC_DATABASE_URL',
    'postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db'
)


async def reset_cache():
    """Clear the in-process dedupe cache for test isolation."""
    from app.services.zep_memory import _dedupe_cache
    _dedupe_cache.clear()


async def test_in_process_dedupe_skips_exact_duplicate():
    """Same (user, category, content) twice: second must be skipped without Zep round-trip."""
    from app.services.zep_memory import add_semantic_memory, _dedupe_cache
    reset_cache()
    _dedupe_cache.clear()

    with patch("app.services.zep_memory._get_client") as mock_get_client:
        fake_client = MagicMock()
        fake_client.graph.add = MagicMock()
        mock_get_client.return_value = fake_client

        # First call — should attempt graph.add
        first = await add_semantic_memory(
            user_id="ws-1",
            category="preference",
            content="User prefers PostgreSQL over MongoDB.",
            confidence=0.9,
            expected_lifetime="permanent",
        )
        assert first is True, "First addition should succeed"
        assert fake_client.graph.add.call_count == 1, "graph.add should be called once"

        # Second call — exact same inputs
        second = await add_semantic_memory(
            user_id="ws-1",
            category="preference",
            content="User prefers PostgreSQL over MongoDB.",
            confidence=0.9,
            expected_lifetime="permanent",
        )
        assert second is True, "Second addition should return True (already exists)"
        assert fake_client.graph.add.call_count == 1, "graph.add must NOT be called again"


async def test_dedupe_considers_normalized_content():
    """Content differing only in whitespace/case should be treated as duplicate."""
    from app.services.zep_memory import add_semantic_memory, _dedupe_cache
    reset_cache()
    _dedupe_cache.clear()

    with patch("app.services.zep_memory._get_client") as mock_get_client:
        fake_client = MagicMock()
        fake_client.graph.add = MagicMock()
        mock_get_client.return_value = fake_client

        first = await add_semantic_memory(
            user_id="ws-1",
            category="preference",
            content="  Prefers PostgreSQL over MongoDB.",
            confidence=0.9,
            expected_lifetime="permanent",
        )
        assert first is True
        first_count = fake_client.graph.add.call_count

        second = await add_semantic_memory(
            user_id="ws-1",
            category="preference",
            content="Prefers PostgreSQL  over  MongoDB.",
            confidence=0.9,
            expected_lifetime="permanent",
        )
        assert second is True
        assert fake_client.graph.add.call_count == first_count, (
            "Whitespace-differing duplicate must not trigger graph.add"
        )


async def test_dedupe_different_user_not_duplicate():
    """Same content, different user: should NOT be treated as duplicate."""
    from app.services.zep_memory import add_semantic_memory, _dedupe_cache
    reset_cache()
    _dedupe_cache.clear()

    with patch("app.services.zep_memory._get_client") as mock_get_client:
        fake_client = MagicMock()
        fake_client.graph.add = MagicMock()
        mock_get_client.return_value = fake_client

        first = await add_semantic_memory(
            user_id="ws-1",
            category="preference",
            content="Prefers PostgreSQL.",
            confidence=0.9,
            expected_lifetime="permanent",
        )
        assert first is True

        second = await add_semantic_memory(
            user_id="ws-2",
            category="preference",
            content="Prefers PostgreSQL.",
            confidence=0.9,
            expected_lifetime="permanent",
        )
        assert second is True
        assert fake_client.graph.add.call_count == 2, "Different users: both must be added"


async def test_dedupe_different_category_not_duplicate():
    """Same user+content, different category: must not be treated as duplicate."""
    from app.services.zep_memory import add_semantic_memory, _dedupe_cache
    reset_cache()
    _dedupe_cache.clear()

    with patch("app.services.zep_memory._get_client") as mock_get_client:
        fake_client = MagicMock()
        fake_client.graph.add = MagicMock()
        mock_get_client.return_value = fake_client

        first = await add_semantic_memory(
            user_id="ws-1",
            category="preference",
            content="Prefers PostgreSQL.",
            confidence=0.9,
            expected_lifetime="permanent",
        )
        assert first is True

        second = await add_semantic_memory(
            user_id="ws-1",
            category="project",
            content="Prefers PostgreSQL.",
            confidence=0.9,
            expected_lifetime="permanent",
        )
        assert second is True
        assert fake_client.graph.add.call_count == 2, "Different categories: both must be added"


async def test_dedupe_batch_skips_duplicates():
    """add_semantic_memories_batch: duplicate entries skip graph.add."""
    from app.services.zep_memory import add_semantic_memories_batch, _dedupe_cache
    reset_cache()
    _dedupe_cache.clear()

    with patch("app.services.zep_memory._get_client") as mock_get_client:
        fake_client = MagicMock()
        fake_client.graph.add = MagicMock()
        mock_get_client.return_value = fake_client

        memories = [
            {"category": "preference", "content": "Prefers PostgreSQL.", "confidence": 0.9, "expected_lifetime": "permanent"},
            {"category": "preference", "content": "Prefers Python.", "confidence": 0.8, "expected_lifetime": "long"},
            {"category": "preference", "content": "Prefers PostgreSQL.", "confidence": 0.9, "expected_lifetime": "permanent"},  # dupe
        ]
        count = await add_semantic_memories_batch(user_id="ws-1", memories=memories)
        assert count == 3, "All 3 memories reported as successfully stored (dupe returns True)"
        assert fake_client.graph.add.call_count == 2, "Only 2 graph.add calls (dupe skipped)"


async def test_zep_search_based_dedupe():
    """When Zep returns a hit with score >= threshold, in-process add must be skipped.

    This test mocks search_semantic_memories to simulate a Zep hit."""
    from app.services.zep_memory import add_semantic_memory, _dedupe_cache
    reset_cache()
    _dedupe_cache.clear()

    with patch("app.services.zep_memory._get_client") as mock_get_client:
        fake_client = MagicMock()
        fake_client.graph.add = MagicMock()
        mock_get_client.return_value = fake_client

        with patch("app.services.zep_memory.search_semantic_memories") as mock_search:
            mock_search.return_value = [
                {"fact": "User prefers PostgreSQL.", "score": 0.97, "category": "preference", "content": "User prefers PostgreSQL."}
            ]

            result = await add_semantic_memory(
                user_id="ws-1",
                category="preference",
                content="User prefers PostgreSQL.",
                confidence=0.9,
                expected_lifetime="permanent",
            )
            assert result is True
            assert fake_client.graph.add.call_count == 0, (
                "graph.add must be skipped when Zep has high-score match"
            )
        mock_search.assert_called_once()


async def test_zep_dedupe_near_duplicate_at_threshold():
    """Near-duplicate at exactly 0.95 threshold is caught.

    "User prefers PostgreSQL." vs "User really likes PostgreSQL a lot."
    — semantically the same, different wording."""
    from app.services.zep_memory import add_semantic_memory, _dedupe_cache
    reset_cache()
    _dedupe_cache.clear()

    with patch("app.services.zep_memory._get_client") as mock_get_client:
        fake_client = MagicMock()
        fake_client.graph.add = MagicMock()
        mock_get_client.return_value = fake_client

        with patch("app.services.zep_memory.search_semantic_memories") as mock_search:
            mock_search.return_value = [
                {"fact": "User really likes PostgreSQL a lot.", "score": 0.95, "category": "preference", "content": "User really likes PostgreSQL a lot."}
            ]

            result = await add_semantic_memory(
                user_id="ws-1",
                category="preference",
                content="User prefers PostgreSQL.",
                confidence=0.9,
                expected_lifetime="permanent",
            )
            assert result is True
            assert fake_client.graph.add.call_count == 0, (
                "graph.add must be skipped when Zep returns near-duplicate at 0.95 threshold"
            )
        mock_search.assert_called_once()


async def test_zep_dedupe_below_threshold_not_duplicate():
    """Content scoring below 0.95 is NOT considered a duplicate."""
    from app.services.zep_memory import add_semantic_memory, _dedupe_cache
    reset_cache()
    _dedupe_cache.clear()

    with patch("app.services.zep_memory._get_client") as mock_get_client:
        fake_client = MagicMock()
        fake_client.graph.add = MagicMock()
        mock_get_client.return_value = fake_client

        with patch("app.services.zep_memory.search_semantic_memories") as mock_search:
            mock_search.return_value = [
                {"fact": "User likes cheese.", "score": 0.50, "category": "preference", "content": "User likes cheese."}
            ]

            result = await add_semantic_memory(
                user_id="ws-1",
                category="preference",
                content="User prefers PostgreSQL.",
                confidence=0.9,
                expected_lifetime="permanent",
            )
            assert result is True
            assert fake_client.graph.add.call_count == 1, (
                "graph.add must proceed when Zep score is below threshold"
            )


async def main():
    await test_in_process_dedupe_skips_exact_duplicate()
    print("✓ test_in_process_dedupe_skips_exact_duplicate")
    await test_dedupe_considers_normalized_content()
    print("✓ test_dedupe_considers_normalized_content")
    await test_dedupe_different_user_not_duplicate()
    print("✓ test_dedupe_different_user_not_duplicate")
    await test_dedupe_different_category_not_duplicate()
    print("✓ test_dedupe_different_category_not_duplicate")
    await test_dedupe_batch_skips_duplicates()
    print("✓ test_dedupe_batch_skips_duplicates")
    await test_zep_search_based_dedupe()
    print("✓ test_zep_search_based_dedupe")
    await test_zep_dedupe_near_duplicate_at_threshold()
    print("✓ test_zep_dedupe_near_duplicate_at_threshold")
    await test_zep_dedupe_below_threshold_not_duplicate()
    print("✓ test_zep_dedupe_below_threshold_not_duplicate")
    print("All Issue-2b tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
