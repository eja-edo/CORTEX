"""Hộp thư (WP27): conversations, one conversation with what the AI did and knows, and the staff actions on it.
Staff may read customer text (this is the one place, audited); the AI supervisor may not."""
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.channels.policy import window_state
from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import VIEW_ONCE, audit, audit_new
from cortex_leads.core.context import RunContext, Scope, StaffPrincipal
from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import wire, wire_date
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.domain.pack import load_pack
from cortex_leads.memory import service as memory
from cortex_leads.review.api import ActionBody, act_on_draft
from cortex_leads.skills.registry import TURN_EVENT
from cortex_leads.tools.booking import cancel_booking, open_slots
from cortex_leads.tools.registry import default_registry
from cortex_leads.tools.v0 import dropped_leads

router = APIRouter()
Filter = Literal["need_human", "waiting", "silent", "all"]
LIST_LIMIT = 50
LOG_LABELS = {
    "job_created": "AI nhận việc", "draft_proposed": "AI soạn nháp, đã qua bộ kiểm", "draft_blocked": "Nháp bị bộ kiểm chặn",
    "turn_handoff_blocked": "Chuyển cho nhân viên (nháp bị chặn)", "turn_hold_sent": "Báo khách đã chuyển người",
    "turn_hold_failed": "Báo khách thất bại", "turn_wait": "AI chờ khách nhắn thêm", "send_queued": "Tin xếp hàng chờ gửi",
    "send_sent": "Đã gửi tin cho khách", "send_cancelled": "Huỷ gửi", "send_refused": "Kênh từ chối gửi",
    "booking_made": "Giữ chỗ học thử", "booking_cancelled": "Huỷ lịch học thử", "run_none": "AI quyết định không nhắn",
    "run_blocked": "AI không chạy (khách đã dừng hoặc đã có kết quả)", "run_paused": "AI đang tạm dừng",
    "shadow_draft": "Bản thử viết nháp (không hiện cho ai)", "fallback_manual": "Chuyển sang nhân viên duyệt",
    "promise_closed_by_outcome": "Lời hẹn đóng vì đã có kết quả", "mark_sent": "Đã gắn nhãn trên nền tảng"}


def _now() -> datetime:
    return datetime.now(UTC)


def _w(kind: str, last: datetime | None, now: datetime) -> dict[str, Any]:
    w = window_state(kind, last, now)
    return {"open": w["open"], "basis": w["basis"], "expires_at": wire(w["expires_at"])}


async def _sets(s: AsyncSession, now: datetime) -> dict[str, list[m.Conversation]]:
    """The four lists, each ordered the way a person should work through it."""
    c = m.Conversation
    need_ids = [r for (r,) in (await s.execute(select(m.Draft.conversation_id).where(
        m.Draft.status == "proposed", m.Draft.needs_human.is_(True)).group_by(m.Draft.conversation_id)
        .order_by(func.min(m.Draft.created_at)))).all()]
    by_id = {x.id: x for x in (await s.execute(select(c).where(c.id.in_(need_ids)))).scalars()} if need_ids else {}
    open_q = select(c).where(c.state == "open", c.last_customer_at.is_not(None))
    waiting = (await s.execute(open_q.where(or_(c.last_staff_at.is_(None), c.last_staff_at < c.last_customer_at),
                                            c.last_customer_at > now - timedelta(hours=24))
                               .order_by(c.last_customer_at.asc()).limit(200))).scalars().all()
    silent: list[m.Conversation] = []
    for sb in (await s.execute(select(m.Sandbox).where(m.Sandbox.purpose == "customer_care"))).scalars():
        silent += await dropped_leads(s, sb.tenant_id, sb.id, now, limit=200)
    everyone = (await s.execute(open_q.order_by(c.updated_at.desc()).limit(200))).scalars().all()
    return {"need_human": [by_id[i] for i in need_ids if i in by_id], "waiting": list(waiting),
            "silent": sorted(silent, key=lambda x: x.last_customer_at), "all": list(everyone)}


@router.get("/conversations")
async def conversations(filter: Filter = "need_human", sess: Session = need("inbox.use")) -> dict[str, Any]:
    now = _now()
    async with tenant_session(sess.caller.tenant_id) as s:
        sets = await _sets(s, now)
        picked = sets[filter][:LIST_LIMIT]
        flag = {k: {x.id for x in v} for k, v in sets.items()}
        booked = {r for (r,) in (await s.execute(select(m.Booking.conversation_id).where(m.Booking.status == "confirmed"))).all()}
        items = []
        for conv in picked:
            ct = await s.get(m.Contact, conv.contact_id)
            last = (await s.execute(select(m.Message.text).where(
                m.Message.conversation_id == conv.id, m.Message.sender_role == "customer")
                .order_by(m.Message.occurred_at.desc()).limit(1))).scalar_one_or_none()
            badges = [k for k in ("need_human", "waiting", "silent") if conv.id in flag[k]]
            if conv.id in booked:
                badges.append("booked")
            if conv.promised_date:
                badges.append(f"promised:{wire_date(conv.promised_date)}")
            items.append({"id": str(conv.id), "name": (ct.display_name if ct else None) or "Khách", "snippet": (last or "")[:140],
                          "at": wire(conv.last_customer_at or conv.updated_at), "channel": conv.channel_kind,
                          "badges": badges, "state": conv.state})
    return {"items": items, "counts": {k: len(v) for k, v in sets.items()}}


