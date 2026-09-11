"""Pins `AsyncSessionLocal`'s actual contract (`app.database_async`).

Live incident: `agent_service.py` and `tool_execution_service.py`'s
parallel-tool-execution paths (`_exec_parallel`, under
`AGENT_PARALLEL_TOOL_EXECUTION`) were changed to acquire a session with
`db = AsyncSessionLocal()` instead of `async with AsyncSessionLocal() as
db:`, so that `db.close()` could be wrapped in `asyncio.shield()` for a
separate cancellation-safety fix (see `test_parallel_tool_session_cleanup.
py`). That broke immediately in production: `AsyncSessionLocal` is
`_AsyncSessionLocalProxy`, not a plain `async_sessionmaker` — calling it
only builds the proxy object, which has none of `AsyncSession`'s methods.
Every parallel tool call failed with `AttributeError:
'_AsyncSessionLocalProxy' object has no attribute 'scalars'`, and the
streaming path's `finally: await db.close()` then failed the exact same
way and crashed the whole turn. Nothing caught this before deploy because
no test in this suite had ever called `AsyncSessionLocal()` directly
without the sanctioned `async with` form.

**Why this resets the engine around the test.** `AsyncSessionLocal`'s
underlying engine (`_async_engine`/`_async_session_local` in
`database_async.py`) is a module-level singleton, lazily bound to whichever
event loop first calls `init_async_engine()`. pytest-asyncio gives each
test function its own event loop, so a singleton left bound from an
earlier test would raise "Future attached to a different loop" here
instead of the thing actually under test — the same hazard
`test_core_events.py`'s `async_db` fixture works around by using
`make_async_sessionmaker()` instead. This test needs `AsyncSessionLocal`
itself, not a substitute, so it resets the singleton before and after
instead of avoiding it.
"""

import pytest
from sqlalchemy import text

from app.database_async import AsyncSessionLocal, close_async_engine


@pytest.mark.asyncio
async def test_calling_AsyncSessionLocal_bare_has_none_of_AsyncSession_methods():
    """Documents the trap: `db = AsyncSessionLocal()` alone does not give
    you a session — it gives you the proxy waiting to be entered."""
    await close_async_engine()  # start from a clean singleton
    db = AsyncSessionLocal()
    assert not hasattr(db, "scalars")
    assert not hasattr(db, "execute")
    assert not hasattr(db, "close")
    await close_async_engine()


@pytest.mark.asyncio
async def test_aenter_on_AsyncSessionLocal_yields_a_real_working_session():
    """The correct way to get a real session outside `async with` — the
    shape `_exec_parallel` uses now: `db = await
    AsyncSessionLocal().__aenter__()`."""
    await close_async_engine()
    db = await AsyncSessionLocal().__aenter__()
    try:
        assert hasattr(db, "scalars")
        result = await db.execute(text("SELECT 1"))
        assert result.scalar() == 1
    finally:
        await db.close()
    await close_async_engine()


@pytest.mark.asyncio
async def test_the_shielded_close_pattern_from_exec_parallel_works_end_to_end():
    """The exact shape now in `agent_service.py`/`tool_execution_service.py`:
    acquire via `__aenter__()`, use it, close it under `asyncio.shield`."""
    import asyncio

    await close_async_engine()
    db = await AsyncSessionLocal().__aenter__()
    try:
        result = await db.execute(text("SELECT 1"))
        assert result.scalar() == 1
    finally:
        await asyncio.shield(db.close())
    await close_async_engine()
