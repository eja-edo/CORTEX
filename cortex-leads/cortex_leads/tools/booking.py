"""Trial-class booking (WP18). A slot is a catalog row (`category=lich_hoc_thu`): `valid_until` is the
start, `attrs.suc_chua` the seats, `attrs.ngay` / `attrs.gio` what the customer reads. Seats are counted
from `booking` under a lock on the slot row, so two customers cannot take the last one (A3: the
conversation comes from RunContext). `book_slot` is internal: the runner calls it, the model only asks."""
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.context import RunContext
from cortex_leads.core.envelope import BlockedCode, ErrorCode, ErrorInfo, ToolResult, Violation
from cortex_leads.db import models as m
from cortex_leads.memory import service as memory
from cortex_leads.notify import service as notify
from cortex_leads.outbound.annotate import annotate
from cortex_leads.tools.registry import ToolArgs, ToolRegistry, ToolSpec
from cortex_leads.tools.v0 import NoArgs, _conversation, _no_scope

SLOT_CATEGORY = "lich_hoc_thu"
Clock = Callable[[], datetime]


class BookArgs(ToolArgs):
    slot_code: str = Field(min_length=1, max_length=50)


def _cap(item: m.CatalogItem) -> int:
    v = (item.attrs or {}).get("suc_chua")
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0  # unknown = no seats


async def _taken(session: AsyncSession, tenant_id: UUID, code: str, *, skip_conversation: UUID | None = None) -> int:
    q = select(func.count()).select_from(m.Booking).where(
        m.Booking.tenant_id == tenant_id, m.Booking.slot_code == code, m.Booking.status == "confirmed")
    if skip_conversation:
        q = q.where(m.Booking.conversation_id != skip_conversation)
    return (await session.execute(q)).scalar_one()


def _slot_query(tenant_id: UUID, now: datetime):
    return select(m.CatalogItem).where(
        m.CatalogItem.tenant_id == tenant_id, m.CatalogItem.active.is_(True),
        m.CatalogItem.category == SLOT_CATEGORY, m.CatalogItem.valid_until > now)


def _view(item: m.CatalogItem, left: int) -> dict[str, Any]:
    a = item.attrs or {}
    return {"code": item.code, "name": item.name, "ngay": a.get("ngay"), "gio": a.get("gio"),
            "con_cho": left, "source_id": item.code}


def _make_list_open_slots(clock: Clock):
    async def list_open_slots(ctx: RunContext, session: AsyncSession, a: NoArgs) -> ToolResult:
        rows = (await session.execute(_slot_query(ctx.tenant_id, clock()).order_by(
            m.CatalogItem.valid_until).limit(20))).scalars().all()
        out = []
        for r in rows:
            if (left := _cap(r) - await _taken(session, ctx.tenant_id, r.code)) > 0:
                out.append(_view(r, left))
        return ToolResult(status="ok", data={"slots": out[:8]}, note=None if out else
                          "Hiện không có lịch học thử nào còn chỗ. Báo khách bạn tư vấn sẽ xếp lịch, đừng hứa ngày.")

    return list_open_slots


def _make_book_slot(clock: Clock):
    async def book_slot(ctx: RunContext, session: AsyncSession, a: BookArgs) -> ToolResult:
        now = clock()
        if ctx.scope.conversation_id is None:
            return _no_scope()
        found = await _conversation(ctx, session, lock=True)  # also serialises one customer's double tap
        if not found:
            return ToolResult(status="not_found", error=ErrorInfo(code=ErrorCode.NOT_FOUND))
        conv, contact = found
        if conv.state != "open" or contact.opted_out:
            return ToolResult(status="blocked", violations=[Violation(code=BlockedCode.OPTED_OUT)])
        item = (await session.execute(_slot_query(ctx.tenant_id, now).where(
            m.CatalogItem.code == a.slot_code).with_for_update())).scalar_one_or_none()
        if item is None or not _cap(item):
            return ToolResult(status="blocked", violations=[Violation(code=BlockedCode.SLOT_GONE, span=a.slot_code)])
        mine = (await session.execute(select(m.Booking).where(
            m.Booking.conversation_id == conv.id, m.Booking.status == "confirmed"))).scalar_one_or_none()
        if mine and mine.slot_code == item.code:  # asked twice for the same seat
            return ToolResult(status="ok", data={"booking_id": str(mine.id), "slot": _view(item, 0), "unchanged": True})
        left = _cap(item) - await _taken(session, ctx.tenant_id, item.code)
        if left <= 0:
            return ToolResult(status="blocked", violations=[Violation(code=BlockedCode.SLOT_FULL, span=a.slot_code)])
        if mine:  # moving to another slot frees the first
            mine.status, mine.cancelled_at, mine.cancelled_by = "cancelled", now, ctx.actor
            await session.flush()
            await memory.release_appointment(session, conversation_id=conv.id, now=now)
        booking = m.Booking(
            tenant_id=ctx.tenant_id, sandbox_id=ctx.sandbox_id, conversation_id=conv.id,
            contact_id=contact.id, slot_code=item.code, starts_at=item.valid_until, actor=ctx.actor,
            run_id=ctx.run_id)
        session.add(booking)
        await session.flush()
        tz = ZoneInfo((await session.execute(select(m.Tenant.timezone).where(
            m.Tenant.id == ctx.tenant_id))).scalar_one())
        await memory.note_appointment(session, conversation_id=conv.id, now=now,
                                      on=item.valid_until.astimezone(tz).date())
        session.add(m.DecisionLog(tenant_id=ctx.tenant_id, run_id=None, conversation_id=conv.id,
                                  decision="booking_made", reason_code=None, at=now,
                                  detail={"booking_id": str(booking.id), "slot": item.code,
                                          "moved": bool(mine)}))
        await notify.enqueue(session, ctx.tenant_id, "booking", booking.id, now)
        await annotate(session, conv, "booking", booking.id, now)  # the platform's own tag/note, if the business set one
        return ToolResult(status="ok", data={"booking_id": str(booking.id), "slot": _view(item, left - 1)})

    return book_slot


async def cancel_booking(session: AsyncSession, booking_id: UUID, *, by: str, now: datetime) -> bool:
    """Staff (or the runner, when the reply that would have confirmed it was blocked). The seat returns to
    the slot and the promise the booking made goes away. False when it was not confirmed."""
    b = await session.get(m.Booking, booking_id, with_for_update=True)
    if b is None or b.status != "confirmed":
        return False
    await session.execute(update(m.Booking).where(m.Booking.id == b.id).values(
        status="cancelled", cancelled_at=now, cancelled_by=by))
    await memory.release_appointment(session, conversation_id=b.conversation_id, now=now)
    session.add(m.DecisionLog(tenant_id=b.tenant_id, conversation_id=b.conversation_id, at=now,
                              decision="booking_cancelled", detail={"booking_id": str(b.id), "by": by.split(":")[0]}))
    return True


def register_booking(reg: ToolRegistry, clock: Clock | None = None) -> None:
    clk = clock or (lambda: datetime.now(UTC))
    reg.register(ToolSpec(
        "list_open_slots", "Liệt kê các lịch học thử còn chỗ (mã, ngày, giờ, số chỗ). Chỉ nói ngày giờ lấy từ kết quả này.",
        NoArgs, "read", "v1", _make_list_open_slots(clk)))
    reg.register(ToolSpec(
        "book_slot", "Giữ một chỗ học thử cho khách của hội thoại này. Chỉ hệ thống gọi, sau khi khách đã chọn lịch.",
        BookArgs, "internal", "v1", _make_book_slot(clk)))