def _fact_text(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(str(v) for v in value.values())
    return str(value)


@router.get("/conversations/{conversation_id}")
async def conversation(conversation_id: UUID, sess: Session = need("inbox.use")) -> dict[str, Any]:
    now = _now()
    async with tenant_session(sess.caller.tenant_id) as s:
        conv = await s.get(m.Conversation, conversation_id)
        if conv is None:
            raise HTTPException(404, "conversation not found")
        ct = await s.get(m.Contact, conv.contact_id)
        sandbox = await s.get(m.Sandbox, conv.sandbox_id)
        pack = load_pack(sandbox)
        msgs = list(reversed((await s.execute(select(m.Message).where(m.Message.conversation_id == conv.id)
                                              .order_by(m.Message.occurred_at.desc()).limit(40))).scalars().all()))
        drafts = (await s.execute(select(m.Draft, m.TriggerRun.event_type).outerjoin(m.TriggerRun, m.TriggerRun.id == m.Draft.run_id)
                                  .where(m.Draft.conversation_id == conv.id, m.Draft.status == "proposed")
                                  .order_by(m.Draft.created_at))).all()
        facts = [f for f in await memory.list_facts(s, contact_id=conv.contact_id, include_inactive=True)
                 if f.status in ("active", "candidate")]
        bookings = (await s.execute(select(m.Booking).where(m.Booking.conversation_id == conv.id, m.Booking.status == "confirmed"))).scalars().all()
        slots = await open_slots(s, sess.caller.tenant_id, now)
        log = (await s.execute(select(m.DecisionLog).where(m.DecisionLog.conversation_id == conv.id)
                               .order_by(m.DecisionLog.at.desc()).limit(10))).scalars().all()
        await audit(sess, s, "view", "conversation.viewed", "Xem hội thoại của khách", obj=("conversation", str(conv.id), None),
                    once_within=VIEW_ONCE)
    return {
        "id": str(conv.id), "name": (ct.display_name if ct else None) or "Khách", "channel": conv.channel_kind, "state": conv.state,
        "intent": pack.intents[conv.intent].label if conv.intent in pack.intents else None, "owner": conv.owner_staff_ref,
        "decision_maker": ct.decision_maker if ct else None, "promised_date": wire_date(conv.promised_date),
        "window": _w(conv.channel_kind, conv.last_customer_at, now),
        "messages": [{"id": str(x.id), "role": x.sender_role, "text": x.text, "at": wire(x.occurred_at)} for x in msgs],
        "drafts": [{"id": str(d.id), "text": d.text, "claims": d.claims, "needs_human": d.needs_human, "route": d.route,
                    "turn": ev == TURN_EVENT, "reason": pack.reason_label(d.reason_code) if d.reason_code else None,
                    "created_at": wire(d.created_at)} for d, ev in drafts],
        "facts": [{"id": str(f.id), "kind": f.kind, "text": _fact_text(f.value), "status": f.status,
                   "evidence": len(f.evidence_msg_ids or []), "by_ai": (f.source or "").startswith("ai:")} for f in facts],
        "bookings": [{"id": str(b.id), "slot": b.slot_code, "at": wire(b.starts_at),
                      "by_ai": b.actor.startswith("ai:")} for b in bookings],
        "open_slots": slots,
        "log": [{"at": wire(x.at), "label": LOG_LABELS.get(x.decision, x.decision), "skill": (x.detail or {}).get("skill")}
                for x in log]}


class DraftAction(BaseModel):
    action: Literal["approved", "sent", "edited", "self", "skipped"]
    edited_text: str | None = Field(default=None, max_length=2000)


DRAFT_VERB = {"approved": "duyệt gửi", "sent": "đã gửi tay", "edited": "sửa rồi gửi", "self": "nhân viên tự trả lời", "skipped": "bỏ qua"}


@router.post("/drafts/{draft_id}/action")
async def draft_action(draft_id: UUID, body: DraftAction, sess: Session = need("inbox.use")) -> dict[str, Any]:
    """The same function the old queue used: 'approved' goes send_message -> outbox -> bridge (A9)."""
    out = await act_on_draft(str(draft_id), ActionBody(**body.model_dump()), sess.caller, _now())
    await audit_new(sess, "data", f"draft.{body.action}", f"Xử lý tin nháp: {DRAFT_VERB[body.action]}",
                    obj=("draft", str(draft_id), None), metadata={"action": body.action, "edited": body.edited_text is not None})
    return out


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/conversations/{conversation_id}/reply")
async def reply(conversation_id: UUID, body: Reply, sess: Session = need("inbox.use")) -> dict[str, Any]:
    """A message a person typed in the console: a draft in their name, approved at once, so it still leaves through
    send_message -> outbox -> bridge and is bound by the channel window like everything else."""
    async with tenant_session(sess.caller.tenant_id) as s:
        conv = await s.get(m.Conversation, conversation_id)
        if conv is None:
            raise HTTPException(404, "conversation not found")
        d = m.Draft(tenant_id=conv.tenant_id, sandbox_id=conv.sandbox_id, conversation_id=conv.id, status="proposed",
                    text=body.text.strip(), claims=[], reason_code="khong_ro", route="channel")
        s.add(d)
        await s.flush()
        draft_id = d.id
    try:
        out = await act_on_draft(str(draft_id), ActionBody(action="approved"), sess.caller, _now())
        await audit_new(sess, "data", "message.sent", "Nhân viên gửi tin trả lời khách", obj=("conversation", str(conversation_id), None),
                        metadata={"draft_id": str(draft_id), "length": len(body.text)})  # the words themselves stay out of the log
        return out
    except HTTPException:
        async with tenant_session(sess.caller.tenant_id) as s:  # a refused message must not stay in the queue as a draft
            (await s.get(m.Draft, draft_id)).status = "skipped"
        raise


class Book(BaseModel):
    slot_code: str = Field(min_length=1, max_length=50)


@router.post("/conversations/{conversation_id}/booking")
async def book(conversation_id: UUID, body: Book, sess: Session = need("inbox.use")) -> dict[str, Any]:
    now = _now()
    async with tenant_session(sess.caller.tenant_id) as s:
        conv = await s.get(m.Conversation, conversation_id)
        if conv is None:
            raise HTTPException(404, "conversation not found")
        sandbox = await s.get(m.Sandbox, conv.sandbox_id)
        profile, _, ver = sandbox.profile_ref.partition("@")
        ctx = RunContext(run_id=uuid7(), tenant_id=conv.tenant_id, sandbox_id=sandbox.id, profile=profile, profile_version=int(ver or 1),
                         principal=StaffPrincipal(sess.caller.staff_ref or sess.caller.role), scope=Scope(conversation_id=conv.id))
        res = await default_registry(clock=lambda: now).execute(ctx, s, "book_slot", {"slot_code": body.slot_code},
                                                                allowlist=["book_slot"], effect_ceiling="internal")
    if res.status != "ok":
        code = res.violations[0].code.value if res.violations else res.status.upper()
        raise HTTPException(409, {"code": code})
    await audit_new(sess, "data", "booking.created", f"Đặt lịch cho khách (ca {body.slot_code})",
                    obj=("booking", res.data["booking_id"], None), metadata={"slot_code": body.slot_code, "conversation_id": str(conversation_id)})
    return {"booking_id": res.data["booking_id"]}


@router.post("/bookings/{booking_id}/cancel")
async def cancel(booking_id: UUID, sess: Session = need("inbox.use")) -> dict[str, str]:
    async with tenant_session(sess.caller.tenant_id) as s:
        if not await cancel_booking(s, booking_id, by=sess.actor, now=_now()):
            raise HTTPException(409, {"code": "NOT_CONFIRMED"})
        await audit(sess, s, "data", "booking.cancelled", "Huỷ lịch hẹn của khách", obj=("booking", str(booking_id), None))
    return {"status": "cancelled"}


class Outcome(BaseModel):
    status: Literal["booked", "won", "lost", "reopen"]


@router.post("/conversations/{conversation_id}/outcome")
async def outcome(conversation_id: UUID, body: Outcome, sess: Session = need("inbox.use")) -> dict[str, str]:
    async with tenant_session(sess.caller.tenant_id) as s:
        try:
            conv = await memory.record_outcome(s, conversation_id=conversation_id, status=body.status, source=sess.actor,
                                               evidence_msg_ids=[], now=_now())
        except memory.MemoryError as e:
            raise HTTPException(409, {"code": e.code}) from None
        await audit(sess, s, "data", "conversation.outcome", f"Ghi kết quả hội thoại: {body.status}",
                    obj=("conversation", str(conversation_id), None), metadata={"status": body.status})
    return {"state": conv.state}


@router.post("/facts/{fact_id}/{verb}")
async def fact_verb(fact_id: UUID, verb: Literal["confirm", "reject"], sess: Session = need("inbox.use")) -> dict[str, str]:
    fn = memory.confirm_fact if verb == "confirm" else memory.reject_fact
    async with tenant_session(sess.caller.tenant_id) as s:
        try:
            f = await fn(s, fact_id, staff_ref=sess.caller.staff_ref or sess.caller.role, now=_now())
        except memory.MemoryError as e:
            raise HTTPException(409, {"code": e.code}) from None
        await audit(sess, s, "data", f"fact.{verb}", "Xác nhận thông tin về khách" if verb == "confirm" else "Bác thông tin về khách",
                    obj=("fact", str(fact_id), None))
    return {"status": f.status}
