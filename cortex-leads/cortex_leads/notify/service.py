"""Staff push notifications (WP17, R58). A push says *that* something needs a person and links to
/staff; it never carries a name, a phone number or a word the customer wrote (the message leaves
the system for a third party)."""
from datetime import datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m

TEXT = {
    "handoff": "🔔 {n} khách đang chờ nhân viên trả lời.",
    "booking": "📅 {n} lịch học thử mới.",
}
PER_ROW = {"task", "digest", "proposal"}  # one message each, built from the row's own numbers


async def enqueue(session: AsyncSession, tenant_id: UUID, kind: str, ref_id: UUID, now: datetime) -> None:
    """Idempotent per (kind, ref_id): a retried run never pushes twice."""
    await session.execute(insert(m.Notification).values(
        id=uuid7(), tenant_id=tenant_id, kind=kind, ref_id=ref_id, created_at=now)
        .on_conflict_do_nothing(constraint="uq_notification_tenant_id_kind_ref_id"))


def render(kind: str, count: int, base_url: str | None) -> str:
    link = f"\nMở: {base_url.rstrip('/')}/staff" if base_url else ""
    return TEXT[kind].format(n=count) + link


def render_row(kind: str, payload: dict, base_url: str | None) -> str:
    """Numbers only. `payload` is a staff_task / digest payload: ids are never printed."""
    base = base_url.rstrip("/") if base_url else None
    if kind == "task":
        text = (f"📋 Việc sáng nay: {len(payload.get('leads', []))} khách chưa được trả lời, "
                f"{payload.get('bookings_today', 0)} lịch học thử hôm nay.")
        return text + (f"\nMở: {base}/staff" if base else "")
    if kind == "proposal":
        from cortex_leads.supervisor.signals import LABELS

        skill = (payload.get("target") or {}).get("skill")
        text = f"⚠️ AI tổng đề xuất xem lại {'kỹ năng ' + skill if skill else 'hệ thống'}: {LABELS.get(payload['signal'], payload['signal'])}."
        return text + (f"\nMở: {base}/staff/proposals" if base else "")
    this = payload.get("this", {})
    text = (f"📊 Báo cáo tuần: {this.get('new_conversations', 0)} khách mới, {this.get('bookings', 0)} lịch học thử, "
            f"{this.get('ai_sent', 0)} tin AI tự gửi, {payload.get('dropped_now', 0)} khách đang bị bỏ rơi.")
    return text + (f"\nChi tiết: {base}/staff/digest" if base else "")
