"""Poll Pancake (GET only) -> Event Format v1 -> signed POST to the ingest API.
Run: python -m bridges.pancake.run [--loop SECONDS]. Env: PANCAKE_PAGE_ID, PANCAKE_PAGE_TOKEN,
CL_INGEST_URL, CL_CONNECTOR_ID, CL_CONNECTOR_SECRET, [PANCAKE_CHANNEL_KIND=messenger]."""
import asyncio
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from bridges.pancake.client import PancakeClient, load_token
from bridges.pancake.mapper import map_message, parse_time
from cortex_leads.ingest.signing import sign

log = logging.getLogger("bridges.pancake")
MAX_BATCH = 100
MAX_CONV_PAGES, MAX_MSG_PAGES = 20, 5
BACKFILL = timedelta(days=7)  # first run only


def load_cursor(path: Path, page_id: str) -> int | None:
    try:
        return int(json.loads(path.read_text())[page_id])
    except (OSError, ValueError, KeyError):
        return None


def save_cursor(path: Path, page_id: str, since: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data[page_id] = since
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


async def collect(client: PancakeClient, *, channel_kind: str, since: int) -> tuple[list[dict], int]:
    """Events (oldest first) for conversations updated since `since`, and the next cursor."""
    convs: list[dict[str, Any]] = []
    last: str | None = None
    for _ in range(MAX_CONV_PAGES):
        page = await client.conversations(since=since, last_conversation_id=last)
        convs += page
        if len(page) < 60:
            break
        last = page[-1]["id"]
    events: list[dict] = []
    next_since = since
    for conv in sorted(convs, key=lambda c: c["updated_at"]):
        msgs: list[dict] = []
        customer = conv.get("from") or {}
        for _ in range(MAX_MSG_PAGES):  # Pancake returns newest first, 30 per call
            resp = await client.messages(conv["id"], current_count=len(msgs))
            customer = resp.get("conv_from") or customer
            batch = [x for x in resp.get("messages") or [] if x["id"] not in {y["id"] for y in msgs}]
            msgs += batch
            if not batch or parse_time(batch[-1]["inserted_at"]).timestamp() < since:
                break
        for msg in reversed(msgs):
            if parse_time(msg["inserted_at"]).timestamp() < since or not customer.get("id"):
                continue
            ev = map_message(msg, page_id=client.page_id, conversation_id=conv["id"],
                             customer=customer, channel_kind=channel_kind)
            if ev:
                events.append(ev)
        next_since = max(next_since, int(parse_time(conv["updated_at"]).timestamp()))
    return events, next_since


async def post_events(http: httpx.AsyncClient, url: str, connector_id: str, secret: str,
                      events: list[dict]) -> dict[str, int]:
    counts = {"accepted": 0, "duplicate": 0, "rejected": 0}
    for i in range(0, len(events), MAX_BATCH):
        body = json.dumps({"format": "cortex.event/1", "events": events[i:i + MAX_BATCH]}).encode()
        ts = int(time.time())
        r = await http.post(url, content=body, headers={
            "X-Connector-Id": connector_id, "X-Timestamp": str(ts),
            "X-Signature": sign(secret.encode(), ts, body), "Content-Type": "application/json"})
        r.raise_for_status()  # cursor must not advance past a batch the server did not take
        for res in r.json()["results"]:
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            if res["status"] == "rejected":
                log.warning("rejected %s: %s", res.get("external_id"), res.get("error"))
    return counts


async def run_once(client: PancakeClient, http: httpx.AsyncClient, *, ingest_url: str,
                   connector_id: str, secret: str, channel_kind: str, cursor_path: Path,
                   now: datetime | None = None) -> dict[str, int]:
    since = load_cursor(cursor_path, client.page_id)
    if since is None:
        since = int(((now or datetime.now(UTC)) - BACKFILL).timestamp())
    events, next_since = await collect(client, channel_kind=channel_kind, since=since)
    counts = await post_events(http, ingest_url, connector_id, secret, events)
    save_cursor(cursor_path, client.page_id, next_since)
    return counts


async def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO)
    page_id = os.environ["PANCAKE_PAGE_ID"]
    client = PancakeClient(page_id, load_token())
    kw = dict(ingest_url=os.environ["CL_INGEST_URL"], connector_id=os.environ["CL_CONNECTOR_ID"],
              secret=os.environ["CL_CONNECTOR_SECRET"],
              channel_kind=os.environ.get("PANCAKE_CHANNEL_KIND", "messenger"),
              cursor_path=Path("data/pancake_cursor.json"))
    interval = int(argv[argv.index("--loop") + 1]) if "--loop" in argv else 0
    async with httpx.AsyncClient(timeout=30) as http:
        while True:
            log.info("pancake poll: %s", await run_once(client, http, **kw))
            if not interval:
                return
            await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
