"""
Integration test for PgVectorMemoryProvider against dev DB.

Run: python -m pytest test_pgvector_provider.py -v -s
"""

import asyncio
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.database_async import AsyncSessionLocal
from app.services.pgvector_memory_provider import (
    PgVectorMemoryProvider,
    _reset_dedupe_cache,
)

TEST_USER_ID = "pgvector-test-workspace"


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(scope="module")
async def provider(db):
    return PgVectorMemoryProvider(db=db)


@pytest.mark.asyncio
async def test_a_insert_and_verify(provider, db):
    _reset_dedupe_cache()
    await db.execute(
        text("DELETE FROM semantic_memories WHERE user_id = :uid"),
        {"uid": TEST_USER_ID},
    )
    await db.commit()

    content = "Test content A: FastAPI microservices with pgvector"
    ok = await provider.add_semantic_memory(
        user_id=TEST_USER_ID,
        category="project",
        content=content,
        confidence=0.95,
        expected_lifetime="permanent",
    )
    assert ok
    await db.commit()

    row = (await db.execute(
        text("SELECT content, vector_dims(embedding) FROM semantic_memories WHERE user_id = :uid"),
        {"uid": TEST_USER_ID},
    )).fetchone()
    assert row is not None
    assert row[0] == content
    assert row[1] == 768, f"expected dims=768, got {row[1]}"
    print(f"  (a) INSERT OK: dims={row[1]}")


@pytest.mark.asyncio
async def test_b_dedup(provider, db):
    _reset_dedupe_cache()
    await db.execute(
        text("DELETE FROM semantic_memories WHERE user_id = :uid"),
        {"uid": TEST_USER_ID},
    )
    await db.commit()

    content = "Test content B: pgvector HNSW index dedup verification"

    ok1 = await provider.add_semantic_memory(
        user_id=TEST_USER_ID, category="constraint", content=content,
        confidence=0.9, expected_lifetime="long",
    )
    assert ok1
    await db.commit()

    ok2 = await provider.add_semantic_memory(
        user_id=TEST_USER_ID, category="constraint", content=content,
        confidence=0.9, expected_lifetime="long",
    )
    assert ok2
    await db.commit()

    count = (await db.execute(
        text("SELECT COUNT(*) FROM semantic_memories WHERE user_id = :uid"),
        {"uid": TEST_USER_ID},
    )).scalar()
    assert count == 1, f"Expected 1 row after dedup, got {count}"
    print(f"  (b) DEDUP OK: count={count}")


@pytest.mark.asyncio
async def test_c_search(provider, db):
    _reset_dedupe_cache()

    content = "Test content C: FastAPI PostgreSQL vector similarity search with HNSW"
    ok = await provider.add_semantic_memory(
        user_id=TEST_USER_ID, category="decision_pattern", content=content,
        confidence=0.85, expected_lifetime="medium",
    )
    assert ok
    await db.commit()

    results = await provider.search_semantic_memories(
        user_id=TEST_USER_ID,
        query="semantic search PostgreSQL pgvector",
        limit=5,
    )
    assert len(results) >= 1, f"Expected >= 1 result, got {len(results)}"
    r = results[0]
    assert r["score"] > 0.5, f"Score too low: {r['score']}"
    assert r["id"] and r["category"] and r["created_at"]
    assert "confidence" in r
    print(f"  (c) SEARCH OK: score={r['score']:.4f}, category={r['category']}")


@pytest.mark.asyncio
async def test_d_min_score_filter(provider, db):
    results = await provider.search_semantic_memories(
        user_id=TEST_USER_ID,
        query="completely unrelated noise xyz123",
        limit=5,
        min_score=0.99,
    )
    assert len(results) == 0, f"Expected empty, got {len(results)}"
    print("  (d) MIN_SCORE FILTER OK: empty")


@pytest.mark.asyncio
async def test_e_cleanup(provider, db):
    _reset_dedupe_cache()
    await db.execute(
        text("DELETE FROM semantic_memories WHERE user_id = :uid"),
        {"uid": TEST_USER_ID},
    )
    await db.commit()
    count = (await db.execute(
        text("SELECT COUNT(*) FROM semantic_memories WHERE user_id = :uid"),
        {"uid": TEST_USER_ID},
    )).scalar()
    assert count == 0
    print("  (e) CLEANUP OK")
