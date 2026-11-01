"""The five v0 tools (DESIGN §5.4). Scope is read from RunContext, never from args (A3).
None of them can reach a customer (A9)."""
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.context import RunContext
from cortex_leads.core.envelope import ErrorCode, ErrorInfo, ToolResult
from cortex_leads.core.timefmt import stamp, tenant_tz, wire, wire_date
from cortex_leads.core.vocabulary import SLOT_CATEGORY
from cortex_leads.db import models as m
from cortex_leads.domain.pack import load_pack
from cortex_leads.guard.validator import scan_dates, scan_times, slot_date_time, validate_draft
from cortex_leads.privacy.redact import redact
from cortex_leads.tools.empty import empty_note
from cortex_leads.tools.refs import resolve, unresolved
from cortex_leads.tools.registry import ToolArgs, ToolRegistry, ToolSpec

Clock = Callable[[], datetime]
_MASK = re.compile(r"\[[A-Z]+_\d+\]")  # redact.py placeholder: a masked name/phone must never reach the customer


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _no_scope() -> ToolResult:
    return ToolResult(status="error", error=ErrorInfo(code=ErrorCode.PERMISSION_DENIED),
                      note="Lượt chạy này không gắn với hội thoại nào.")


async def _conversation(ctx: RunContext, session: AsyncSession, *, lock: bool = False
                        ) -> tuple[m.Conversation, m.Contact] | None:
    if ctx.scope.conversation_id is None:
        return None
    q = (select(m.Conversation, m.Contact)
         .join(m.Contact, m.Contact.id == m.Conversation.contact_id)
         .where(m.Conversation.id == ctx.scope.conversation_id,
                m.Conversation.tenant_id == ctx.tenant_id,
                m.Conversation.sandbox_id == ctx.sandbox_id))
    if lock:
        q = q.with_for_update(of=m.Conversation)
    row = (await session.execute(q)).first()
    return (row[0], row[1]) if row else None


# --- read_messages ---------------------------------------------------------------------------
class ReadMessagesArgs(ToolArgs):
    last_n: int = Field(default=10, ge=1, le=30)


async def read_messages(ctx: RunContext, session: AsyncSession, a: ReadMessagesArgs) -> ToolResult:
    if ctx.scope.conversation_id is None:
        return _no_scope()
    found = await _conversation(ctx, session)
    if not found:
        return ToolResult(status="not_found", error=ErrorInfo(code=ErrorCode.NOT_FOUND))
    conv, contact = found
    rows = (await session.execute(
        select(m.Message).where(m.Message.conversation_id == conv.id,
                                m.Message.tenant_id == ctx.tenant_id)
        .order_by(m.Message.occurred_at.desc()).limit(a.last_n))).scalars().all()
    names = [contact.display_name] if contact.display_name else []
    zone = await tenant_tz(session, ctx.tenant_id)  # a model reads the business's local time, never UTC
    msgs = [{"id": str(r.id), "role": r.sender_role, "at": stamp(r.occurred_at, zone),
             "text": redact(r.text, names).text} for r in reversed(rows)]
    return ToolResult(status="ok", data={"messages": msgs},
                      note=None if msgs else empty_note("Hội thoại chưa có tin nhắn"))


# --- read_contact ----------------------------------------------------------------------------
class NoArgs(ToolArgs):
    pass


async def read_contact(ctx: RunContext, session: AsyncSession, a: NoArgs) -> ToolResult:
    if ctx.scope.conversation_id is None:
        return _no_scope()
    found = await _conversation(ctx, session)
    if not found:
        return ToolResult(status="not_found", error=ErrorInfo(code=ErrorCode.NOT_FOUND))
    conv, contact = found
    return ToolResult(status="ok", data={  # no name / phone: the model does not need them (N2)
        "opted_out": contact.opted_out, "decision_maker": contact.decision_maker,
        "channel_kind": conv.channel_kind, "intent": conv.intent, "touches": conv.touches,
        "state": conv.state, "owner_staff_ref": conv.owner_staff_ref,
        "offchannel_contact": conv.offchannel_contact,
        "promised_date": wire_date(conv.promised_date)})


