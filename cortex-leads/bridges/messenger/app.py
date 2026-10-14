"""Messenger bridge: webhook -> signed ingest; Cortex Action Format v1 -> Send API (README)."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response

from bridges.messenger.mapper import map_messaging
from bridges.messenger.sender import Sender
from cortex_leads.ingest.signing import sign, verify

log = logging.getLogger("bridges.messenger")
MAX_BATCH, MAX_SKEW_S = 100, 300

def _ids(v: str | None) -> frozenset[str]:  # comma-separated
    return frozenset(x.strip() for x in (v or "").split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    app_secret: str = field(repr=False)
    verify_token: str = field(repr=False)
    page_token: str = field(repr=False)
    page_id: str
    own_app_id: str
    ingest_url: str
    connector_id: str
    connector_secret: str = field(repr=False)
    human_apps: frozenset[str] = frozenset()
    bot_apps: frozenset[str] = frozenset()
    graph_version: str = "v25.0"
    policy: dict[str, Any] = field(default_factory=dict)  # ai_send, quiet_hours, max_per_minute

    @classmethod
    def from_env(cls, data_dir: Path = Path("data")) -> "Settings":
        e = os.environ
        token = e.get("MESSENGER_PAGE_TOKEN", "")
        f = data_dir / "messenger_page_token"
        if not token and f.exists():
            token = f.read_text().strip()
        pol = e.get("MESSENGER_POLICY", "")  # inline JSON
        values = {"app_secret": e.get("MESSENGER_APP_SECRET"), "verify_token": e.get("MESSENGER_VERIFY_TOKEN"),
                  "page_token": token, "page_id": e.get("MESSENGER_PAGE_ID"),
                  "own_app_id": e.get("MESSENGER_OWN_APP_ID"), "ingest_url": e.get("CL_INGEST_URL"),
                  "connector_id": e.get("CL_CONNECTOR_ID"), "connector_secret": e.get("CL_CONNECTOR_SECRET")}
        if missing := [k for k, v in values.items() if not v]:
            raise RuntimeError(f"missing settings: {', '.join(missing)}")  # no default secrets (PLAN §0.4)
        return cls(**values, graph_version=e.get("MESSENGER_GRAPH_VERSION", "v25.0"),
                   human_apps=_ids(e.get("MESSENGER_HUMAN_APP_IDS")), bot_apps=_ids(e.get("MESSENGER_BOT_APP_IDS")),
                   policy=json.loads(pol) if pol else {})

class Forwarder:
    """In-memory queue so Meta gets its 200 at once; retries with backoff, never drops on failure."""

    def __init__(self, s: Settings, http: httpx.AsyncClient,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.s, self.http, self.sleep = s, http, sleep
        self.queue: list[dict] = []

    def add(self, events: list[dict]) -> None:
        self.queue += events

    async def flush(self, attempts: int = 5) -> None:
        while self.queue:
            batch = self.queue[:MAX_BATCH]
            body = json.dumps({"format": "cortex.event/1", "events": batch}).encode()
            for n in range(attempts):
                ts = int(time.time())
                try:
                    r = await self.http.post(self.s.ingest_url, content=body, headers={
                        "X-Connector-Id": self.s.connector_id, "X-Timestamp": str(ts),
                        "X-Signature": sign(self.s.connector_secret.encode(), ts, body),
                        "Content-Type": "application/json"})
                    if r.status_code < 300:
                        break
                    if r.status_code < 500 and r.status_code != 429:
                        log.error("ingest refused batch: HTTP %s", r.status_code)
                        break  # 4xx will not heal by retrying
                except httpx.TransportError:
                    pass
                if n == attempts - 1:
                    log.error("ingest unreachable; %d events kept for the next flush", len(self.queue))
                    return
                await self.sleep(min(30.0, 0.5 * 2 ** n))
            del self.queue[:len(batch)]

def create_app(settings: Settings | None = None, *, http: httpx.AsyncClient | None = None,
               data_dir: Path = Path("data"), run_worker: bool = False,
               sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> FastAPI:
    s = settings or Settings.from_env(data_dir)
    http = http or httpx.AsyncClient(timeout=30)
    fwd = Forwarder(s, http, sleep)
    sender = Sender(page_token=s.page_token, version=s.graph_version, policy=s.policy,
                    store=data_dir / "messenger_actions.json", http=http)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async def loop() -> None:
            while True:
                await fwd.flush()
                await asyncio.sleep(1)
        task = asyncio.create_task(loop()) if run_worker else None
        yield
        if task:
            task.cancel()

    app = FastAPI(lifespan=lifespan)
    app.state.forwarder = fwd

    @app.get("/webhook")
    async def challenge(mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
                        chal: str = Query("", alias="hub.challenge")) -> Response:
        if mode != "subscribe" or not hmac.compare_digest(token.encode(), s.verify_token.encode()):
            raise HTTPException(403, "verify token mismatch")
        return Response(chal, media_type="text/plain")

    @app.post("/webhook")
    async def webhook(request: Request) -> dict[str, str]:
        body = await request.body()  # signature is over the raw bytes, before any JSON parsing
        want = "sha256=" + hmac.new(s.app_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(want, request.headers.get("X-Hub-Signature-256", "")):
            raise HTTPException(401, "invalid signature")
        payload = json.loads(body) if body else {}
        entries = payload.get("entry") or [] if payload.get("object") == "page" else []
        fwd.add([ev for en in entries for item in en.get("messaging") or []
                 if (ev := map_messaging(item, page_id=str(en.get("id") or s.page_id), own_app_id=s.own_app_id,
                                     human_apps=s.human_apps, bot_apps=s.bot_apps))])
        return {"status": "ok"}

    @app.post("/actions")
    async def actions(request: Request) -> dict[str, Any]:
        body = await request.body()
        try:
            ts = int(request.headers.get("X-Cortex-Timestamp", ""))
        except ValueError:
            raise HTTPException(401, "invalid signature") from None
        if not verify(s.connector_secret.encode(), ts, body, request.headers.get("X-Cortex-Signature", ""),
                      now=datetime.now(UTC), max_skew_s=MAX_SKEW_S):
            raise HTTPException(401, "invalid signature")
        action = json.loads(body)
        if action.get("format") != "cortex.action/1" or not action.get("action_id"):
            raise HTTPException(400, "bad action")
        return await sender.handle(action)

    return app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(run_worker=True), host="0.0.0.0", port=int(os.environ.get("MESSENGER_PORT", "8110")))
