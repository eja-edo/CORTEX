"""Kill switch (DESIGN §10, nhóm C): stop the AI for a whole business, or one sandbox, in one call.
Pausing a sandbox is already honoured everywhere that matters: the engine makes no job, the runner leaves jobs alone,
the outbox worker cancels what is queued (`PAUSED`), the tools refuse. Staff keep answering by hand."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.audit.service import record
from cortex_leads.db import models as m


async def set_paused(session: AsyncSession, tenant_id: UUID, paused: bool, *, by: str, now: datetime,
                     sandbox_id: UUID | None = None, role: str = "system") -> int:
    """Returns how many sandboxes changed state. Always leaves an audit row, even when nothing changed."""
    q = select(m.Sandbox)
    if sandbox_id is not None:
        q = q.where(m.Sandbox.id == sandbox_id)
    changed = 0
    for sb in (await session.execute(q)).scalars():
        want = "paused" if paused else "active"
        if sb.status != want:
            sb.status = want
            changed += 1
    await record(session, tenant_id, actor=by, role=role, category="control", now=now,
                 action="killswitch.pause" if paused else "killswitch.resume",
                 summary=("Tạm dừng AI" if paused else "Cho AI chạy lại") + (" (một sandbox)" if sandbox_id else " (toàn bộ)"),
                 obj=("sandbox", str(sandbox_id), None) if sandbox_id else None, metadata={"changed": changed})
    return changed
