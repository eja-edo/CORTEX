"""A new sandbox comes up ready to work (WP32): its domain pack loaded and the skills shipped for its kind live, because an empty
sandbox that silently does nothing is worse than none. One function for the console and the command line."""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.errors import CortexError
from cortex_leads.db import models as m
from cortex_leads.domain.pack import load_pack_file
from cortex_leads.sandbox.kinds import SandboxKind
from cortex_leads.skills.loader import sync_dir
from cortex_leads.skills.profile import SANDBOXES_DIR
from cortex_leads.skills.registry import promote

DEFAULT_BUDGET = {"runs_per_day": 200, "drafts_per_staff_per_day": 20, "tokens_per_day": 500_000}


async def create_sandbox(session: AsyncSession, tenant_id: UUID, kind: SandboxKind, *, name: str, title: str | None = None,
                         sandbox_id: UUID | None = None) -> m.Sandbox:
    if not kind.profile:
        raise CortexError(f"{kind.purpose} cannot be created yet: {kind.reason or 'no profile'}")
    kw = {"id": sandbox_id} if sandbox_id else {}
    sb = m.Sandbox(tenant_id=tenant_id, name=name, title=title, purpose=kind.purpose, profile_ref=kind.profile,
                   budget=DEFAULT_BUDGET, send_mode="manual", **kw)
    folder = SANDBOXES_DIR / kind.directory
    if (folder / "domain.yaml").is_file():
        sb.domain_pack = load_pack_file(folder / "domain.yaml").model_dump(mode="json")
    session.add(sb)
    await session.flush()
    if (folder / "skills").is_dir():  # draft -> shadow -> live, as `dev setup` does
        for row in await sync_dir(session, tenant_id, sb.id, folder / "skills"):
            if row.name in kind.skills_off:
                continue
            await promote(session, sb.id, row.name, row.version, "shadow")
            await promote(session, sb.id, row.name, row.version, "live")
    return sb
