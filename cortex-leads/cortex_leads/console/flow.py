"""What goes into a sandbox and where its output goes, for the sandboxes that are not conversations with customers (WP32).
The page of a customer-care sandbox shows channels and a catalogue; a lesson sandbox has a folder of recordings in and a team
channel out, and the page has to say that in the same words wherever it appears. Never returns an address or a token:
a webhook is shown as its host only."""
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m

SOURCE_LABELS = {"drive": "Thư mục Google Drive", "local": "Thư mục trên máy chủ", "upload": "Tải lên trực tiếp", "classroom": "Khoá học Google Classroom"}
PUSH_LABELS = {"mezon": "Kênh Mezon", "telegram": "Telegram"}
WAITING = ("queued", "working")


def _where(kind: str, ref: str) -> str:
    return f"…{ref[-6:]}" if kind == "drive" else "trong trang Buổi học" if kind == "upload" else Path(ref).name


async def feeds_and_pushes(s: AsyncSession, sb: m.Sandbox) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """([what the sandbox reads, with what became of each piece of work], [places its count or recap is posted]); both empty for
    kinds that talk to customers or only report."""
    if sb.purpose == "classroom_grader":
        return await _classroom_feeds(s, sb), await _pushes(s, sb)
    if sb.purpose != "lesson_recap":
        return [], []
    counts: dict[tuple[Any, str], int] = {(sid, st): n for sid, st, n in (await s.execute(
        select(m.Lesson.class_id, m.Lesson.status, func.count()).where(m.Lesson.sandbox_id == sb.id)
        .group_by(m.Lesson.class_id, m.Lesson.status))).all()}
    feeds = []
    for src in (await s.execute(select(m.Class).where(m.Class.recap_sandbox_id == sb.id).order_by(m.Class.created_at))).scalars():
        feeds.append({"id": str(src.id), "kind": src.source_kind, "label": SOURCE_LABELS.get(src.source_kind or "", src.source_kind), "where": _where(src.source_kind or "", src.source_ref or ""),
                      "active": src.active, "since": wire(src.created_at), "noun": "thư mục bản ghi", "unit": "buổi",
                      "lessons": {"done": counts.get((src.id, "done"), 0), "failed": counts.get((src.id, "failed"), 0),
                                  "waiting": sum(counts.get((src.id, st), 0) for st in WAITING)}})
    return feeds, await _pushes(s, sb)


async def _pushes(s: AsyncSession, sb: m.Sandbox) -> list[dict[str, Any]]:
    """The channels this sandbox posts to: the ones bound to it if it has any, else the business's general ones (the rule of `notify.worker.route`)."""
    from cortex_leads.notify.worker import route

    pushes = []
    mezon = list((await s.execute(select(m.NotifyTarget).where(m.NotifyTarget.kind == "mezon").order_by(m.NotifyTarget.created_at))).scalars())
    for t in route(mezon, sb.id):
        pushes.append({"id": str(t.id), "kind": t.kind, "label": t.label or PUSH_LABELS[t.kind], "where": urlsplit(t.address).hostname or "",
                       "active": t.active})
    return pushes


async def _classroom_feeds(s: AsyncSession, sb: m.Sandbox) -> list[dict[str, Any]]:
    counts: dict[tuple[Any, str], int] = {(sid, st): n for sid, st, n in (await s.execute(
        select(m.Assignment.class_id, m.GradeItem.status, func.count()).join(m.Assignment, m.Assignment.id == m.GradeItem.assignment_id)
        .where(m.GradeItem.sandbox_id == sb.id).group_by(m.Assignment.class_id, m.GradeItem.status))).all()}
    feeds = []
    for src in (await s.execute(select(m.Class).where(m.Class.grader_sandbox_id == sb.id).order_by(m.Class.created_at))).scalars():
        feeds.append({"id": str(src.id), "kind": "classroom", "label": SOURCE_LABELS["classroom"], "where": src.course_name or src.name,
                      "active": src.active, "since": wire(src.created_at), "noun": "khoá học Classroom", "unit": "bài nộp",
                      "lessons": {"done": counts.get((src.id, "approved"), 0) + counts.get((src.id, "rejected"), 0),
                                  "failed": counts.get((src.id, "failed"), 0),
                                  "waiting": sum(counts.get((src.id, st), 0) for st in ("pending", "queued", "working", "proposed"))}})
    return feeds


def flow_line(feeds: list[dict[str, Any]], pushes: list[dict[str, Any]]) -> str | None:
    """One line for the sandbox list: what comes in, what goes out."""
    if not feeds and not pushes:
        return None
    on_in, on_out = [f for f in feeds if f["active"]], [p for p in pushes if p["active"]]
    noun = (feeds or [{"noun": "nguồn"}])[0]["noun"]
    inn = f"{len(on_in)} {noun}" if on_in else f"Chưa gắn {noun}"
    out = f"{len(on_out)} kênh Mezon" if on_out else "chưa có nơi gửi"
    return f"{inn} → {out}"
