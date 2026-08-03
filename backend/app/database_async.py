import asyncio
from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_async_engine: Optional[AsyncEngine] = None
_async_session_local: Optional[async_sessionmaker[AsyncSession]] = None


async def init_async_engine() -> AsyncEngine:
    """Create the main async engine and sessionmaker, bound to the current loop.

    Must be called from inside the FastAPI lifespan (or any async context with
    a running event loop) so that asyncpg connections are created on the
    correct loop.  Callers should pair this with :func:`close_async_engine`.
    """
    global _async_engine, _async_session_local
    if _async_engine is not None:
        return _async_engine

    _async_engine = create_async_engine(
        settings.ASYNC_DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        future=True,
    )
    _async_session_local = async_sessionmaker(
        bind=_async_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    # Force the pool to establish a connection on this loop NOW so that
    # the internal asyncio.Lock and asyncpg connection objects are bound
    # to the correct event loop before any worker threads start.
    async with _async_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    logger.info("Async engine initialised on event loop %s", id(asyncio.get_running_loop()))
    return _async_engine


async def close_async_engine() -> None:
    """Dispose the main async engine, releasing all pooled connections."""
    global _async_engine, _async_session_local
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_local = None


def make_async_sessionmaker() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create a fresh async engine + sessionmaker.

    Workers running in a dedicated thread with their own event loop
    (e.g. LLMProcessorWorker, ReminderWorker, GoogleSyncWorker) must call
    this inside their async start() so that the engine's connection pool
    is bound to the worker's loop, not the FastAPI request loop.

    Callers are responsible for calling `await engine.dispose()` on
    shutdown to release connections cleanly.
    """
    engine = create_async_engine(
        settings.ASYNC_DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        future=True,
    )
    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    return engine, session_maker


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async SQLAlchemy session.

    The engine is initialised lazily on first call so this dependency
    works even when imported before any lifespan hook runs (e.g. during
    test collection).  Under normal operation ``init_async_engine`` is
    called explicitly inside the lifespan.
    """
    if _async_session_local is None:
        await init_async_engine()
    async with _async_session_local() as session:
        yield session


# ---------------------------------------------------------------------------
# Backward-compatible alias for test files that import AsyncSessionLocal
# directly.  The proxy lazily initialises the engine on first use within
# the caller's event loop.
# ---------------------------------------------------------------------------
class _AsyncSessionLocalProxy:
    """Drop-in replacement for the old module-level async_sessionmaker.

    Usage (unchanged)::

        async with AsyncSessionLocal() as session:
            ...
    """

    async def __aenter__(self):
        if _async_session_local is None:
            await init_async_engine()
        self._cm = _async_session_local()
        return await self._cm.__aenter__()

    async def __aexit__(self, *args):
        if hasattr(self, "_cm"):
            return await self._cm.__aexit__(*args)


AsyncSessionLocal = _AsyncSessionLocalProxy
