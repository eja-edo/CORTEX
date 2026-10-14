"""Staff review page (DESIGN §2.1, §5.7). Server-rendered, no JS: a to-do list for people, not a ranking.
Session = signed cookie holding the api_key row id (never the key itself); revocation is honoured
because the row is re-read on every request. CSRF token = HMAC of the session cookie (A6/R6 notes in PLAN §8.2)."""
import hashlib
import hmac
import importlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, select

from cortex_leads.channels.policy import window_state
from cortex_leads.config import get_settings
from cortex_leads.core.errors import CortexError
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.domain.pack import load_pack
from cortex_leads.review.api import ActionBody, act_on_draft
from cortex_leads.review.auth import Caller
from cortex_leads.skills.registry import TURN_EVENT

router = APIRouter()
COOKIE, LOGIN_COOKIE, TTL_S = "cl_staff", "cl_login_csrf", 12 * 3600
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                   autoescape=select_autoescape(["html"]))
OUTCOMES = {"won": "Đã chốt", "booked": "Đã đặt lịch", "lost": "Mua chỗ khác", "reopen": "Mở lại"}
MSGS = {"ok": "Đã lưu.", "STALE": "Khách vừa nhắn thêm — nháp đã cũ, hãy đọc lại tin mới.",
        "NOT_PROPOSED": "Nháp này đã được xử lý.", "bad": "Không thực hiện được.", "csrf": "Phiên hết hạn, thử lại.",
        "OUTBOUND_OFF": "Kênh này chưa bật gửi từ hệ thống — hãy tự gửi.",
        "CONNECTOR_TRUST": "Kênh này chưa được phép gửi từ hệ thống — hãy tự gửi.",
        "WINDOW_CLOSED": "Cửa sổ nhắn đã đóng — hãy tự liên hệ khách.",
        "OFFCHANNEL_DRAFT": "Nháp này dành cho gọi điện/Zalo, không gửi qua kênh được.",
        "OPTED_OUT": "Khách đã từ chối nhận tin.", "PAUSED": "Hệ thống đang tạm dừng gửi tin."}


def _memory() -> Any | None:  # WP9 lands in parallel; the page degrades without it
    try:
        return importlib.import_module("cortex_leads.memory.service")
    except ModuleNotFoundError:
        return None


def _sk() -> bytes:
    return hashlib.sha256(b"staff-ui|" + get_settings().CONNECTOR_SECRET_KEY.encode()).digest()


def _sig(data: str) -> str:
    return hmac.new(_sk(), data.encode(), hashlib.sha256).hexdigest()


@dataclass
class Session:
    caller: Caller
    csrf: str
    tz: ZoneInfo


def _redirect(url: str, status: int = 303) -> RedirectResponse:
    return RedirectResponse(url, status_code=status)


async def session_dep(request: Request) -> Session:
    cookie = request.cookies.get(COOKIE, "")
    kid, _, rest = cookie.partition(".")
    exp, _, sig = rest.partition(".")
    login = HTTPException(303, headers={"Location": "/staff/login"})
    if not (kid and exp.isdigit() and hmac.compare_digest(sig, _sig(f"{kid}.{exp}"))) or int(exp) < time.time():
        raise login
    try:
        key_id = UUID(kid)
    except ValueError:
        raise login from None
    async with system_session() as s:
        row = await s.get(m.ApiKey, key_id)
        tenant = await s.get(m.Tenant, row.tenant_id) if row else None
    if row is None or row.revoked_at or row.role not in ("staff", "owner") or tenant is None:
        raise login
    return Session(Caller(row.tenant_id, row.role, row.staff_ref), _sig("csrf|" + cookie)[:32],
                   ZoneInfo(tenant.timezone))


S = Depends(session_dep)


def check_csrf(sess: Session, token: str) -> None:  # DESIGN A6: every POST
    if not hmac.compare_digest(token, sess.csrf):
        raise HTTPException(403, "CSRF token missing or invalid")


