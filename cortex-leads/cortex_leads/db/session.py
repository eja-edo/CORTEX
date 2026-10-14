from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cortex_leads.config import get_settings
from cortex_leads.db.models import Tenant


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().DATABASE_URL, pool_pre_ping=True)


async def _begin(session: AsyncSession, tenant_id: UUID, role: str | None) -> None:
    # set_config(..., true) == SET LOCAL, but accepts bind params. Dies with the txn.
    await session.execute(
        text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
    if role:
        await session.execute(text(f"set local role {role}"))


@asynccontextmanager
async def _scoped(tenant_id: UUID, role: str | None) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
        async with session.begin():  # commits on success, rolls back on error
            await _begin(session, tenant_id, role)
            yield session


@asynccontextmanager
async def tenant_session(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """One transaction scoped to a tenant (DESIGN A1); RLS does the filtering."""
    async with _scoped(tenant_id, None) as s:
        yield s


@asynccontextmanager
async def supervisor_session(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """Same, but as cl_supervisor: column grants only, no free text (DESIGN §5.6)."""
    async with _scoped(tenant_id, "cl_supervisor") as s:
        yield s


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Only for tables without RLS: tenant, connector, api_key."""
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
        async with session.begin():
            yield session


async def list_active_tenants(session: AsyncSession) -> list[UUID]:
    rows = await session.execute(select(Tenant.id).where(Tenant.status == "active"))
    return list(rows.scalars())
