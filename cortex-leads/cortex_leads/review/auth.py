"""X-Api-Key auth. Tenant and role come from the key row, never from the request (DESIGN A3)."""
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from cortex_leads.auth.roles import ApiRole
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session


@dataclass(frozen=True)
class Caller:
    tenant_id: UUID
    role: str
    staff_ref: str | None


def require(*roles: ApiRole) -> Callable[..., object]:
    async def dep(x_api_key: str | None = Header(default=None)) -> Caller:
        if not x_api_key:
            raise HTTPException(401, "missing X-Api-Key")
        digest = hashlib.sha256(x_api_key.encode()).hexdigest()
        async with system_session() as s:
            row = (await s.execute(select(m.ApiKey).where(
                m.ApiKey.key_hash == digest, m.ApiKey.revoked_at.is_(None)))).scalar_one_or_none()
        if row is None:
            raise HTTPException(401, "invalid api key")
        if row.role not in roles:
            raise HTTPException(403, "role not allowed")
        return Caller(row.tenant_id, row.role, row.staff_ref)

    return Depends(dep)
