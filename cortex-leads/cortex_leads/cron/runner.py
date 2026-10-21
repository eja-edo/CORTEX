"""Cron runner (WP19): once per worker pass, for every active sandbox, the jobs of its purpose whose slot
has come. Idempotent: the output row is unique per slot, so a repeat pass writes and pushes nothing."""
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from cortex_leads.cron.jobs import morning_list, scan_signals, weekly_digest
from cortex_leads.cron.schedule import morning_slot, weekly_slot
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.supervisor.narrative import narrate

log = logging.getLogger(__name__)
JOBS = {"customer_care": [(morning_slot, morning_list)],
        "owner_digest": [(morning_slot, scan_signals), (weekly_slot, weekly_digest)]}


async def cron_once(now: datetime, gateway: Any = None) -> int:
    """Returns how many outputs were written. With a gateway the weekly digest also gets an LLM summary."""
    async with system_session() as s:
        tenants = (await s.execute(select(m.Tenant.id, m.Tenant.timezone).where(m.Tenant.status == "active"))).all()
    made = 0
    for tid, tz in tenants:
        async with tenant_session(tid) as session:
            for sb in (await session.execute(select(m.Sandbox).where(m.Sandbox.status == "active"))).scalars().all():
                for slot_of, job in JOBS.get(sb.purpose, []):
                    if (slot := slot_of(now, tz)) is None:
                        continue
                    try:
                        async with session.begin_nested():  # one failing job costs itself, not the tenant
                            out = await job(session, sb, tz, now, slot)
                        made += out is not None
                        if gateway is not None and isinstance(out, m.Digest):
                            async with session.begin_nested():  # the summary is a bonus: its failure keeps the digest
                                await narrate(session, sb, out, gateway, now)
                    except Exception:
                        log.exception("cron job failed: %s", sb.purpose)
    return made
