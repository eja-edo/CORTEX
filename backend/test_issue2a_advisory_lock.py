"""
Tests for Issue 2a: advisory lock prevents concurrent memory extraction.

Verifies:
- Helper skips when below threshold or summarizer is None
- Helper acquires the advisory lock before calling summarize_conversation
- Helper skips calling summarize_conversation if the advisory lock is held by another session
- Lock releases on transaction commit
"""
import os
import asyncio
import sys
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

from sqlalchemy import text

os.environ.setdefault(
    'ASYNC_DATABASE_URL',
    'postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db'
)


async def test_helper_skips_when_threshold_not_reached():
    from app.ai.agents.agent_service import _maybe_trigger_memory_extraction

    fake_summarizer = MagicMock()
    fake_summarizer.MESSAGE_THRESHOLD = 20
    fake_conv = MagicMock()
    fake_conv.id = uuid4()
    fake_conv.message_count = 5

    captured = {}

    async def tracking(*args, **kwargs):
        captured["called"] = True
        return True

    fake_summarizer.summarize_conversation = AsyncMock(side_effect=tracking)
    fake_db = MagicMock()

    await _maybe_trigger_memory_extraction(fake_summarizer, fake_conv, fake_db)

    assert "called" not in captured
    fake_db.execute.assert_not_called()


async def test_helper_skips_when_summarizer_is_none():
    from app.ai.agents.agent_service import _maybe_trigger_memory_extraction

    fake_conv = MagicMock()
    fake_conv.id = uuid4()
    fake_conv.message_count = 25
    fake_db = MagicMock()

    await _maybe_trigger_memory_extraction(None, fake_conv, fake_db)
    fake_db.execute.assert_not_called()


async def test_helper_skips_extraction_when_lock_held():
    """When another session holds the conv's advisory lock, helper must NOT call
    summarize_conversation AND must NOT raise (race-safe behavior)."""
    from app.ai.agents.agent_service import _maybe_trigger_memory_extraction
    from app.database_async import AsyncSessionLocal

    # Acquire the conv's advisory lock in a different session (simulating a
    # concurrent extraction in progress).
    stolen_conv_id = uuid4()

    # Manually acquire the lock in this background session and hold it.
    holder_done = asyncio.Event()
    proceed = asyncio.Event()

    async def hold_lock_then_release():
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))")
                .bindparams(k=stolen_conv_id.hex)
            )
            holder_done.set()
            await proceed.wait()
            await session.commit()

    holder_task = asyncio.create_task(hold_lock_then_release())
    await holder_done.wait()

    # Now invoke helper with same conv id. Helper should detect lock-held state
    # and skip calling summarize_conversation.
    fake_summarizer = MagicMock()
    fake_summarizer.MESSAGE_THRESHOLD = 20

    summarize_called = []
    async def tracking(*args, **kwargs):
        summarize_called.append(1)
        return {"success": True}
    fake_summarizer.summarize_conversation = AsyncMock(side_effect=tracking)
    fake_conv = MagicMock(id=stolen_conv_id, message_count=20)

    async with AsyncSessionLocal() as session:
        # Should not raise
        await _maybe_trigger_memory_extraction(fake_summarizer, fake_conv, session)
        try:
            await session.commit()
        except Exception:
            await session.rollback()

    # Release holder
    proceed.set()
    await holder_task

    assert len(summarize_called) == 0, (
        "summarize_conversation must not be called while a sibling session holds the lock"
    )


async def test_lock_releases_on_commit():
    from app.database_async import AsyncSessionLocal

    conv_id = uuid4()
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))")
            .bindparams(k=conv_id.hex)
        )
        assert r.scalar() is True
        await session.commit()

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))")
            .bindparams(k=conv_id.hex)
        )
        assert r.scalar() is True, "Lock should be released after commit"
        await session.commit()


async def test_helper_runs_extraction_when_lock_free():
    """When no concurrent holder, helper should call summarize_conversation once."""
    from app.ai.agents.agent_service import _maybe_trigger_memory_extraction
    from app.database_async import AsyncSessionLocal

    conv_id = uuid4()
    fake_summarizer = MagicMock()
    fake_summarizer.MESSAGE_THRESHOLD = 20
    called = []
    async def tracking(*args, **kwargs):
        called.append(1)
        return {"success": True}
    fake_summarizer.summarize_conversation = AsyncMock(side_effect=tracking)
    fake_conv = MagicMock(id=conv_id, message_count=20)

    async with AsyncSessionLocal() as session:
        await _maybe_trigger_memory_extraction(fake_summarizer, fake_conv, session)
        await session.commit()

    assert len(called) == 1, f"Helper should run extraction once, got {len(called)}"


async def main():
    await test_helper_skips_when_threshold_not_reached()
    print("✓ test_helper_skips_when_threshold_not_reached")
    await test_helper_skips_when_summarizer_is_none()
    print("✓ test_helper_skips_when_summarizer_is_none")
    await test_helper_skips_extraction_when_lock_held()
    print("✓ test_helper_skips_extraction_when_lock_held")
    await test_lock_releases_on_commit()
    print("✓ test_lock_releases_on_commit")
    await test_helper_runs_extraction_when_lock_free()
    print("✓ test_helper_runs_extraction_when_lock_free")
    print("All Issue-2a tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
