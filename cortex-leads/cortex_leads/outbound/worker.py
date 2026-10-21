"""Outbox worker (DESIGN A9, §5.2): the only code that POSTs to a bridge. Queued rows are taken
FOR UPDATE SKIP LOCKED; the lock is held across the HTTP call, so a crash rolls the row back to
`queued` and the bridge's action_id idempotency absorbs the repeat."""
import logging
from datetime import datetime, timedelta
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.channels.policy import window_state
from cortex_leads.config import get_settings
from cortex_leads.db import models as m
from cortex_leads.db.session import list_active_tenants, system_session, tenant_session
from cortex_leads.outbound.action_format import build_action, encode, parse_result

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
BACKOFF_S = 30  # attempt n waits 30 * 4**(n-1) seconds
NO_FALLBACK = {"STALE", "PAUSED"}  # the customer moved on / the kill switch is on: nothing for staff


def _log(session: AsyncSession, row: m.Outbox, decision: str, reason: str | None, now: datetime) -> None:
    run_id = row.source.get("run_id")
    session.add(m.DecisionLog(  # no customer text, ever
        tenant_id=row.tenant_id, run_id=UUID(run_id) if run_id else None,
        conversation_id=row.conversation_id, decision=decision, reason_code=reason, at=now,
        detail={"outbox_id": str(row.id), "actor_kind": row.actor.split(":")[0],
                "attempts": row.attempts}))


async def _end(session: AsyncSession, row: m.Outbox, status: str, reason: str, now: datetime,
               decision: str) -> None:
    """Terminal non-sent state. ai:* falls back to manual: staff gets a fresh proposed draft."""
    row.status, row.reason = status, reason
    _log(session, row, decision, reason, now)
    draft = await session.get(m.Draft, row.draft_id) if row.draft_id else None
    if draft is None or draft.status not in ("approved", "proposed"):
        return
    draft.status = "failed"
    if not row.actor.startswith("ai:") or reason in NO_FALLBACK:
        return
    spoke = (await session.execute(select(m.Message.id).where(
        m.Message.conversation_id == draft.conversation_id, m.Message.sender_role.in_(("customer", "staff")),
        m.Message.occurred_at > row.created_at).limit(1))).first()  # same clock as `now`
    if spoke is None:
        session.add(m.Draft(
            tenant_id=draft.tenant_id, sandbox_id=draft.sandbox_id, conversation_id=draft.conversation_id,
            run_id=draft.run_id, status="proposed", text=draft.text, claims=draft.claims,
            reason_code=draft.reason_code))
        _log(session, row, "fallback_manual", reason, now)


async def _post_mark(session: AsyncSession, client: httpx.AsyncClient, row: m.Outbox, conv: m.Conversation,
                     cn: m.Connector, now: datetime) -> None:
    """add_tag / add_note (WP24). Same signed door as a message; none of the customer-facing rules apply."""
    out = cn.outbound or {}
    if row.kind not in (out.get("capabilities") or []):
        return await _end(session, row, "cancelled", "OUTBOUND_DISABLED", now, "send_cancelled")
    row.status = "sending"
    await session.flush()
    body, headers = encode(build_action(row, conv, cn, window_state(conv.channel_kind, conv.last_customer_at, now)),
                           Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(cn.secret_enc), now)
    try:
        r = await client.post(out["url"], content=body, headers=headers, timeout=15)
        try:
            data = r.json()
        except ValueError:
            data = None
        kind, reason, _ = parse_result(r.status_code, data)
    except httpx.HTTPError:
        kind, reason = "error", "RETRY"
    if kind == "sent":
        row.status, row.sent_at, row.reason = "sent", now, None
        _log(session, row, "mark_sent", None, now)
    elif kind == "refused":  # a bridge that has no tags (Messenger) says NOT_SUPPORTED: that is its answer, not an error
        await _end(session, row, "refused", reason, now, "mark_refused")
    else:
        row.attempts += 1
        if reason == "RETRY" and row.attempts < MAX_ATTEMPTS:
            row.status, row.not_before = "queued", now + timedelta(seconds=BACKOFF_S * 4 ** (row.attempts - 1))
        else:
            await _end(session, row, "error", "RETRIES_EXHAUSTED" if reason == "RETRY" else "BRIDGE_ERROR", now, "mark_error")