def page(tpl: str, **ctx: Any) -> HTMLResponse:
    return HTMLResponse(_env.get_template(tpl).render(**ctx),
                        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


def _ago(then: datetime | None, now: datetime) -> str:
    if then is None:
        return "chưa rõ"
    mins = int((now - then).total_seconds() // 60)
    return f"{mins} phút" if mins < 90 else f"{mins // 60} giờ" if mins < 2880 else f"{mins // 1440} ngày"


def _window(kind: str, last: datetime | None, now: datetime, tz: ZoneInfo) -> dict[str, str]:
    w = window_state(kind, last, now)
    until = w["expires_at"].astimezone(tz).strftime("%H:%M %d/%m") if w["expires_at"] else ""
    if w["basis"] == "human_agent":  # R6: only a person typing by hand
        return {"cls": "warn", "text": f"Chỉ người gõ tay được gửi (đến {until})"}
    if w["open"]:
        return {"cls": "ok", "text": f"Cửa sổ mở đến {until}"}
    return {"cls": "bad", "text": "Cửa sổ đã đóng — hãy tự liên hệ khách"}


async def _audit(s: Any, c: Caller, tool: str, args: dict[str, Any]) -> None:
    s.add(m.ActionLog(tenant_id=c.tenant_id, action_id=uuid7(), actor=f"staff:{c.staff_ref or c.role}",
                      tool=tool, args_masked=args, status="ok", evidence={}))


def _staff(c: Caller) -> str:
    return c.staff_ref or c.role


def _safe(url: str) -> str:
    return url if url.startswith("/staff") and "//" not in url and "\\" not in url else "/staff"


@router.get("/login", response_class=HTMLResponse)
async def login_form(msg: str = "") -> HTMLResponse:
    token = secrets.token_urlsafe(24)
    resp = page("login.html", csrf=token, msg=MSGS.get(msg, ""))
    resp.set_cookie(LOGIN_COOKIE, token, httponly=True, samesite="strict", max_age=600, path="/staff")
    return resp


@router.post("/login")
async def login(request: Request, api_key: str = Form(...), csrf: str = Form("")) -> RedirectResponse:
    if not (c := request.cookies.get(LOGIN_COOKIE)) or not hmac.compare_digest(c, csrf):  # double-submit
        raise HTTPException(403, "CSRF token missing or invalid")
    async with system_session() as s:
        row = (await s.execute(select(m.ApiKey).where(
            m.ApiKey.key_hash == hashlib.sha256(api_key.strip().encode()).hexdigest(),
            m.ApiKey.revoked_at.is_(None)))).scalar_one_or_none()
    if row is None or row.role not in ("staff", "owner"):
        return _redirect("/staff/login?msg=bad")
    exp = int(time.time()) + TTL_S
    resp = _redirect("/staff")
    resp.set_cookie(COOKIE, f"{row.id}.{exp}.{_sig(f'{row.id}.{exp}')}", httponly=True, samesite="strict",
                    secure=request.url.scheme == "https", max_age=TTL_S, path="/staff")
    resp.delete_cookie(LOGIN_COOKIE, path="/staff")
    return resp


@router.post("/logout")
async def logout(sess: Session = S, csrf: str = Form("")) -> RedirectResponse:
    check_csrf(sess, csrf)
    resp = _redirect("/staff/login")
    resp.delete_cookie(COOKIE, path="/staff")
    return resp


@router.get("", response_class=HTMLResponse)
async def queue(request: Request, msg: str = "", sess: Session = S) -> HTMLResponse:
    now, c = datetime.now(UTC), sess.caller
    cards: list[dict[str, Any]] = []
    async with tenant_session(c.tenant_id) as s:
        packs = {sb.id: load_pack(sb) for sb in (await s.execute(select(m.Sandbox))).scalars()}
        rows = (await s.execute(
            select(m.Draft, m.Conversation, m.Contact, m.TriggerRun.event_type == TURN_EVENT)
            .join(m.Conversation, m.Conversation.id == m.Draft.conversation_id)
            .join(m.Contact, m.Contact.id == m.Conversation.contact_id)
            .outerjoin(m.TriggerRun, m.TriggerRun.id == m.Draft.run_id)
            .where(m.Draft.status == "proposed")  # a customer waiting for an answer goes first
            .order_by(func.coalesce(m.TriggerRun.event_type == TURN_EVENT, False).desc(), m.Draft.created_at)
            .limit(50))).all()
        for d, conv, ct, turn in rows:
            last = (await s.execute(select(m.Message.text).where(
                m.Message.conversation_id == conv.id, m.Message.sender_role == "customer")
                .order_by(m.Message.occurred_at.desc()).limit(1))).scalar_one_or_none()
            out = (await s.get(m.Connector, conv.connector_id)).outbound or {}
            intent = packs[d.sandbox_id].intents.get(conv.intent or "")
            cards.append({"kind": "draft", "id": d.id, "conv_id": conv.id, "name": ct.display_name or "Khách",
                          "asked": (last or "")[:200], "silent": _ago(conv.last_customer_at, now),
                          "intent": intent.label if intent else "", "text": d.text,
                          "reason": packs[d.sandbox_id].reason_label(d.reason_code) if d.reason_code else "Chưa rõ lý do",
                          "can_send": bool(out.get("enabled") and out.get("url")) and d.route == "channel",
                          "offchannel": d.route == "offchannel", "turn": bool(turn), "needs_human": d.needs_human,
                          "chan": {"messenger": "Messenger", "zalo_oa": "Zalo OA"}.get(conv.channel_kind, "nhắn tin"),
                          "window": _window(conv.channel_kind, conv.last_customer_at, now, sess.tz)})
        facts, mem = [], _memory()
        for sb_id in packs if mem else ():
            for f in await mem.pending_confirmations(s, sandbox_id=sb_id):
                ct = await s.get(m.Contact, f.contact_id)
                facts.append({"kind": "fact", "id": f.id, "conv_id": f.conversation_id, "fact_kind": f.kind,
                              "value": f.value, "name": (ct.display_name if ct else None) or "Khách"})
        await _audit(s, c, "staff_ui.queue", {"drafts": len(cards), "facts": len(facts)})
    return page("queue.html", cards=cards, facts=facts, csrf=sess.csrf, msg=MSGS.get(msg, ""))


@router.post("/draft/{draft_id}")
async def draft_action(draft_id: UUID, action: str = Form(...), edited_text: str = Form(""),
                       csrf: str = Form(""), sess: Session = S) -> RedirectResponse:
    check_csrf(sess, csrf)
    if action not in ("approved", "sent", "edited", "self", "skipped", "zalo"):
        raise HTTPException(422, "unknown action")
    now = datetime.now(UTC)
    try:  # reuse review.api's handler: same StaffAction row, same 409 STALE (R6)
        await act_on_draft(str(draft_id), ActionBody(action="sent" if action == "zalo" else action,
                                                     edited_text=edited_text or None), sess.caller, now)
        if action == "zalo" and (mem := _memory()):  # R39: the only path that sets offchannel_contact
            async with tenant_session(sess.caller.tenant_id) as s:
                await mem.mark_offchannel(s, conversation_id=(await s.get(m.Draft, draft_id)).conversation_id,
                                          channel="zalo_personal", staff_ref=_staff(sess.caller), now=now)
    except HTTPException as e:
        code = e.detail.get("code") if isinstance(e.detail, dict) else "bad"
        return _redirect(f"/staff?msg={code if code in MSGS else 'bad'}")
    return _redirect("/staff?msg=ok")


@router.get("/c/{conv_id}", response_class=HTMLResponse)
async def conversation(conv_id: UUID, msg: str = "", sess: Session = S) -> HTMLResponse:
    now, c, mem = datetime.now(UTC), sess.caller, _memory()
    async with tenant_session(c.tenant_id) as s:
        conv = await s.get(m.Conversation, conv_id)
        if conv is None:
            raise HTTPException(404, "not found")
        ct = await s.get(m.Contact, conv.contact_id)
        msgs = list(reversed((await s.execute(select(m.Message).where(m.Message.conversation_id == conv_id)
                              .order_by(m.Message.occurred_at.desc()).limit(10))).scalars().all()))
        facts = [f for f in (await mem.list_facts(s, contact_id=conv.contact_id, include_inactive=True)
                             if mem else []) if f.status in ("active", "candidate")]
        await _audit(s, c, "staff_ui.conversation", {"conversation_id": str(conv_id)})
    return page("conversation.html", conv=conv, name=(ct.display_name if ct else None) or "Khách",
                msgs=[{"who": {"customer": "Khách", "staff": "Nhân viên"}.get(x.sender_role, "Bot"),
                       "text": x.text, "at": x.occurred_at.astimezone(sess.tz).strftime("%H:%M %d/%m")}
                      for x in msgs], facts=facts, outcomes=OUTCOMES, csrf=sess.csrf, msg=MSGS.get(msg, ""),
                window=_window(conv.channel_kind, conv.last_customer_at, now, sess.tz), has_memory=mem is not None)


@router.post("/c/{conv_id}/do")
async def conversation_do(conv_id: UUID, op: str = Form(...), value: str = Form(""),
                          csrf: str = Form(""), sess: Session = S) -> RedirectResponse:
    check_csrf(sess, csrf)
    mem, c, now = _memory(), sess.caller, datetime.now(UTC)
    if mem is None:
        return _redirect(f"/staff/c/{conv_id}?msg=bad")
    who, to = f"staff:{_staff(c)}", f"/staff/c/{conv_id}"
    try:
        async with tenant_session(c.tenant_id) as s:
            if op == "promise":
                await mem.record_fact(s, conversation_id=conv_id, kind="promised_date", source=who, now=now,
                                      value={"date": date.fromisoformat(value).isoformat()}, evidence_msg_ids=[])
            elif op == "offchannel" and value in ("phone", "zalo_personal"):
                await mem.mark_offchannel(s, conversation_id=conv_id, channel=value, staff_ref=_staff(c), now=now)
            elif op == "outcome" and value in OUTCOMES:
                await mem.record_outcome(s, conversation_id=conv_id, status=value, source=who,
                                         evidence_msg_ids=[], now=now)
            else:
                raise HTTPException(422, "unknown op")
            await _audit(s, c, f"staff_ui.{op}", {"conversation_id": str(conv_id), "value": value})
    except (CortexError, ValueError):
        return _redirect(f"{to}?msg=bad")
    return _redirect(f"{to}?msg=ok")


@router.post("/fact/{fact_id}/{verb}")
async def fact_verb(fact_id: UUID, verb: str, back: str = Form("/staff"), csrf: str = Form(""),
                    sess: Session = S) -> RedirectResponse:
    check_csrf(sess, csrf)
    mem, c, now = _memory(), sess.caller, datetime.now(UTC)
    if verb not in ("confirm", "reject") or mem is None:
        raise HTTPException(404, "not found")
    try:
        async with tenant_session(c.tenant_id) as s:
            await getattr(mem, f"{verb}_fact")(s, fact_id, staff_ref=_staff(c), now=now)
            await _audit(s, c, f"staff_ui.fact_{verb}", {"fact_id": str(fact_id)})
    except CortexError:
        return _redirect(f"{_safe(back)}?msg=bad")
    return _redirect(f"{_safe(back)}?msg=ok")
