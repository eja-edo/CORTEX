"""Dữ liệu (giai đoạn 1): the price list and the trial-lesson calendar, the one place every number the AI says to a customer comes from
(A7). Anyone who works with customers may read it; only the owner may change it, by importing a CSV (a changed row becomes a new version,
the old one stays as history). The import is two calls: the first with `dry_run` only reports what would happen, the second saves.
The audit line holds counts, never a row."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from cortex_leads.catalog.importer import MAX_BYTES, ImportRefused, import_catalog
from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import audit
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

router = APIRouter(prefix="/catalog")
SOON = timedelta(days=14)
# Safe to open in a spreadsheet: no cell starts with = + - @ (the rule the importer does not enforce but the sample keeps).
TEMPLATE = "code,name,category,price,unit,valid_until\nKH01,Khoá IELTS 12 tuần,khoa_hoc,6500000,khoá,2026-12-31\nKH02,Giao tiếp cơ bản A2,khoa_hoc,3600000,khoá,\n"


def _num(x: Decimal | None) -> int | float | None:
    if x is None:
        return None
    return int(x) if x == x.to_integral_value() else float(x)


@router.get("")
async def read(sess: Session = need("catalog.read")) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(sess.caller.tenant_id) as s:
        items = (await s.execute(select(m.CatalogItem).where(m.CatalogItem.active.is_(True)).order_by(m.CatalogItem.category, m.CatalogItem.code))).scalars().all()
        last = (await s.execute(select(m.AuditEvent.at).where(m.AuditEvent.action == "catalog.imported").order_by(m.AuditEvent.at.desc()).limit(1))).scalar_one_or_none()
    rows = [{"code": c.code, "name": c.name, "category": c.category, "price": _num(c.price), "unit": c.unit, "valid_until": wire(c.valid_until),
             "version": c.version, "state": "expired" if c.valid_until and c.valid_until < now else "soon" if c.valid_until and c.valid_until < now + SOON else "ok"} for c in items]
    return {"items": rows, "categories": sorted({r["category"] for r in rows if r["category"]}),
            "stats": {"active": len(rows), "soon": sum(r["state"] == "soon" for r in rows), "expired": sum(r["state"] == "expired" for r in rows),
                      "last_import_at": wire(last)},  # from the audit trail: a CLI import leaves no line, so this can be empty on a business that has data
            "can_import": sess.can("catalog.manage")}


@router.get("/template")
async def template(sess: Session = need("catalog.read")) -> dict[str, str]:
    return {"filename": "mau-bang-gia.csv", "csv": TEMPLATE}


class Import(BaseModel):
    csv: str = Field(max_length=MAX_BYTES + 1000)
    dry_run: bool = True  # saving has to be asked for


@router.post("/import")
async def import_(body: Import, sess: Session = need("catalog.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        try:
            result = await import_catalog(s, sess.caller.tenant_id, body.csv, dry_run=body.dry_run)
        except ImportRefused as e:
            raise HTTPException(422, {"code": e.code, "message": e.message}) from None
        if not body.dry_run and result.to_save:
            await audit(sess, s, "data", "catalog.imported", f"Nhập bảng giá: {result.new} mục mới, {result.changed} mục đổi",
                        metadata={"new": result.new, "changed": result.changed, "unchanged": result.unchanged, "errors": len(result.errors)})
    return result.as_dict()