async def _deliver(session: AsyncSession, client: httpx.AsyncClient, row: m.Outbox, now: datetime) -> None:
    conv = await session.get(m.Conversation, row.conversation_id)
    cn = await session.get(m.Connector, row.connector_id)
    sandbox = await session.get(m.Sandbox, conv.sandbox_id)
    ai = row.actor.startswith("ai:")
    out = cn.outbound or {}
    if row.kind != "message":
        if sandbox.status == "paused" or cn.status != "active" or not (out.get("enabled") and out.get("url")):
            return await _end(session, row, "cancelled", "PAUSED" if sandbox.status == "paused" else "OUTBOUND_DISABLED",
                              now, "send_cancelled")
        return await _post_mark(session, client, row, conv, cn, now)
    window = window_state(conv.channel_kind, conv.last_customer_at, now)  # recomputed: it may have closed
    if sandbox.status == "paused" or cn.status != "active":  # kill switch, checked again at send time
        return await _end(session, row, "cancelled", "PAUSED", now, "send_cancelled")
    if not out.get("enabled") or not out.get("url"):
        return await _end(session, row, "cancelled", "OUTBOUND_DISABLED", now, "send_cancelled")
    if ai and (await session.execute(select(m.Message.id).where(
            m.Message.conversation_id == conv.id, m.Message.sender_role.in_(("customer", "staff")),  # staff took over: stale too
            m.Message.occurred_at > row.created_at).limit(1))).first():
        return await _end(session, row, "cancelled", "STALE", now, "send_cancelled")
    if not window["open"] or (ai and window["basis"] != "free"):
        return await _end(session, row, "cancelled", "WINDOW_CLOSED", now, "send_cancelled")

    action = build_action(row, conv, cn, window)
    row.status, row.window = "sending", action["window"]
    await session.flush()
    body, headers = encode(action, Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(cn.secret_enc), now)
    try:
        r = await client.post(out["url"], content=body, headers=headers, timeout=15)
        try:
            data = r.json()
        except ValueError:
            data = None
        kind, reason, ext_id = parse_result(r.status_code, data)
    except httpx.HTTPError:
        kind, reason, ext_id = "error", "RETRY", None

    if kind == "sent":
        row.status, row.external_message_id, row.sent_at, row.reason = "sent", ext_id, now, None
        if not row.source.get("turn"):  # R36: a touch is a follow-up that went out; answering a waiting customer is not (N5)
            conv.touches += 1
        if (draft := await session.get(m.Draft, row.draft_id) if row.draft_id else None):
            draft.status = "sent"
        _log(session, row, "send_sent", None, now)
    elif kind == "refused":  # a normal answer, never retried (DESIGN §5.2)
        await _end(session, row, "refused", reason, now, "send_refused")
    else:
        row.attempts += 1
        if reason == "RETRY" and row.attempts < MAX_ATTEMPTS:
            row.status = "queued"
            row.not_before = now + timedelta(seconds=BACKOFF_S * 4 ** (row.attempts - 1))
            _log(session, row, "send_retry", reason, now)
        else:
            await _end(session, row, "error", "RETRIES_EXHAUSTED" if reason == "RETRY" else "BRIDGE_ERROR",
                       now, "send_error")


async def deliver_once(now: datetime, *, client: httpx.AsyncClient | None = None, limit: int = 50) -> int:
    """One pass over every active tenant (rotating who goes first). Returns rows handled."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        async with system_session() as s:
            tenants = await list_active_tenants(s)
        if tenants:
            start = int(now.timestamp() // 60) % len(tenants)
            tenants = tenants[start:] + tenants[:start]
        done = 0
        for tid in tenants:
            async with tenant_session(tid) as session:
                rows = (await session.execute(
                    select(m.Outbox).where(
                        m.Outbox.status == "queued",
                        or_(m.Outbox.not_before.is_(None), m.Outbox.not_before <= now))
                    .order_by(m.Outbox.created_at).limit(limit)
                    .with_for_update(skip_locked=True))).scalars().all()
                for row in rows:
                    row_id = row.id
                    try:
                        async with session.begin_nested():  # one bad row must not stop the batch
                            await _deliver(session, client, row, now)
                    except Exception:
                        log.exception("outbox delivery crashed")
                        tries = m.Outbox.attempts + 1
                        await session.execute(update(m.Outbox).where(m.Outbox.id == row_id).values(
                            attempts=tries, status=case((tries >= MAX_ATTEMPTS, "error"), else_="queued"),
                            reason=case((tries >= MAX_ATTEMPTS, "INTERNAL"), else_=None)))
                    done += 1
        return done
    finally:
        if own:
            await client.aclose()
