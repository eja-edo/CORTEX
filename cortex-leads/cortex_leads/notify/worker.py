"""Push worker (WP17): queued notifications -> one Telegram message per kind per target.
Rows are claimed FOR UPDATE SKIP LOCKED like the outbox. No token or no target = `skipped`
(nothing to retry); a transport error retries with backoff, then `failed`."""
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.config import get_settings
from cortex_leads.db import models as m
from cortex_leads.db.session import list_active_tenants, system_session, tenant_session
from cortex_leads.notify.service import PER_ROW, render, render_row

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
BACKOFF_S = 60
API = "https://api.telegram.org/bot{token}/sendMessage"


async def _send(client: httpx.AsyncClient, token: str, chat_id: str, text: str) -> bool:
    try:
        r = await client.post(API.format(token=token), timeout=10, json={
            "chat_id": chat_id, "text": text, "disable_web_page_preview": True})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def _tenant_pass(session: AsyncSession, client: httpx.AsyncClient, now: datetime, token: str | None,
                       base_url: str | None) -> int:
    rows = list((await session.execute(
        select(m.Notification).where(
            m.Notification.status == "queued",
            or_(m.Notification.not_before.is_(None), m.Notification.not_before <= now))
        .order_by(m.Notification.created_at).limit(200).with_for_update(skip_locked=True))).scalars())
    if not rows:
        return 0
    targets = list((await session.execute(select(m.NotifyTarget).where(
        m.NotifyTarget.active.is_(True), m.NotifyTarget.kind == "telegram"))).scalars())
    if not token or not targets:
        for r in rows:
            r.status = "skipped"
        return len(rows)
    batches: list[tuple[str, list[m.Notification]]] = []
    for kind in sorted({r.kind for r in rows}):
        group = [r for r in rows if r.kind == kind]
        batches += [(kind, [r]) for r in group] if kind in PER_ROW else [(kind, group)]
    for kind, group in batches:
        if kind in PER_ROW:
            model = {"task": m.StaffTask, "digest": m.Digest, "proposal": m.Proposal}[kind]
            made = await session.get(model, group[0].ref_id)
            if made is None or (kind == "proposal" and made.status != "pending"):  # gone, or already decided
                group[0].status = "skipped"
                continue
            text = render_row(kind, {"signal": made.signal, "target": made.target} if kind == "proposal"
                              else made.payload, base_url)
        else:
            text = render(kind, len(group), base_url)
        ok = False
        for t in targets:  # one delivered copy is enough: a failure on one chat must not repeat the rest
            ok = await _send(client, token, t.address, text) or ok
        for r in group:
            if ok:
                r.status, r.sent_at = "sent", now
                continue
            r.attempts += 1
            if r.attempts >= MAX_ATTEMPTS:
                r.status = "failed"
            else:
                r.not_before = now + timedelta(seconds=BACKOFF_S * 4 ** (r.attempts - 1))
    return len(rows)


async def notify_once(now: datetime, *, client: httpx.AsyncClient | None = None) -> int:
    own = client is None
    client = client or httpx.AsyncClient()
    s = get_settings()
    try:
        async with system_session() as sys_s:
            tenants = await list_active_tenants(sys_s)
        done = 0
        for tid in tenants:
            try:
                async with tenant_session(tid) as session:
                    done += await _tenant_pass(session, client, now, s.TELEGRAM_BOT_TOKEN, s.PUBLIC_BASE_URL)
            except Exception:
                log.exception("notify pass failed for a tenant")
        return done
    finally:
        if own:
            await client.aclose()
