"""Reading a price list from CSV (DESIGN A7: every number a customer sees points at one catalog row). One function serves the console
screen and `cli import-catalog`, so the two can never disagree about what a changed row is.

Columns: code,name,category,price,unit,valid_until (ISO). A row whose name, category, price, unit or expiry differs from the active one
becomes version+1 and the old row is switched off (never deleted: a draft written yesterday still points at it). A bad row is reported
with its line number and skipped; the others still go in. Nothing here ever writes a cell back out as text, so a name that starts with
`=` is stored as a name and shown as a name."""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.db import models as m

MAX_BYTES = 1_000_000
MAX_ROWS = 2000
REQUIRED = ("code", "name")
LIMITS = {"code": 64, "name": 200, "category": 60, "unit": 30}
PRICE = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,2})?$")  # ASCII digits only: `\d` would also take ٣٤٥ or １２３
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ImportRefused(ValueError):
    """The whole file is unusable (too big, not text, no header). `code` is stable for the screen."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class ImportResult:
    new: int = 0          # codes the catalog did not have
    changed: int = 0      # codes that now get version+1
    unchanged: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)  # {"line": n, "message": "..."}
    dry_run: bool = False

    @property
    def to_save(self) -> int:
        return self.new + self.changed

    def as_dict(self) -> dict[str, Any]:
        return {"new": self.new, "changed": self.changed, "unchanged": self.unchanged, "errors": self.errors, "to_save": self.to_save, "dry_run": self.dry_run}


def _clean(text: str) -> str:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ImportRefused("TOO_BIG", "Tệp lớn quá (tối đa 1 MB). Hãy tách thành nhiều tệp.")
    if "�" in text:
        raise ImportRefused("NOT_UTF8", "Tệp không phải UTF-8. Mở bằng Excel rồi lưu lại dạng «CSV UTF-8».")
    return text.lstrip("﻿")


def _price(raw: str) -> Decimal | None:
    raw = raw.strip()
    if not raw:
        return None
    if not PRICE.match(raw):
        raise ValueError(f"giá «{raw}» không phải số. Ghi 6500000 (không dấu chấm, phẩy hay chữ).")
    return Decimal(raw)


def _when(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    except (ValueError, OverflowError):  # OverflowError: a date near year 0001 with a zone offset leaves the range of dates
        raise ValueError(f"hạn «{raw}» không đúng dạng ngày. Ghi 2026-12-31 hoặc để trống.") from None


def _row(r: dict[str, str | None]) -> dict[str, Any]:
    """One CSV row as typed values, or ValueError saying what to fix."""
    if r.get(None):  # more cells than the header: an unquoted comma inside a price or a name shifted everything after it
        raise ValueError("có nhiều ô hơn dòng tiêu đề. Nếu giá hoặc tên có dấu phẩy, hãy đặt cả ô trong dấu ngoặc kép.")
    v = {k: (r.get(k) or "").strip() for k in ("code", "name", "category", "price", "unit", "valid_until")}
    for k in REQUIRED:
        if not v[k]:
            raise ValueError(f"thiếu cột «{k}».")
    for k, n in LIMITS.items():
        if len(v[k]) > n:
            raise ValueError(f"«{k}» dài quá {n} ký tự.")
        if CONTROL.search(v[k]):
            raise ValueError(f"«{k}» có ký tự điều khiển.")
    return {"code": v["code"], "name": v["name"], "category": v["category"] or None, "price": _price(v["price"]), "unit": v["unit"] or None,
            "valid_until": _when(v["valid_until"])}


def _same(cur: m.CatalogItem, n: dict[str, Any]) -> bool:
    cp = None if cur.price is None else Decimal(cur.price)
    return (cur.name == n["name"] and (cur.category or None) == n["category"] and cp == n["price"] and (cur.unit or None) == n["unit"]
            and cur.valid_until == n["valid_until"])


async def import_catalog(session: AsyncSession, tenant_id: UUID, text: str, *, dry_run: bool = False) -> ImportResult:
    """The caller owns the transaction (and the tenant: `session` is a tenant session)."""
    text = _clean(text)
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    try:
        header = {(h or "").strip() for h in (reader.fieldnames or [])}
        if not all(k in header for k in REQUIRED):
            raise ImportRefused("NO_HEADER", "Dòng đầu phải có các cột code,name,category,price,unit,valid_until (tải tệp mẫu để xem).")
        reader.fieldnames = [(h or "").strip() for h in reader.fieldnames or []]
        for r in reader:
            if len(rows) >= MAX_ROWS:
                raise ImportRefused("TOO_MANY_ROWS", f"Tệp có quá {MAX_ROWS} dòng. Hãy tách thành nhiều tệp.")
            rows.append((reader.line_num, r))
    except csv.Error as e:  # a cell over 131072 characters, or a lone carriage return (Excel's "CSV (Macintosh)")
        raise ImportRefused("BAD_CSV", f"Tệp CSV không đọc được ở gần dòng {reader.line_num + 1}: {e}. Mở bằng Excel rồi lưu lại dạng «CSV UTF-8».") from None
    active = {c.code: c for c in (await session.execute(select(m.CatalogItem).where(m.CatalogItem.active.is_(True)))).scalars()}
    top = dict((await session.execute(select(m.CatalogItem.code, func.max(m.CatalogItem.version)).group_by(m.CatalogItem.code))).all())
    out, seen = ImportResult(dry_run=dry_run), set()
    for line, r in rows:
        if not any((x or "").strip() for x in r.values() if isinstance(x, str)):
            continue  # a blank line
        try:
            n = _row(r)
        except ValueError as e:
            out.errors.append({"line": line, "message": f"Dòng {line}: {e}"})
            continue
        if n["code"] in seen:
            out.errors.append({"line": line, "message": f"Dòng {line}: mã «{n['code']}» đã có ở dòng trên trong tệp này."})
            continue
        seen.add(n["code"])
        cur = active.get(n["code"])
        if cur and _same(cur, n):
            out.unchanged += 1
            continue
        if cur:
            out.changed += 1
        else:
            out.new += 1
        if dry_run:
            continue
        if cur:
            cur.active = False
        session.add(m.CatalogItem(tenant_id=tenant_id, version=top.get(n["code"], 0) + 1, attrs=dict(cur.attrs) if cur else {}, **n))
    return out
