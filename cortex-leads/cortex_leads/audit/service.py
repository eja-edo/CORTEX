"""The audit writer and its checks (DESIGN §5.14). One function records; every human action in the console goes through it."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.audit.context import current
from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m

MAX_METADATA = 20_000  # bytes of JSON: a snapshot to restore from, not a dump
MAX_VALUE = 500  # characters of one value inside `changes`
SECRET_KEYS = {"secret", "password", "token", "api_key", "key", "authorization", "secret_enc"}


def _clean(v: Any, depth: int = 0) -> Any:
    """Secrets never enter a snapshot, and one long value cannot swamp the row."""
    if depth > 6:
        return "…"
    if isinstance(v, dict):
        return {str(k): ("***" if str(k).lower() in SECRET_KEYS else _clean(x, depth + 1)) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_clean(x, depth + 1) for x in v][:100]
    if isinstance(v, datetime):
        return wire(v)
    if isinstance(v, str) and len(v) > MAX_VALUE * 4:
        return v[: MAX_VALUE * 4] + "…"
    return v


def _flat(d: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(d, dict):
        out: dict[str, Any] = {}
        for k, v in d.items():
            out.update(_flat(v, f"{prefix}{k}."))
        return out or ({prefix[:-1]: {}} if prefix else {})
    return {prefix[:-1]: d}


def _short(v: Any) -> Any:
    return v[:MAX_VALUE] + "…" if isinstance(v, str) and len(v) > MAX_VALUE else v


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    """What changed, field by field (dotted paths). Secret fields show as `***` on both sides."""
    b, a = _flat(_clean(before or {})), _flat(_clean(after or {}))
    return [{"field": k, "before": _short(b.get(k)), "after": _short(a.get(k))} for k in sorted({*b, *a}) if b.get(k) != a.get(k)]


def _digest(prev: str | None, row: m.AuditEvent) -> str:
    body = {"id": str(row.id), "tenant_id": str(row.tenant_id) if row.tenant_id else None, "at": wire(row.at), "actor": row.actor,
            "actor_role": row.actor_role, "category": row.category, "action": row.action, "result": row.result,
            "object_type": row.object_type, "object_id": row.object_id, "object_label": row.object_label, "summary": row.summary,
            "ip": row.ip, "user_agent": row.user_agent, "request_id": row.request_id, "session_id": row.session_id,
            "metadata": row.metadata_}
    return hashlib.sha256((prev or "").encode() + json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


async def record(session: AsyncSession, tenant_id: UUID | None, *, actor: str, role: str, category: str, action: str, summary: str,
                 result: str = "success", obj: tuple[str, str, str | None] | None = None, changes: list[dict[str, Any]] | None = None,
                 metadata: dict[str, Any] | None = None, now: datetime | None = None, once_within: timedelta | None = None,
                 ) -> m.AuditEvent | None:
    """Writes one event in the caller's transaction (it commits or rolls back with the change it describes).
    `once_within`: skip if the same actor did the same action on the same object that recently (opening a conversation
    twice in a minute is one visit). Returns None when skipped."""
    now = now or datetime.now(UTC)
    info = current()
    if tenant_id is not None:
        await session.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"audit:{tenant_id}"})  # one chain, in order
        if once_within is not None and obj is not None:
            recent = (await session.execute(select(m.AuditEvent.id).where(
                m.AuditEvent.actor == actor, m.AuditEvent.action == action, m.AuditEvent.object_id == obj[1],
                m.AuditEvent.at > now - once_within).limit(1))).first()
            if recent:
                return None
    meta = _clean(dict(metadata or {}))
    if changes:
        meta["changes"] = _clean(changes)
    if len(json.dumps(meta, ensure_ascii=False)) > MAX_METADATA:
        meta = {"truncated": True, "changes": meta.get("changes", [])[:20]}
    row = m.AuditEvent(
        id=uuid7(), tenant_id=tenant_id, at=now, actor=actor, actor_role=role, category=category, action=action, result=result,
        object_type=obj[0] if obj else None, object_id=obj[1] if obj else None, object_label=obj[2] if obj else None,
        summary=summary[:300], ip=info.ip, user_agent=info.user_agent, request_id=info.request_id, session_id=info.session_id,
        metadata_=meta)
    prev = None
    if tenant_id is not None:  # platform-scope rows are invisible to every tenant session, so they cannot be chained
        prev = (await session.execute(select(m.AuditEvent.hash).where(m.AuditEvent.tenant_id == tenant_id)
                                      .order_by(m.AuditEvent.seq.desc()).limit(1))).scalar()
    row.prev_hash, row.hash = prev, _digest(prev, row)
    if tenant_id is None:
        # No tenant can read a platform row back, so a plain INSERT ... RETURNING would be refused by the read policy.
        cols = {c.key: getattr(row, c.key if c.key != "metadata" else "metadata_") for c in m.AuditEvent.__table__.columns if c.key != "seq"}
        await session.execute(insert(m.AuditEvent.__table__).values(**cols))
        return row
    session.add(row)
    await session.flush()
    return row


async def verify(session: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    """Recompute the chain. A row edited or removed after the fact makes everything after it fail to link."""
    prev: str | None = None
    n = 0
    rows = (await session.execute(select(m.AuditEvent).where(m.AuditEvent.tenant_id == tenant_id).order_by(m.AuditEvent.seq))).scalars()
    for r in rows:
        n += 1
        if r.prev_hash != prev or r.hash != _digest(prev, r):
            return {"ok": False, "checked": n, "first_bad": wire(r.at), "seq": r.seq}
        prev = r.hash
    total = (await session.execute(select(func.count()).select_from(m.AuditEvent).where(m.AuditEvent.tenant_id == tenant_id))).scalar_one()
    return {"ok": True, "checked": n, "total": total}


async def record_new(tenant_id: UUID | None, **kw: Any) -> m.AuditEvent | None:
    """For events that happen when there is no transaction to join, or that must survive the request failing (a refusal, a
    failed sign-in). It never raises: losing an audit line must not turn a refusal into a 500."""
    import logging

    from cortex_leads.db.session import system_session, tenant_session

    try:
        async with (tenant_session(tenant_id) if tenant_id else system_session()) as s:
            return await record(s, tenant_id, **kw)
    except Exception:
        logging.getLogger(__name__).exception("audit event could not be written: %s", kw.get("action"))
        return None