# --- lookup_catalog / list_dropped_leads / draft_followup (need a clock) ---------------------
class LookupCatalogArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=100)


class DroppedLeadsArgs(ToolArgs):
    silent_hours: int = Field(default=24, ge=1, le=720)
    limit: int = Field(default=20, ge=1, le=20)


class Claim(ToolArgs):
    value: int | float | str
    source_id: str = Field(min_length=1)


class DraftArgs(ToolArgs):
    text: str = Field(min_length=1, max_length=2000)
    reason_code: str
    has_new_info: bool
    claims: list[Claim] = Field(default_factory=list, max_length=10)
    # Supplied by the runner from skill limits, not by the model (the model never sees this tool).
    max_touches: int = Field(default=2, ge=1, le=10)
    never_say: list[str] = Field(default_factory=list, max_length=50)
    route: Literal["channel", "offchannel"] = "channel"  # offchannel: window closed, staff phones (R39)


def _brief(i: m.CatalogItem) -> dict[str, Any]:
    return {"id": str(i.id), "code": i.code, "name": i.name, "category": i.category,
            "price": float(i.price) if i.price is not None else None, "unit": i.unit,
            "attrs": i.attrs, "valid_until": wire(i.valid_until)}


def _make_lookup_catalog(clock: Clock):
    async def lookup_catalog(ctx: RunContext, session: AsyncSession, a: LookupCatalogArgs
                             ) -> ToolResult:
        now = clock()
        q = select(m.CatalogItem).where(
            m.CatalogItem.tenant_id == ctx.tenant_id, m.CatalogItem.active.is_(True),
            or_(m.CatalogItem.valid_until.is_(None), m.CatalogItem.valid_until > now))
        if a.category:
            q = q.where(m.CatalogItem.category == a.category)
        items = list((await session.execute(q.order_by(m.CatalogItem.code))).scalars())
        res = resolve(items, a.query, keys=lambda i: [i.code, i.name])
        if res.status == "match":
            return ToolResult(status="ok", data={"items": [_brief(res.match)]})
        return unresolved(res, "mục catalog", lambda i: {"code": i.code, "name": i.name})

    return lookup_catalog


# --- study_plan ------------------------------------------------------------------------------
class StudyPlanArgs(ToolArgs):
    from_band: float = Field(ge=0, le=9, description="Điểm IELTS hiện tại (mất gốc/chưa thi: 3.5)")
    to_band: float = Field(ge=0, le=9, description="Điểm IELTS mục tiêu")
    months: int = Field(ge=1, le=24, description="Số tháng khách còn để chuẩn bị")


