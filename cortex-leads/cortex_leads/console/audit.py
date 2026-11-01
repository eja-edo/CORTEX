"""The activity log (DESIGN §5.14): the owner reads everything that happened in the business, staff read only their own
trail. Read-only: nothing here can change or remove a line."""
import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select

from cortex_leads.audit.service import verify
from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import audit
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

router = APIRouter()
PAGE_SIZES = (10, 20, 50, 100)
CATEGORIES = {"auth": "Đăng nhập", "access": "Truy cập bị từ chối", "view": "Xem", "data": "Dữ liệu", "config": "Cấu hình", "control": "Điều khiển AI"}
EXPORT_MAX = 5000


def _item(r: m.AuditEvent, *, detail: bool = False) -> dict[str, Any]:
    out = {"id": str(r.id), "seq": r.seq, "at": wire(r.at), "actor": r.actor, "role": r.actor_role, "category": r.category, "action": r.action,
           "result": r.result, "summary": r.summary, "object": {"type": r.object_type, "id": r.object_id, "label": r.object_label} if r.object_type else None,
           "ip": r.ip, "has_metadata": bool(r.metadata_)}
    if detail:
        out |= {"user_agent": r.user_agent, "request_id": r.request_id, "session_id": r.session_id, "metadata": r.metadata_, "hash": r.hash}
    return out


def _filters(sess: Session, *, start: datetime | None, end: datetime | None, actor: str | None, category: str | None, result: str | None,
             q: str | None) -> list[Any]:
    conds: list[Any] = [m.AuditEvent.tenant_id == sess.caller.tenant_id]
    if not sess.can("audit.all"):
        conds.append(m.AuditEvent.actor == sess.actor)  # staff see their own trail, nothing about colleagues
    elif actor:
        conds.append(m.AuditEvent.actor == actor)
    if start:
        conds.append(m.AuditEvent.at >= start)
    if end:
        conds.append(m.AuditEvent.at < end)
    if category:
        conds.append(m.AuditEvent.category == category)
    if result:
        conds.append(m.AuditEvent.result == result)
    if q:
        like = f"%{q.strip()[:80].replace('%', '').replace('_', '')}%"
        conds.append(or_(m.AuditEvent.summary.ilike(like), m.AuditEvent.object_label.ilike(like), m.AuditEvent.ip.ilike(like),
                         m.AuditEvent.action.ilike(like), m.AuditEvent.request_id.ilike(like)))
    return conds


def _day(sess: Session, d: str | None, plus: int = 0) -> datetime | None:
    if not d:
        return None
    try:
        day = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=sess.tz) + timedelta(days=plus)
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD") from None
    return day.astimezone(UTC)


@router.get("/audit")
async def list_events(
    sess: Session = need("audit.own"), page: int = Query(1, ge=1, le=100_000), page_size: int = Query(20), date_from: str | None = None,
    date_to: str | None = None, actor: str | None = Query(None, max_length=120), category: Literal[tuple(CATEGORIES)] | None = None,  # type: ignore[valid-type]
    result: Literal["success", "denied", "failed"] | None = None, q: str | None = Query(None, max_length=80),
) -> dict[str, Any]:
    if page_size not in PAGE_SIZES:
        raise HTTPException(422, f"page_size must be one of {PAGE_SIZES}")
    conds = _filters(sess, start=_day(sess, date_from), end=_day(sess, date_to, 1), actor=actor, category=category, result=result, q=q)
    async with tenant_session(sess.caller.tenant_id) as s:
        total = (await s.execute(select(func.count()).select_from(m.AuditEvent).where(*conds))).scalar_one()
        rows = (await s.execute(select(m.AuditEvent).where(*conds).order_by(m.AuditEvent.seq.desc())
                                .limit(page_size).offset((page - 1) * page_size))).scalars().all()
        actors = [a for (a,) in (await s.execute(select(m.AuditEvent.actor).where(m.AuditEvent.tenant_id == sess.caller.tenant_id)
                                                 .distinct().order_by(m.AuditEvent.actor))).all()] if sess.can("audit.all") else [sess.actor]
    pages = max(1, -(-total // page_size))
    return {"items": [_item(r) for r in rows], "total": total, "page": page, "page_size": page_size, "pages": pages,
            "page_sizes": list(PAGE_SIZES), "actors": actors, "categories": CATEGORIES}


@router.get("/audit/export")
async def export(sess: Session = need("audit.admin"), date_from: str | None = None, date_to: str | None = None, category: str | None = None,
                 result: str | None = None, q: str | None = Query(None, max_length=80)) -> Response:
    conds = _filters(sess, start=_day(sess, date_from), end=_day(sess, date_to, 1), actor=None, category=category, result=result, q=q)
    async with tenant_session(sess.caller.tenant_id) as s:
        rows = (await s.execute(select(m.AuditEvent).where(*conds).order_by(m.AuditEvent.seq.desc()).limit(EXPORT_MAX))).scalars().all()
        await audit(sess, s, "data", "audit.exported", f"Xuất nhật ký ra tệp ({len(rows)} dòng)", metadata={"rows": len(rows)})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["thời điểm (UTC)", "người thực hiện", "vai trò", "nhóm", "hành động", "kết quả", "tóm tắt", "đối tượng", "IP", "mã yêu cầu"])
    for r in rows:
        w.writerow([_safe(x) for x in (wire(r.at), r.actor, r.actor_role, r.category, r.action, r.result, r.summary, r.object_label or "", r.ip or "", r.request_id or "")])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="nhat-ky.csv"'})


def _safe(v: Any) -> str:
    """A cell that starts like a formula would run in a spreadsheet: neutralise it."""
    t = str(v)
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t


@router.get("/audit/verify")
async def check(sess: Session = need("audit.admin")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        return await verify(s, sess.caller.tenant_id)


@router.get("/audit/{event_id}")
async def one(event_id: UUID, sess: Session = need("audit.own")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        r = await s.get(m.AuditEvent, event_id)
    if r is None or r.tenant_id != sess.caller.tenant_id or (not sess.can("audit.all") and r.actor != sess.actor):
        raise HTTPException(404, "event not found")
    return _item(r, detail=True)
