"""AI tổng (WP27): the owner's open proposals, and a chat that answers from NUMBERS only.

The chat is the supervisor of DESIGN §5.6 with a keyboard: it is given counts and metadata (the same views `cl_supervisor`
reads) and nothing a customer wrote, no name, no phone, no draft. So it can answer "which skill is blocked most?" and cannot
answer "what did customer A say?"; asked that, it says so and points at the inbox. Every number in its answer must be one it
was given or one the owner typed; an answer with a number of its own is replaced by an honest "I can't say that from the data"."""
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from cortex_leads.console.auth import Session, need
from cortex_leads.console.sandboxes import PURPOSE_LABELS
from cortex_leads.console.trail import audit_new
from cortex_leads.core.context import RunContext, Scope, SystemPrincipal
from cortex_leads.core.errors import CortexError
from cortex_leads.core.ids import uuid7
from cortex_leads.cron.jobs import week_stats
from cortex_leads.db import models as m
from cortex_leads.db.session import supervisor_session, tenant_session
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.llm.shape import parse_json_object, response_shape
from cortex_leads.llm.types import LLMError, ShapeError
from cortex_leads.sandbox.policy import check_budget
from cortex_leads.skills.profile import load_profile
from cortex_leads.staff_ui.routes import ACTION_TEXT, EVIDENCE_TEXT
from cortex_leads.supervisor.narrative import _NUM, _numbers
from cortex_leads.supervisor.proposals import decide
from cortex_leads.supervisor.signals import LABELS
from cortex_leads.tools.v0 import dropped_leads

router = APIRouter()
SKILL = "tro-chuyen-ai-tong"
WINDOW = timedelta(days=7)
MAX_TURNS, MAX_CHARS = 8, 600
FALLBACK = "Mình chưa trả lời chắc chắn được câu này từ số liệu hiện có. Bạn thử hỏi cụ thể hơn về kỹ năng, lượt chạy hoặc số khách."
SYSTEM = (
    "Bạn là AI tổng của một trung tâm đào tạo: bạn giúp chủ hiểu số liệu vận hành của AI chăm sóc khách. Bạn CHỈ có các con số và mã "
    "trạng thái trong dữ liệu được đưa. Bạn không đọc nội dung tin nhắn, không biết tên hay số điện thoại khách, không thấy nháp. "
    "Nếu chủ hỏi khách cụ thể nói gì hoặc muốn xem nội dung, đặt refused=true, nói rõ bạn không đọc được nội dung và bảo chủ mở Hộp thư. "
    "Chỉ dùng đúng các con số có trong dữ liệu hoặc do chủ viết; không tự tính số mới, không bịa nguyên nhân; thiếu dữ liệu thì nói thiếu. "
    "Chỉ đề xuất, không tự đổi gì: việc đổi nằm ở mục Đề xuất. Trả lời tiếng Việt, ngắn gọn, tối đa 4 câu.")
SHAPE = {"reply": "<câu trả lời tiếng Việt, tối đa 4 câu>", "refused": False}


def get_gateway() -> LLMGateway:
    from cortex_leads.llm.providers import OpenAICompatibleProvider

    try:
        return LLMGateway(OpenAICompatibleProvider())
    except Exception as e:  # not configured on this machine
        raise HTTPException(503, {"code": "LLM_UNAVAILABLE"}) from e


@router.get("/proposals")
async def proposals(sess: Session = need("assistant.use")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        rows = (await s.execute(select(m.Proposal, m.Sandbox.title, m.Sandbox.name, m.Sandbox.purpose).join(m.Sandbox, m.Sandbox.id == m.Proposal.sandbox_id)
                                .where(m.Proposal.status == "pending").order_by(m.Proposal.created_at))).all()
    return {"items": [{
        "id": str(p.id), "kind": p.kind, "signal": LABELS.get(p.signal, p.signal), "sandbox": title or PURPOSE_LABELS.get(purpose, name),
        "skill": (p.target or {}).get("skill"), "change": (p.target or {}).get("change"), "action": ACTION_TEXT[p.kind],
        "evidence": [f"{EVIDENCE_TEXT.get(k, k)}: {v}" for k, v in p.evidence.items()],
        "danger": p.kind == "pause_sandbox"} for p, title, name, purpose in rows]}


@router.post("/proposals/{proposal_id}/{verb}")
async def proposal_verb(proposal_id: UUID, verb: Literal["accept", "dismiss"], sess: Session = need("assistant.use")) -> dict[str, str]:
    try:
        async with tenant_session(sess.caller.tenant_id) as s:
            status = await decide(s, proposal_id, accept=verb == "accept", by=sess.actor, now=datetime.now(UTC))
    except CortexError:
        raise HTTPException(404, "proposal not found") from None
    await audit_new(sess, "config", f"proposal.{verb}", "Nhận đề xuất của AI tổng" if verb == "accept" else "Bỏ đề xuất của AI tổng",
                    obj=("proposal", str(proposal_id), None), metadata={"status": status})
    return {"status": status}


async def snapshot(tenant_id: UUID, now: datetime) -> dict[str, Any]:
    """Counts and enum codes for the last 7 days. Built from the supervisor views (no text columns exist for that role)
    plus plain counts; nothing here can hold a customer's words."""
    since, p = now - WINDOW, {"since": now - WINDOW}
    async with supervisor_session(tenant_id) as s:
        per = (await s.execute(text(
            "select skill_name, skill_version, count(*), count(*) filter (where cardinality(blocked_codes) > 0), "
            "count(*) filter (where status = 'error'), count(*) filter (where staff_outcome is not null), "
            "count(*) filter (where staff_outcome = 'skipped') from supervisor_run_view where started_at >= :since "
            "group by 1, 2 order by 3 desc limit 12"), p)).all()
        tops = dict((await s.execute(text(
            "select skill_name, (array_agg(c order by n desc))[1] from (select skill_name, c, count(*) n from supervisor_run_view, "
            "unnest(blocked_codes) c where started_at >= :since group by 1, 2) t group by 1"), p)).all())
        out = (await s.execute(text("select count(*), count(*) filter (where status in ('refused', 'error')) from supervisor_outbox_view "
                                    "where created_at >= :since"), p)).one()
    async with tenant_session(tenant_id) as s:
        week = await week_stats(s, tenant_id, since, now)
        dropped = 0
        for sb in (await s.execute(select(m.Sandbox).where(m.Sandbox.purpose == "customer_care"))).scalars():
            dropped += len(await dropped_leads(s, tenant_id, sb.id, now, limit=1000))
        pending = [LABELS.get(x.signal, x.signal) for x in (await s.execute(select(m.Proposal).where(m.Proposal.status == "pending"))).scalars()]
    pct = lambda a, b: round(100 * a / b) if b else 0
    decided, skipped = sum(r[5] for r in per), sum(r[6] for r in per)
    return {"so_ngay_trong_so_lieu": WINDOW.days, "7_ngay_qua": week,
            "theo_ky_nang": [{"ky_nang": r[0], "ban": r[1], "luot_chay": r[2], "bi_chan": r[3], "ti_le_chan_pct": pct(r[3], r[2]),
                              "loi": r[4], "ma_chan_nhieu_nhat": tops.get(r[0])} for r in per],
            "nhan_vien_xu_ly_nhap": {"da_xu_ly": decided, "bo": skipped, "ti_le_bo_pct": pct(skipped, decided)},
            "gui_tin": {"tong": out[0], "that_bai": out[1]}, "khach_dang_bi_bo_roi": dropped, "de_xuat_dang_cho": pending}


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CHARS)


