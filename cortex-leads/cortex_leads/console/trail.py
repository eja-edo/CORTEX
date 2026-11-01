"""How the console writes its audit lines: the actor, role and tenant come from the session, never from the call site (A3)."""
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.audit.service import record, record_new
from cortex_leads.console.auth import Session


async def audit(sess: Session, db: AsyncSession, category: str, action: str, summary: str, **kw: Any) -> None:
    """In the caller's transaction: the line and the change commit together."""
    await record(db, sess.caller.tenant_id, actor=sess.actor, role=sess.caller.role, category=category, action=action,
                 summary=summary, **kw)


async def audit_new(sess: Session, category: str, action: str, summary: str, **kw: Any) -> None:
    """In its own transaction: for outcomes the request itself will not commit (a refusal)."""
    await record_new(sess.caller.tenant_id, actor=sess.actor, role=sess.caller.role, category=category, action=action,
                     summary=summary, **kw)


VIEW_ONCE = timedelta(minutes=15)  # the screen refetches every few seconds: opening is one event, not a hundred
