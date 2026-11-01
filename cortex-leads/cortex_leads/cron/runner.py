"""Cron runner (WP19): once per worker pass, for every active sandbox, the jobs of its purpose whose slot
has come. Idempotent: the output row is unique per slot, so a repeat pass writes and pushes nothing."""
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.sandbox.kinds import kind_of
from cortex_leads.supervisor.narrative import narrate

log = logging.getLogger(__name__)


async def cron_once(now: datetime, gateway: Any = None) -> int:
    """Returns how many outputs were written. With a gateway the weekly digest also gets an LLM summary."""
    async with system_session() as s:
        tenants = (await s.execute(select(m.Tenant.id, m.Tenant.timezone).where(m.Tenant.status == "active"))).all()
    made = 0
    for tid, tz in tenants:
        async with tenant_session(tid) as session:
            for sb in (await session.execute(select(m.Sandbox).where(m.Sandbox.status == "active"))).scalars().all():
                for slot_of, job in (kind_of(sb.purpose).jobs() if kind_of(sb.purpose) else []):
                    if (slot := slot_of(now, tz)) is None:
                        continue
                    try:
                        async with session.begin_nested():  # one failing job costs itself, not the tenant
                            out = await job(session, sb, tz, now, slot)
                        made += out is not None
                        if gateway is not None and isinstance(out, m.Digest) and out.kind == "weekly":
                            async with session.begin_nested():  # the summary is a bonus: its failure keeps the digest
                                await narrate(session, sb, out, gateway, now)
                    except Exception:
                        log.exception("cron job failed: %s", sb.purpose)
    return made
