"""Shared helpers for the console API tests."""
import hashlib

from httpx import AsyncClient
from sqlalchemy import func, select

from cortex_leads.auth.users import create_user
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session

PASSWORD = "Test-pass-12345"


async def account_for_key(key: str) -> str:
    """Tests still mint an `api_key_factory` key to say "an owner" or "staff nv1"; the console now signs people in by email and
    password, so this makes (or finds) the matching account and returns its email."""
    async with system_session() as s:
        row = (await s.execute(select(m.ApiKey).where(m.ApiKey.key_hash == hashlib.sha256(key.encode()).hexdigest()))).scalar_one()
    ref = row.staff_ref or row.role
    async with tenant_session(row.tenant_id) as s:
        found = (await s.execute(select(m.AppUser).where(m.AppUser.staff_ref == ref, func.lower(m.AppUser.role) == row.role))).scalar_one_or_none()
        if found is None:
            u = await create_user(s, row.tenant_id, email=f"{ref}@{row.tenant_id.hex[-10:]}.test", name=f"Người {ref}", role=row.role,
                                     password=PASSWORD, created_by="test", staff_ref=ref)
            return u.email
        return found.email


async def sign_in(client: AsyncClient, key: str) -> str:
    """Logs in (the cookie jar keeps the session) and returns the CSRF token the SPA would send."""
    email = await account_for_key(key)
    r = await client.post("/api/v1/session/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["csrf"]


def h(csrf: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf}

URL = "http://bridge/actions"


async def sql(owner_engine, stmt: str, **params) -> None:
    from sqlalchemy import text
    async with owner_engine.begin() as c:
        await c.execute(text(stmt), params)


def token_of(mailbox, n: int = -1) -> str:
    """The token in the link of the n-th mail sent."""
    import re

    return re.search(r"#token=([\w\-]+)", mailbox.sent[n]["body"]).group(1)


async def activate(client: AsyncClient, mailbox, password: str, n: int = -1):
    """What the invited person does: opens the link in the mail and chooses a password."""
    return await client.post("/api/v1/auth/reset", json={"token": token_of(mailbox, n), "password": password})
