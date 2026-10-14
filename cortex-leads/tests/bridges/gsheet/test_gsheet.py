from pathlib import Path

import httpx
from sqlalchemy import select

from bridges.gsheet.sheet import fetch_csv, import_catalog, orders_to_events
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

SAMPLES = Path(__file__).resolve().parents[3] / "dev" / "samples"
ORDERS = "ma_don,sdt_hoac_ref,trang_thai,gia_tri,ngay\nDH1,0901,won,100000,2026-10-14\nDH2,cn_x:p1,đặt lịch,,2026-10-15\nDH3,0902,???,1,2026-10-15\n"


def test_orders_map_phone_ref_and_skip_unknown_status() -> None:
    a, b = orders_to_events(ORDERS)  # DH3 skipped
    assert (a["external_id"], a["contact"], a["deal"]) == ("gsheet:DH1:won", {"phone": "0901"},
                                                          {"external_id": "gsheet:DH1", "status": "won", "value": 100000.0})
    assert b["contact"] == {"ref": {"connector_id": "cn_x", "external_id": "p1"}} and b["deal"] == {"external_id": "gsheet:DH2", "status": "booked"}
    assert a["occurred_at"] == "2026-10-14T00:00:00+07:00"


def test_idempotent_external_id_and_sample_file() -> None:
    assert orders_to_events(ORDERS) == orders_to_events(ORDERS)  # same ma_don+status -> same id -> ingest dedupes
    assert len(orders_to_events((SAMPLES / "orders.csv").read_text())) == 3


async def test_fetch_csv_uses_export_url() -> None:
    seen: list[str] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, content="﻿a,b\n1,2\n".encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as http:
        assert await fetch_csv(http, "SID", "7") == "a,b\n1,2\n"
    assert seen == ["https://docs.google.com/spreadsheets/d/SID/export?format=csv&gid=7"]


async def test_catalog_import_reuses_cli_versioning(tenant_factory, capsys) -> None:
    t = await tenant_factory()
    text = (SAMPLES / "catalog.csv").read_text()
    await import_catalog(text, t.id)
    await import_catalog(text, t.id)  # unchanged
    await import_catalog(text.replace("2500000", "2700000"), t.id)  # price change -> version 2
    out = capsys.readouterr().out
    assert "new_versions=2 unchanged=0" in out and "new_versions=0 unchanged=2" in out and "new_versions=1 unchanged=1" in out
    async with tenant_session(t.id) as s:
        rows = (await s.execute(select(m.CatalogItem).where(m.CatalogItem.code == "KH01")
                                .order_by(m.CatalogItem.version))).scalars().all()
    assert [(r.version, r.active) for r in rows] == [(1, False), (2, True)]
