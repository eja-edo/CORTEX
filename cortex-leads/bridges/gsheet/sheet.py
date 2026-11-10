"""Google Sheet (link-shared CSV export) -> catalog + order `deal.updated`. DEV ONLY: link sharing is
for the test rig; real customers use a service account (T1).
Run: python -m bridges.gsheet.sheet [--loop SECONDS]. Env: GSHEET_ID, [GSHEET_CATALOG_GID, CL_TENANT_ID,
GSHEET_ORDERS_GID], CL_INGEST_URL, CL_CONNECTOR_ID, CL_CONNECTOR_SECRET."""
import argparse
import asyncio
import csv
import io
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

from bridges.pancake.run import post_events
from cortex_leads.cli import cmd_import_catalog
from cortex_leads.core.logs import setup_logging

log = logging.getLogger(__name__)

URL = "https://docs.google.com/spreadsheets/d/{id}/export?format=csv&gid={gid}"
STATUS = {"booked": "booked", "won": "won", "lost": "lost", "cancelled": "cancelled",
          "đặt lịch": "booked", "đã chốt": "won", "mất": "lost", "hủy": "cancelled"}


async def fetch_csv(http: httpx.AsyncClient, sheet_id: str, gid: str) -> str:
    r = await http.get(URL.format(id=sheet_id, gid=gid), follow_redirects=True)
    r.raise_for_status()
    return r.content.decode("utf-8-sig")


async def import_catalog(text: str, tenant: UUID) -> None:
    """Reuses cli.import-catalog (versioning, unchanged rows) through a temp file."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "c.csv").write_text(text, encoding="utf-8")
        await cmd_import_catalog(argparse.Namespace(csv=str(Path(d) / "c.csv"), tenant=tenant))


def orders_to_events(text: str, tz: str = "Asia/Ho_Chi_Minh") -> list[dict]:
    """Columns: ma_don, sdt_hoac_ref, trang_thai, gia_tri, ngay. Unknown status rows are skipped."""
    events: list[dict] = []
    for r in csv.DictReader(io.StringIO(text)):
        status = STATUS.get((r.get("trang_thai") or "").strip().lower())
        who = (r.get("sdt_hoac_ref") or "").strip()
        if not (status and who and r.get("ma_don")):
            continue
        contact = {"ref": dict(zip(("connector_id", "external_id"), who.split(":", 1)))} if ":" in who \
            else {"phone": who}
        deal: dict = {"external_id": f"gsheet:{r['ma_don'].strip()}", "status": status, **({"value": float(r["gia_tri"])} if (r.get("gia_tri") or "").strip() else {})}
        events.append({"type": "deal.updated", "external_id": f"gsheet:{r['ma_don'].strip()}:{status}",
                       "occurred_at": datetime.fromisoformat(r["ngay"].strip()).replace(
                           tzinfo=ZoneInfo(tz)).isoformat(), "contact": contact, "deal": deal})
    return events


async def main(argv: list[str]) -> None:
    e, interval = os.environ, int(argv[1]) if argv[:1] == ["--loop"] else 0
    async with httpx.AsyncClient(timeout=30) as http:
        while True:
            if e.get("GSHEET_CATALOG_GID") and e.get("CL_TENANT_ID"):
                await import_catalog(await fetch_csv(http, e["GSHEET_ID"], e["GSHEET_CATALOG_GID"]),
                                     UUID(e["CL_TENANT_ID"]))
            if e.get("GSHEET_ORDERS_GID"):
                evs = orders_to_events(await fetch_csv(http, e["GSHEET_ID"], e["GSHEET_ORDERS_GID"]))
                counts = await post_events(http, e["CL_INGEST_URL"], e["CL_CONNECTOR_ID"],
                                           e["CL_CONNECTOR_SECRET"], evs)  # re-posting is a no-op: dedupe
                log.info("orders posted: %s", counts)
            if not interval:
                return
            await asyncio.sleep(interval)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main(sys.argv[1:]))
