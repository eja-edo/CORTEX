"""
Integration test: Zep down → PgVector fallback in chat flow.

Verifies that memory extraction and memory search continue to work
when Zep Cloud is completely unavailable (SemanticMemoryUnavailable).

Uses a real database session. Seeded conversation/messages reference an
existing user+workspace from the dev database, then clean up after.

Run: python test_m4_zep_down_chat_flow.py

Requires: dev database running with all tables migrated.
"""
import os
import json
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, PropertyMock

os.environ.setdefault(
    "ASYNC_DATABASE_URL",
    "postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db",
)

from sqlalchemy import text
from app.database_async import AsyncSessionLocal
from app.services.semantic_memory_provider import SemanticMemoryUnavailable
from app.utils.logger import get_logger

logger = get_logger(__name__)

EXISTING_USER_ID = "47fa05f1-40b0-4804-8036-e9978fcaf7d9"
EXISTING_WS_ID = "64ae9b68-af38-4ab6-b4a9-71f2f98b4d86"

CONVERSATION_ID = str(uuid.uuid4())

MOCK_EXTRACTION_RESPONSE = json.dumps({
    "episodic_summary": "Test episodic summary about pgvector integration.",
    "title": "M4 Integration Test",
    "semantic_memories": [
        {"category": "project", "content": "Uses pgvector for vector search", "confidence": 0.95, "expected_lifetime": "permanent"},
        {"category": "preference", "content": "Prefers Python with async patterns", "confidence": 0.85, "expected_lifetime": "long"},
    ],
})


async def _cleanup(skip_conversation: bool = False):
    logger.info("Cleaning up test data...")
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM semantic_memories WHERE user_id = :uid"),
            {"uid": EXISTING_WS_ID},
        )
        if not skip_conversation:
            await db.execute(
                text("DELETE FROM agent_messages WHERE conversation_id = :cid"),
                {"cid": CONVERSATION_ID},
            )
            await db.execute(
                text("DELETE FROM agent_conversations WHERE id = :cid"),
                {"cid": CONVERSATION_ID},
            )
        await db.commit()


async def _seed_conversation():
    logger.info("Seeding test conversation...")
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        await db.execute(
            text("""
                INSERT INTO agent_conversations (id, user_id, workspace_id, title, created_at, updated_at)
                VALUES (:id, :uid, :wid, :title, :now, :now)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": CONVERSATION_ID,
                "uid": EXISTING_USER_ID,
                "wid": EXISTING_WS_ID,
                "title": "M4 Test Conversation",
                "now": now,
            },
        )
        for i in range(6):
            await db.execute(
                text("""
                    INSERT INTO agent_messages (id, conversation_id, role, content, created_at)
                    VALUES (:id, :cid, :role, :content, :now)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "cid": CONVERSATION_ID,
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": f"Test message {i}",
                    "now": now,
                },
            )
        await db.commit()


async def test_extract_and_store_with_zep_down():
    """Full extract_and_store pipeline with Zep down: writes to PgVector."""
    await _cleanup(skip_conversation=False)
    await _seed_conversation()

    mock_response = MagicMock()
    mock_response.content = MOCK_EXTRACTION_RESPONSE

    from app.services.memory_extraction_service import extract_and_store

    with patch("app.services.memory_extraction_service._model_client.generate") as mock_gen:
        mock_gen.return_value = ("test-model", mock_response)

        with patch(
            "app.services.zep_memory.ZepMemoryProvider.ensure_user",
            side_effect=SemanticMemoryUnavailable("Simulated Zep 503 Outage"),
        ), patch(
            "app.services.zep_memory.ZepMemoryProvider.add_semantic_memories_batch",
            side_effect=SemanticMemoryUnavailable("Simulated Zep 503 Outage"),
        ):
            async with AsyncSessionLocal() as db:
                result = await extract_and_store(
                    conversation_id=CONVERSATION_ID,
                    db=db,
                )

    assert result["success"] is True, f"Expected success, got: {result}"
    assert result["semantic_count"] == 2, (
        f"Expected 2 semantic memories stored, got {result['semantic_count']}"
    )
    assert result["episodic_stored"] is True
    assert result["model_used"] == "test-model"

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            text("SELECT content, category FROM semantic_memories WHERE user_id = :uid ORDER BY created_at"),
            {"uid": EXISTING_WS_ID},
        )).fetchall()
    contents = [r[0] for r in rows]
    assert "Uses pgvector for vector search" in contents, f"Missing memory, got: {contents}"
    assert "Prefers Python with async patterns" in contents, f"Missing memory, got: {contents}"

    await _cleanup(skip_conversation=True)
    print("  ✓ test_extract_and_store_with_zep_down: memories written to PgVector")


async def test_extract_memory_handler_with_zep_down():
    """Memory search tool works via PgVector when Zep is down."""
    await _cleanup(skip_conversation=True)

    async with AsyncSessionLocal() as db:
        from app.services.pgvector_memory_provider import PgVectorMemoryProvider
        prov = PgVectorMemoryProvider(db)
        count = 0
        for mem in [
            {"category": "preference", "content": "Loves PostgreSQL JSONB", "confidence": 0.92, "expected_lifetime": "permanent"},
            {"category": "project", "content": "Building a chat application with FastAPI", "confidence": 0.88, "expected_lifetime": "long"},
        ]:
            ok = await prov.add_semantic_memory(user_id=EXISTING_WS_ID, **mem)
            if ok:
                count += 1
        await db.commit()
    assert count == 2, f"Expected 2 seeded, got {count}"

    from app.ai.tools.extract_memory import extract_memory_handler

    mock_ctx = MagicMock()
    mock_ctx.workspace_id = EXISTING_WS_ID
    mock_ctx.user_id = EXISTING_USER_ID

    mock_sync_session = MagicMock()
    mock_ctx.get_sync_db.return_value.__enter__.return_value = mock_sync_session

    @asynccontextmanager
    async def fake_async_db():
        async with AsyncSessionLocal() as db:
            yield db

    mock_ctx.async_db = fake_async_db

    with patch(
        "app.services.zep_memory.ZepMemoryProvider.search_semantic_memories",
        side_effect=SemanticMemoryUnavailable("Simulated Zep 503 Outage"),
    ):
        result = await extract_memory_handler(
            {"query": "PostgreSQL FastAPI", "limit": 5},
            mock_ctx,
        )

    assert result["success"] is True, f"Expected success, got: {result}"
    assert result["memory_count"] >= 1, (
        f"Expected at least 1 memory result, got {result['memory_count']}"
    )
    result_text = result.get("result", "")
    assert "Loves PostgreSQL JSONB" in result_text or "Building a chat application" in result_text, (
        f"Expected seeded memory in search results, got: {result_text[:200]}"
    )

    await _cleanup(skip_conversation=True)
    print("  ✓ test_extract_memory_handler_with_zep_down: search falls back to PgVector")


async def main():
    logger.info("M4: Zep-down chat flow integration tests")
    await _cleanup(skip_conversation=False)
    try:
        await test_extract_and_store_with_zep_down()
        await test_extract_memory_handler_with_zep_down()
    finally:
        await _cleanup(skip_conversation=False)
    print("All M4 integration tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
