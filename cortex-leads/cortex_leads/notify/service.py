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
PER_ROW = {"task", "digest", "proposal", "lesson", "grading"}  # one message each, built from the row's own numbers


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
        owed = sum(len(payload.get(k, [])) for k in ("due", "quiet", "capped"))
        text = (f"📋 Việc sáng nay: {len(payload.get('leads', []))} khách chưa được trả lời, "
                + (f"{owed} khách tới hạn hẹn hoặc im sau khi đã trả lời, " if owed else "")
                + f"{payload.get('bookings_today', 0)} lịch học thử hôm nay.")
        return text + (f"\nMở: {base}/staff" if base else "")
    if kind == "grading":  # the team channel only (see the worker): it names the student and the suggested mark, as the teacher asked
        return render_grading(payload, base_url)
    if kind == "lesson":  # the one push that carries words: the teacher's own lesson, to the team channel only
        from cortex_leads.lessons.recap import render_recap

        return render_recap(payload["name"], payload, payload.get("video_url"), payload.get("video_label", "Video buổi học"), payload.get("class"))
    if kind == "proposal":
        from cortex_leads.supervisor.signals import LABELS

        skill = (payload.get("target") or {}).get("skill")
        text = f"⚠️ AI tổng đề xuất xem lại {'kỹ năng ' + skill if skill else 'hệ thống'}: {LABELS.get(payload['signal'], payload['signal'])}."
        return text + (f"\nMở: {base}/staff/proposals" if base else "")
    this = payload.get("this", {})
    monthly = payload.get("kind") == "monthly"
    text = (f"📊 Báo cáo {'tháng' if monthly else 'tuần'}: {this.get('new_conversations', 0)} khách mới, {this.get('bookings', 0)} lịch học thử, "
            f"{this.get('ai_sent', 0)} tin AI tự gửi, {payload.get('dropped_now', 0)} khách đang bị bỏ rơi.")
    return text + (f"\nChi tiết: {base}/staff/digest" if base else "")


def _num(x: float) -> str:
    return f"{x:g}"


def render_grading(p: dict, base_url: str | None) -> str:
    """One submission, in words that say what has and has not happened: the AI SUGGESTED a mark, nobody has approved it, nothing is in
    Classroom yet and the student has seen nothing. Where to open it is a link, never left for the reader to look up."""
    lines = [f"Lớp: {p['course']}", "", "Bài nộp mới đã được AI đề xuất điểm. CHƯA phải điểm chính thức: giáo viên chưa duyệt, chưa ghi lên Classroom, học sinh chưa thấy điểm.", "",
             f"Học sinh: {p['student']}", f"Bài tập: {p['work_title']}"]
    if p.get("total") is not None:
        parts = " · ".join(f"{c['label']} {_num(c['score'])}/{_num(c['points'])}" for c in p["criteria"])
        lines.append(f"Đề xuất của AI: {_num(p['total'])}/{_num(p['max_points'])} ({parts})")
    from cortex_leads.grader.extract import NOTES

    kinds = {"audio": "bản ghi âm, máy chép lại thành chữ nên có thể sai: hãy nghe lại trước khi duyệt",
             "video": "video (chỉ lấy tiếng, hình không được đọc): hãy xem lại trước khi duyệt",
             "pdf": "PDF (bảng và hình có thể bị mất)", "docx": "Word"}
    read_from = [kinds[k] for k in p.get("kinds", []) if k in kinds]
    if read_from:
        lines.append("Bài nộp là: " + "; ".join(read_from))
    problems = [x for x in p.get("problems", []) if x not in NOTES.values()]  # how it was read is said above
    for problem in problems[:2]:
        lines.append(f"Lưu ý: {problem if len(problem) <= 220 else problem[:220].rsplit(' ', 1)[0] + '…'}")
    if len(problems) > 2:
        lines.append(f"(còn {len(problems) - 2} lưu ý khác trong trang duyệt)")
    lines.append("Bài này không do ứng dụng tạo nên chỉ là gợi ý; điểm phải nhập tay trên Classroom." if not p.get("ours")
                 else "Sau khi duyệt, có thể lưu điểm nháp hoặc ghi điểm lên Classroom.")
    base = base_url.rstrip("/") if base_url else None
    if base:
        lines += ["", f"Xem và duyệt điểm: {base}/app/grading/{p['id']}"]
    if p.get("classroom_link"):
        lines.append(f"Bài nộp trên Classroom: {p['classroom_link']}")
    return "\n".join(lines)
