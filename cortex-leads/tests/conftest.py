"""Shared fixtures (PLAN §3.4). Seeding goes through the OWNER connection (bypasses RLS);
code under test uses the app role, so RLS is real."""
import hashlib
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]


def _load_env_test() -> None:
    for line in (ROOT / ".env.test").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_env_test()

from cortex_leads.config import get_settings
from cortex_leads.core.ids import new_connector_id, uuid7
from cortex_leads.db import models as m
from cortex_leads.domain.pack import load_pack_file


@pytest.fixture(scope="session")
def db_ready() -> None:
    """Needs `make db-up`. Migrates to head with the owner URL."""
    get_settings.cache_clear()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def owner_engine(db_ready: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(get_settings().DATABASE_OWNER_URL, poolclass=NullPool)
    names = ", ".join(t.name for t in m.Base.metadata.sorted_tables)
    async with engine.begin() as c:
        await c.execute(text(f"TRUNCATE {names} CASCADE"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def seed(owner_engine: AsyncEngine) -> Callable[[Any], Awaitable[Any]]:
    async def _seed(obj: Any) -> Any:
        async with AsyncSession(owner_engine, expire_on_commit=False) as s:
            s.add(obj)
            await s.commit()
        return obj

    return _seed


@pytest.fixture
def tenant_factory(seed: Callable[[Any], Awaitable[Any]]) -> Callable[..., Awaitable[m.Tenant]]:
    async def make(name: str = "Acme", **kw: Any) -> m.Tenant:
        return await seed(m.Tenant(name=name, **kw))

    return make


@pytest.fixture
def sandbox_factory(seed: Callable[[Any], Awaitable[Any]]) -> Callable[..., Awaitable[m.Sandbox]]:
    async def make(tenant: m.Tenant, **kw: Any) -> m.Sandbox:
        kw.setdefault("name", "customer_care")
        kw.setdefault("profile_ref", "customer_drafter@1")
        kw.setdefault("domain_pack", load_pack_file(
            ROOT / "sandboxes" / "customer_care" / "domain.yaml").model_dump(mode="json"))
        kw.setdefault("budget", {"runs_per_day": 100, "drafts_per_staff_per_day": 20,
                                 "tokens_per_day": 100000})
        return await seed(m.Sandbox(tenant_id=tenant.id, **kw))

    return make


@pytest.fixture
def connector_factory(seed: Callable[[Any], Awaitable[Any]]) -> Callable[..., Awaitable[m.Connector]]:
    async def make(sandbox: m.Sandbox, *, secret: str = "test-connector-secret", **kw: Any) -> m.Connector:
        fernet = Fernet(get_settings().CONNECTOR_SECRET_KEY)
        kw.setdefault("channel_kind", "messenger")
        return await seed(m.Connector(
            id=new_connector_id(), tenant_id=sandbox.tenant_id, sandbox_id=sandbox.id,
            secret_enc=fernet.encrypt(secret.encode()), **kw))

    return make


@pytest.fixture
def conversation_factory(seed: Callable[[Any], Awaitable[Any]]) -> Callable[..., Awaitable[m.Conversation]]:
    async def make(connector: m.Connector, *, external_id: str = "conv-1", **kw: Any) -> m.Conversation:
        contact = await seed(m.Contact(
            tenant_id=connector.tenant_id, connector_id=connector.id,
            external_id=f"contact-{external_id}", display_name=kw.pop("display_name", "Khách A")))
        return await seed(m.Conversation(
            tenant_id=connector.tenant_id, sandbox_id=connector.sandbox_id,
            connector_id=connector.id, external_id=external_id, contact_id=contact.id,
            channel_kind=connector.channel_kind, **kw))

    return make


@pytest.fixture
def message_factory(seed: Callable[[Any], Awaitable[Any]]) -> Callable[..., Awaitable[m.Message]]:
    async def make(conversation: m.Conversation, text: str = "Giá bao nhiêu?", *,
                   sender_role: str = "customer", occurred_at: datetime | None = None,
                   **kw: Any) -> m.Message:
        kw.setdefault("external_id", f"msg-{uuid7()}")
        return await seed(m.Message(
            tenant_id=conversation.tenant_id, conversation_id=conversation.id,
            connector_id=conversation.connector_id, sender_role=sender_role, text=text,
            occurred_at=occurred_at or datetime.now(UTC), **kw))

    return make


@pytest.fixture
def catalog_factory(seed: Callable[[Any], Awaitable[Any]]) -> Callable[..., Awaitable[m.CatalogItem]]:
    async def make(tenant: m.Tenant, *, code: str = "KH01", **kw: Any) -> m.CatalogItem:
        kw.setdefault("name", "Khóa học 1")
        kw.setdefault("price", 2_500_000)
        return await seed(m.CatalogItem(tenant_id=tenant.id, code=code, **kw))

    return make


@pytest.fixture
def api_key_factory(seed: Callable[[Any], Awaitable[Any]]) -> Callable[..., Awaitable[tuple[m.ApiKey, str]]]:
    async def make(tenant: m.Tenant, role: str = "staff", staff_ref: str | None = "staff-1") -> tuple[m.ApiKey, str]:
        raw = f"clk_{uuid7().hex}"
        row = await seed(m.ApiKey(
            tenant_id=tenant.id, role=role, staff_ref=staff_ref,
            key_hash=hashlib.sha256(raw.encode()).hexdigest()))
        return row, raw  # raw key is only known here

    return make


@pytest_asyncio.fixture
async def app_client(db_ready: None, owner_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    from cortex_leads.app import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def freeze_time() -> datetime:
    """Time is injected: every time-dependent function takes `now` as a parameter."""
    return datetime(2026, 10, 12, 3, 0, tzinfo=UTC)


def as_uuid(v: Any) -> UUID:
    return v if isinstance(v, UUID) else UUID(str(v))
