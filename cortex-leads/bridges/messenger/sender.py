"""Cortex Action Format v1 -> Graph Send API. This is the bridge's own blocking layer (DESIGN §5.2, N3)."""
import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
GRAPH = "https://graph.facebook.com"


class Sender:
    def __init__(self, *, page_token: str, version: str, policy: dict[str, Any], store: Path,
                 http: httpx.AsyncClient | None = None, tz: str = "Asia/Ho_Chi_Minh",
                 clock: Callable[[], float] = time.time) -> None:
        self._token, self._version, self.policy, self._store = page_token, version, policy, store
        self._http, self._tz, self._clock = http or httpx.AsyncClient(timeout=15), ZoneInfo(tz), clock
        self._sent_at, self._lock = deque[float](), asyncio.Lock()
        try:
            self._done: dict[str, dict] = json.loads(store.read_text())
        except (OSError, ValueError):
            self._done = {}

    def _remember(self, action_id: str, result: dict) -> dict:
        self._done[action_id] = result
        self._store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._store.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._done))
        tmp.replace(self._store)
        return result

    def _decide(self, a: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
        """(refusal reason | None, Send API params)."""
        actor, window = str(a.get("actor", "")), a.get("window") or {}
        ai = actor.startswith("ai:")
        if a.get("type") != "send_message" or (a.get("channel") or {}).get("kind") != "messenger":
            return "NOT_SUPPORTED", {}
        if ai and not self.policy.get("ai_send", False):
            return "AI_SEND_DISABLED", {}
        if not window.get("open"):
            return "WINDOW_CLOSED", {}
        human_agent = window.get("basis") == "human_agent"
        if human_agent and not actor.startswith("staff:"):
            return "PLATFORM_POLICY", {}  # HUMAN_AGENT is for a person typing, never for ai:*/system
        qh = self.policy.get("quiet_hours")  # [start_hour, end_hour) in the business timezone
        if ai and qh:
            h, (s, e) = datetime.fromtimestamp(self._clock(), self._tz).hour, qh
            if (s <= h < e) if s <= e else (h >= s or h < e):
                return "QUIET_HOURS", {}
        mt = {"messaging_type": "MESSAGE_TAG", "tag": "HUMAN_AGENT"} if human_agent else {"messaging_type": "RESPONSE"}
        return None, mt

    async def handle(self, a: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            aid = str(a["action_id"])
            if aid in self._done:  # idempotency: same answer, no second send
                return self._done[aid]
            reason, params = self._decide(a)
            if reason:
                return self._remember(aid, {"status": "refused", "reason": reason})
            now = self._clock()
            while self._sent_at and now - self._sent_at[0] >= 60:
                self._sent_at.popleft()
            if len(self._sent_at) >= int(self.policy.get("max_per_minute", 30)):
                return {"status": "refused", "reason": "RATE_LIMIT"}  # transient: not remembered
            text = a.get("text") or ""
            if a.get("disclosure"):
                text += "\n— " + a["disclosure"]
            body = {"recipient": {"id": a["conversation"]["external_id"]}, **params, "message": {"text": text}}
            try:
                r = await self._http.post(f"{GRAPH}/{self._version}/me/messages", json=body,
                                          headers={"Authorization": f"Bearer {self._token}"})
            except httpx.TransportError:
                return {"status": "error", "retryable": True}
            if r.status_code >= 400:  # 5xx/429 may heal, other 4xx will not
                logging.getLogger(__name__).warning("send api: HTTP %s", r.status_code)
                return {"status": "error", "retryable": r.status_code >= 500 or r.status_code == 429}
            self._sent_at.append(now)
            return self._remember(aid, {"status": "sent", "external_message_id": r.json().get("message_id")})
