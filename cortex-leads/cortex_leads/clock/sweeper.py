"""The silence clock (DESIGN §5.2/§5.7): due conversations become events, once per silence."""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.db import models as m
from cortex_leads.db.session import list_active_tenants, system_session, tenant_session
from cortex_leads.skills.registry import TURN_EVENT
from cortex_leads.triggers.engine import on_conversation_event


async def _sweep_tenant(session: AsyncSession, tenant_id, tz: str, now: datetime, limit: int) -> int:
    c = m.Conversation
    turns = (await session.execute(  # DESIGN §5.7 `turn`: customers who finished talking come first
        select(c).where(c.reply_check_at.is_not(None), c.reply_check_at <= now, c.state == "open")
        .order_by(c.reply_check_at).limit(limit).with_for_update(skip_locked=True))).scalars().all()
    for conv in turns:
        conv.reply_check_at = None  # one shot per turn; the next customer message re-arms it
        await on_conversation_event(session, conv, TURN_EVENT, now)
    due = (await session.execute(
        select(c).where(c.next_check_at.is_not(None), c.next_check_at <= now, c.state == "open",
                        c.id.not_in([t.id for t in turns]))
        .order_by(c.next_check_at).limit(max(limit - len(turns), 0))
        .with_for_update(skip_locked=True))).scalars().all()
    today = now.astimezone(ZoneInfo(tz)).date()
    for conv in due:
        promised = conv.promised_date is not None and conv.promised_date <= today
        conv.next_check_at = None  # one shot per silence; a new message re-arms it, the engine may re-time
        await on_conversation_event(
            session, conv, "conversation.promised_date_reached" if promised else "conversation.silent", now)
    return len(turns) + len(due)


async def sweep_once(now: datetime, *, gateway=None, limit: int = 100) -> int:
    """Returns the number of conversations fired. With a gateway, pending jobs are run too."""
    async with system_session() as s:
        tenants = await list_active_tenants(s)
        tzs = dict((await s.execute(select(m.Tenant.id, m.Tenant.timezone))).all())
    if not tenants:
        return 0
    start = int(now.timestamp() // 60) % len(tenants)  # rotate who goes first: fairness
    tenants = tenants[start:] + tenants[:start]
    share = max(1, -(-limit // len(tenants)))
    fired = 0
    for tid in tenants:
        async with tenant_session(tid) as session:
            fired += await _sweep_tenant(session, tid, tzs[tid], now, min(share, limit - fired))
        if fired >= limit:
            break
    if gateway is not None:
        from cortex_leads.runner.customer_run import run_pending

        await run_pending(now, gateway)
    return fired
