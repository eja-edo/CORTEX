import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from cortex_leads.config import get_settings
from cortex_leads.db.models import Base

target_metadata = Base.metadata


def _url() -> str:
    url = get_settings().DATABASE_OWNER_URL
    if not url:
        raise RuntimeError("CL_DATABASE_OWNER_URL is required to run migrations")
    return url


def _run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _main() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


asyncio.run(_main())