class Chat(BaseModel):
    messages: list[Turn] = Field(min_length=1, max_length=MAX_TURNS)


@router.post("/assistant/chat")
async def chat(body: Chat, sess: Session = need("assistant.use"), gateway: LLMGateway = Depends(get_gateway)) -> dict[str, Any]:
    if body.messages[-1].role != "user":
        raise HTTPException(422, "the last message must be the owner's question")
    now, tid = datetime.now(UTC), sess.caller.tenant_id
    async with tenant_session(tid) as s:
        sb = (await s.execute(select(m.Sandbox).where(m.Sandbox.purpose == "owner_digest").order_by(m.Sandbox.created_at).limit(1))).scalar_one_or_none()
        if sb is None:
            raise HTTPException(409, {"code": "NO_DIGEST_SANDBOX"})  # AI tổng lives in the "Báo cáo cho chủ" sandbox, with its own budget
        if v := (await check_budget(s, sb, "tokens", now)) or (await check_budget(s, sb, "runs", now)):
            raise HTTPException(429, {"code": v.code.value})
        profile = load_profile(sb.profile_ref)
        run = m.TriggerRun(id=uuid7(), tenant_id=tid, sandbox_id=sb.id, skill_name=SKILL, skill_version=1, profile=profile.id,
                           profile_version=profile.version, event_type="console.chat", status="ok", blocked_codes=[], tokens_in=0,
                           tokens_out=0, started_at=now)
        s.add(run)
        sb_id, run_id = sb.id, run.id
    data = await snapshot(tid, now)
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Số liệu hiện có (7 ngày gần nhất):\n" + json.dumps(data, ensure_ascii=False)}]
    msgs += [{"role": t.role, "content": t.content} for t in body.messages[:-1]]
    msgs.append({"role": "user", "content": body.messages[-1].content + "\n\n" + response_shape(SHAPE)})
    ctx = RunContext(run_id=run_id, tenant_id=tid, sandbox_id=sb_id, profile=profile.id, profile_version=profile.version,
                     principal=SystemPrincipal(job="console_chat"), scope=Scope())
    reply, refused, status, codes, res = FALLBACK, False, "ok", [], None
    try:
        res = await gateway.complete(ctx, msgs, timeout_s=profile.timeout_s)
        out = parse_json_object(res.content)
        text_ = str(out.get("reply", "")).strip()
        owner_said = " ".join(t.content for t in body.messages if t.role == "user")
        allowed = _numbers(data) | set(_NUM.findall(owner_said))
        if 10 <= len(text_) <= 800 and "http" not in text_.lower() and all(n.replace(",", ".") in allowed or n in allowed for n in _NUM.findall(text_)):
            reply, refused = text_, bool(out.get("refused"))
        else:
            status, codes = "blocked", ["UNVERIFIED_CLAIM"]
    except ShapeError:
        status = "error"
    except LLMError:
        status = "error"
        reply = ""
    async with tenant_session(tid) as s:
        r = await s.get(m.TriggerRun, run_id)
        r.status, r.blocked_codes, r.finished_at = status, codes, now
        if res is not None:
            r.tokens_in, r.tokens_out, r.model = res.tokens_in, res.tokens_out, res.model
    if not reply:
        raise HTTPException(503, {"code": "LLM_UNAVAILABLE"})
    await audit_new(sess, "data", "assistant.asked", "Hỏi AI tổng", metadata={"run_id": str(run_id), "status": status})
    return {"reply": reply, "refused": refused, "verified": status == "ok"}
