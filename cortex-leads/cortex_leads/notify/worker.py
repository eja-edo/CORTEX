"""Push worker (WP17): queued notifications -> one Telegram message per kind per target.
Rows are claimed FOR UPDATE SKIP LOCKED like the outbox. No token or no target = `skipped`
(nothing to retry); a transport error retries with backoff, then `failed`."""
import logging
import re
from datetime import datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.config import get_settings
from cortex_leads.connectors.egress import EgressError, ensure_callable
from cortex_leads.db import models as m
from cortex_leads.db.session import list_active_tenants, system_session, tenant_session
from cortex_leads.lessons.recap import video_url
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


# Measured on a real channel (2026-10-22): 2000 characters and 2456 ASCII characters go through; 2975 characters of
# Vietnamese (6267 bytes), 4000 and 5000 come back as "The original message was too long". Whether the limit counts
# characters or bytes is not yet known, so a piece obeys both until it is.
_URL = re.compile(r"https?://\S+")
MEZON_MAX_CHARS = 2400
MEZON_MAX_BYTES = 2400


def split_for_mezon(text: str, max_chars: int = MEZON_MAX_CHARS, max_bytes: int = MEZON_MAX_BYTES) -> list[str]:
    """Pieces that each fit one Mezon message, cut at line ends (a homework line is never cut in half unless it alone is too
    long) and numbered "(1/3)" when there is more than one. Nothing is dropped."""
    room = max_chars - 8  # the "(1/3)\n" label
    fits = lambda t: len(t) <= room and len(t.encode()) <= max_bytes - 16
    pieces: list[str] = []
    cur = ""
    for line in text.split("\n"):
        while not fits(line):  # one line longer than a message: cut it at the largest prefix that fits
            cut = len(line)
            while cut > 1 and not fits(line[:cut]):
                cut -= max(1, cut // 20)
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(line[:cut])
            line = line[cut:]
        joined = f"{cur}\n{line}" if cur else line
        if fits(joined):
            cur = joined
        else:
            pieces.append(cur)
            cur = line
    if cur or not pieces:
        pieces.append(cur)
    return pieces if len(pieces) == 1 else [f"({i}/{len(pieces)})\n{p}" for i, p in enumerate(pieces, 1)]


async def _send_mezon(client: httpx.AsyncClient, url: str, text: str) -> bool:
    """A Mezon channel webhook (https://mezon.ai/docs/developer/webhooks/channel-webhook): POST
    {"type": "hook", "message": {"t": <text>}}. The server answers 200 with an empty body even to a shape it ignores or
    a text it finds too long (it posts "The original message was too long"), so the shape and `split_for_mezon` matter
    more than the status. Pieces go in order; if one fails the whole push is retried, which can repeat the first ones."""
    try:
        await ensure_callable(url)
    except EgressError as e:  # an address that should never have been saved, or whose name now points inside: not called
        log.warning("mezon target refused (%s)", e.code)
        return False
    try:
        for piece in split_for_mezon(text):
            marks = [{"type": "lk", "s": u.start(), "e": u.end()} for u in _URL.finditer(piece)]  # a link is clickable
            r = await client.post(url, timeout=10, follow_redirects=False, json={"type": "hook", "message": {"t": piece, **({"mk": marks} if marks else {})}})
            if r.status_code >= 300:
                return False
        return True
    except httpx.HTTPError:
        return False


def route(targets: list[m.NotifyTarget], sandbox_id: object, classes: frozenset = frozenset()) -> list[m.NotifyTarget]:
    """Where what one sandbox made is posted: the targets bound to that sandbox if there are any, else the business's general ones.
    A target bound to another sandbox never gets it, and neither does one that belongs to a class (`classes`: their ids): that one gets
    only that class's lessons."""
    targets = [t for t in targets if t.id not in classes]
    return [t for t in targets if t.sandbox_id == sandbox_id] or [t for t in targets if t.sandbox_id is None]


async def _tenant_pass(session: AsyncSession, client: httpx.AsyncClient, now: datetime, token: str | None,
                       base_url: str | None) -> int:
    rows = list((await session.execute(
        select(m.Notification).where(
            m.Notification.status == "queued",
            or_(m.Notification.not_before.is_(None), m.Notification.not_before <= now))
        .order_by(m.Notification.created_at).limit(200).with_for_update(skip_locked=True))).scalars())
    if not rows:
        return 0
    active = list((await session.execute(select(m.NotifyTarget).where(m.NotifyTarget.active.is_(True)))).scalars())
    classes = frozenset((await session.execute(select(m.Class.notify_target_id).where(m.Class.notify_target_id.is_not(None)))).scalars())
    # A lesson recap carries the class's words, so it goes only to the team channel that was set up for it.
    dests = {"lesson": [t for t in active if t.kind == "mezon"],
             "grading": [t for t in active if t.kind == "mezon"],  # names a student and a mark: the team's own channel only
             None: [t for t in active if t.kind == "telegram" and t.sandbox_id is None] if token else []}
    batches: list[tuple[str, list[m.Notification]]] = []
    for kind in sorted({r.kind for r in rows}):
        group = [r for r in rows if r.kind == kind]
        batches += [(kind, [r]) for r in group] if kind in PER_ROW else [(kind, group)]
    for kind, group in batches:
        targets = dests.get(kind, dests[None])
        if not targets:
            for r in group:
                r.status = "skipped"
            continue
        if kind in PER_ROW:
            model = {"task": m.StaffTask, "digest": m.Digest, "proposal": m.Proposal, "lesson": m.Lesson, "grading": m.GradeItem}[kind]
            made = await session.get(model, group[0].ref_id)
            if made is None or (kind == "proposal" and made.status != "pending") or (kind == "lesson" and (made.status != "done" or made.released_at is None)) \
                    or (kind == "grading" and made.status != "proposed"):
                group[0].status = "skipped"  # gone, or already decided
                continue
            if kind in ("lesson", "grading"):
                targets = route(dests[kind], made.sandbox_id, classes)
                if kind == "lesson":  # a class with a channel of its own: its recaps go there and nowhere else
                    own = (await session.get(m.Class, made.class_id)).notify_target_id
                    targets = [t for t in dests["lesson"] if t.id == own] or targets if own else targets
                if not targets:
                    group[0].status = "skipped"
                    continue
            if kind == "lesson":
                src = await session.get(m.Class, made.class_id)
                payload = {"name": made.name, "class": src.name, **made.recap, "video_url": video_url(src.source_kind or "", made.file_id)}
                if src.source_kind == "upload":  # no public place for the file: the console page, where it can be watched again
                    payload |= {"video_url": f"{base_url.rstrip('/')}/app/lessons/{made.id}" if base_url else None, "video_label": "Xem lại buổi học"}
            elif kind == "grading":
                p = made.proposal or {}
                work = await session.get(m.Assignment, made.assignment_id)
                src = await session.get(m.Class, work.class_id)
                payload = {"id": str(made.id), "course": src.course_name or src.name, "student": made.student_name or "Học sinh (chưa có tên)", "work_title": work.title,
                           "total": p.get("total"), "max_points": p.get("max_points"), "criteria": p.get("criteria", []), "problems": p.get("problems", []),
                           "kinds": (made.content_kind or "").split(","), "ours": work.origin == "app", "classroom_link": made.link}
            else:
                payload = {"signal": made.signal, "target": made.target} if kind == "proposal" else made.payload
            text = render_row(kind, payload, base_url)
        else:
            text = render(kind, len(group), base_url)
        ok = False
        for t in targets:  # one delivered copy is enough: a failure on one chat must not repeat the rest
            sent = await (_send_mezon(client, t.address, text) if t.kind == "mezon"
                          else _send(client, token, t.address, text))
            ok = sent or ok
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