async def study_plan(ctx: RunContext, session: AsyncSession, a: StudyPlanArgs) -> ToolResult:
    """Picks the row of catalog `TT-THOIGIAN` for this gap and time, so the model never does the sum
    itself. `hours_per_day` is a catalog value: cite it as a claim with source_id TT-THOIGIAN."""
    row = (await session.execute(select(m.CatalogItem).where(
        m.CatalogItem.tenant_id == ctx.tenant_id, m.CatalogItem.code == "TT-THOIGIAN",
        m.CatalogItem.active.is_(True)))).scalar_one_or_none()
    if row is None:
        return ToolResult(status="not_found", error=ErrorInfo(code=ErrorCode.NOT_FOUND))
    gap = min(max(-(-(a.to_band - a.from_band) * 2 // 1) / 2, 0.5), 3.0)  # up to the next half band
    rows = {}
    for months in (3, 6, 9, 12):
        key = f"tang_{str(gap).replace('.', '_')}_band_trong_{months}_thang_tu_hoc_gio_moi_ngay"
        if key in row.attrs:
            rows[months] = row.attrs[key]
    if not rows:
        return ToolResult(status="not_found", error=ErrorInfo(code=ErrorCode.NOT_FOUND))
    cap = row.attrs.get("gio_tu_hoc_toi_da_moi_ngay", 3)
    near = min(rows, key=lambda x: abs(x - a.months))
    ok = [x for x in sorted(rows) if rows[x] <= cap]
    return ToolResult(status="ok", data={
        "source_id": "TT-THOIGIAN", "gap_band": gap, "months": near, "hours_per_day": rows[near],
        "max_hours_per_day": cap, "within_limit": rows[near] <= cap,
        "months_that_fit": ok[0] if ok else None, "hours_per_day_there": rows[ok[0]] if ok else None})


async def dropped_leads(session: AsyncSession, tenant_id: UUID, sandbox_id: UUID, now: datetime, *,
                        silent_hours: int = 24, limit: int = 20) -> list[m.Conversation]:
    """Customers who wrote and were never answered, silent for `silent_hours`+: the 0-token rule behind
    `list_dropped_leads` and the morning list (WP19)."""
    c = m.Conversation
    return list((await session.execute(
        select(c).where(
            c.tenant_id == tenant_id, c.sandbox_id == sandbox_id, c.state == "open",
            c.offchannel_contact.is_not(True),
            c.last_customer_at.is_not(None), c.last_customer_at <= now - timedelta(hours=silent_hours),
            or_(c.last_staff_at.is_(None), c.last_staff_at < c.last_customer_at))
        .order_by(c.last_customer_at.asc()).limit(limit))).scalars().all())


def _make_list_dropped_leads(clock: Clock):
    async def list_dropped_leads(ctx: RunContext, session: AsyncSession, a: DroppedLeadsArgs
                                 ) -> ToolResult:
        now = clock()
        rows = await dropped_leads(session, ctx.tenant_id, ctx.sandbox_id, now,
                                   silent_hours=a.silent_hours, limit=a.limit)
        leads = [{"conversation_id": str(r.id), "intent": r.intent, "touches": r.touches,
                  "owner_staff_ref": r.owner_staff_ref,
                  "silent_hours": int((now - r.last_customer_at).total_seconds() // 3600)}
                 for r in rows]
        return ToolResult(status="ok", data={"leads": leads},
                          note=None if leads else empty_note("Không có lead nào đang bị bỏ rơi"))

    return list_dropped_leads


def _flat(values):
    for v in values:
        yield from (v if isinstance(v, list | tuple) else [v])


def _checkable(v: Any) -> bool:  # a number, or a text holding a date or a clock time: what the validator can verify
    return (isinstance(v, int | float) and not isinstance(v, bool)) or (
        isinstance(v, str) and bool(scan_dates(v)[0] or scan_times(scan_dates(v)[1])[0]))


def _make_draft_followup(clock: Clock):
    async def draft_followup(ctx: RunContext, session: AsyncSession, a: DraftArgs) -> ToolResult:
        if ctx.scope.conversation_id is None:
            return _no_scope()
        found = await _conversation(ctx, session, lock=True)  # lock: touches is a counter
        if not found:
            return ToolResult(status="not_found", error=ErrorInfo(code=ErrorCode.NOT_FOUND))
        conv, contact = found
        a = a.model_copy(update={"text": _MASK.sub("mình", a.text)})
        sandbox = await session.get(m.Sandbox, ctx.sandbox_id)
        if sandbox is None or a.reason_code not in load_pack(sandbox).reason_codes:  # DESIGN A6
            return ToolResult(
                status="error", next_step="Sửa các trường lỗi rồi gọi lại.",
                error=ErrorInfo(code=ErrorCode.INVALID_ARGS, retryable=True, fields=["reason_code"]))
        sources = [c.source_id for c in a.claims]
        ids = []
        for s in sources:
            try:
                ids.append(UUID(s))
            except ValueError:
                pass
        rows = list((await session.execute(select(m.CatalogItem).where(
            m.CatalogItem.tenant_id == ctx.tenant_id,
            or_(m.CatalogItem.code.in_(sources), m.CatalogItem.id.in_(ids))))).scalars())
        claims = [c.model_dump() for c in a.claims]
        folded = a.text.casefold()  # naming a course ("khoá IELTS 3 tháng") cites it, like a claim
        rows += [r for r in (await session.execute(select(m.CatalogItem).where(
            m.CatalogItem.tenant_id == ctx.tenant_id, m.CatalogItem.active.is_(True)))).scalars()
            if r not in rows and r.name.split("(")[0].strip().casefold() in folded]
        # Citing a row vouches for that row's own numbers (models forget one claim of three); any
        # number in the text that is not on a cited row is still UNVERIFIED (A7, N2).
        tz = await tenant_tz(session, ctx.tenant_id)

        def vouched(r: m.CatalogItem) -> list[Any]:  # a slot vouches for its real start, not for text typed beside it
            if r.category == SLOT_CATEGORY and r.valid_until:
                d, t = slot_date_time(r, tz)
                return [*d, *t, *[v for k, v in (r.attrs or {}).items() if k not in ("ngay", "gio")]]
            return list(_flat((r.attrs or {}).values()))

        claims += [{"value": v, "source_id": r.code} for r in rows if r.active
                   for v in [r.price and float(r.price), *vouched(r)] if _checkable(v)]
        violations = validate_draft(  # DESIGN A7: the validator lives inside the write tool
            a.text, claims, rows, never_say=a.never_say, touches=conv.touches,
            max_touches=a.max_touches, opted_out=contact.opted_out or conv.state == "opted_out",
            has_new_info=a.has_new_info, now=clock(), tz=tz)
        run_exists = (await session.execute(
            select(m.TriggerRun.id).where(m.TriggerRun.id == ctx.run_id))).scalar()
        draft = m.Draft(
            tenant_id=ctx.tenant_id, sandbox_id=ctx.sandbox_id, conversation_id=conv.id,
            run_id=ctx.run_id if run_exists else None, text=a.text, claims=claims,
            reason_code=a.reason_code, route=a.route, status="blocked" if violations else "proposed")
        session.add(draft)
        if violations:
            await session.flush()
            return ToolResult(status="blocked", violations=violations,
                              data={"draft_id": str(draft.id)})
        await session.flush()  # touches are counted when the message goes out, not here (R36)
        return ToolResult(status="proposed", data={"draft_id": str(draft.id)},
                          next_step="Nháp đã chuyển cho nhân viên duyệt.")

    return draft_followup


def register_v0(reg: ToolRegistry, clock: Clock | None = None) -> None:
    clk = clock or _utcnow
    for name, desc, model, effect, handler in [
        ("read_messages", "Đọc các tin nhắn gần nhất của hội thoại đang xử lý, đã che thông tin cá nhân.",
         ReadMessagesArgs, "read", read_messages),
        ("read_contact", "Đọc hồ sơ khách của hội thoại đang xử lý (không gồm tên hay số điện thoại).",
         NoArgs, "read", read_contact),
        ("lookup_catalog", "Tra mục catalog đang bán theo mã hoặc tên. Chỉ báo giá lấy từ kết quả này.",
         LookupCatalogArgs, "read", _make_lookup_catalog(clk)),
        ("list_dropped_leads", "Liệt kê hội thoại khách nhắn mà chưa ai trả lời quá số giờ cho trước.",
         DroppedLeadsArgs, "read", _make_list_dropped_leads(clk)),
        ("study_plan", "Tính lộ trình IELTS: giờ tự học mỗi ngày để đi từ điểm hiện tại tới mục tiêu trong số tháng "
         "khách có. Chỉ nói số lấy từ kết quả, khai claim với source_id TT-THOIGIAN.",
         StudyPlanArgs, "read", study_plan),
        ("draft_followup", "Lưu nháp tin nhắn hỏi lại khách để nhân viên duyệt. Không bao giờ gửi cho khách.",
         DraftArgs, "internal", _make_draft_followup(clk)),
    ]:
        reg.register(ToolSpec(name, desc, model, effect, "v0", handler))
