"""Read-only Pancake client (DESIGN §6): GET only, 5 req/s per page, retry 429/5xx.
The token travels as a query parameter, so URLs are never logged and errors name the path only."""
import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx INFO-logs full URLs (= the token)
BASE = "https://pages.fm/api/public_api"
RATE_PER_S = 5


class PancakeError(Exception):
    pass


def load_token(data_dir: Path = Path("data")) -> str:
    token = os.environ.get("PANCAKE_PAGE_TOKEN") or ""
    f = data_dir / "pancake_page_token"
    if not token and f.exists():
        token = f.read_text().strip()
    if not token:
        raise PancakeError("set PANCAKE_PAGE_TOKEN or put the token in data/pancake_page_token")
    return token


class TokenBucket:
    def __init__(self, rate: float = RATE_PER_S, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.rate, self.clock, self.sleep = rate, clock, sleep
        self.tokens, self.stamp = rate, clock()

    async def acquire(self) -> None:
        while True:
            now = self.clock()
            self.tokens = min(self.rate, self.tokens + (now - self.stamp) * self.rate)
            self.stamp = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            await self.sleep((1 - self.tokens) / self.rate)


class PancakeClient:
    def __init__(self, page_id: str, token: str, *, http: httpx.AsyncClient | None = None,
                 bucket: TokenBucket | None = None, retries: int = 4,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.page_id, self._token = page_id, token
        self._http = http or httpx.AsyncClient(timeout=30)
        self._bucket, self._retries, self._sleep = bucket or TokenBucket(), retries, sleep

    def __repr__(self) -> str:
        return f"PancakeClient(page_id={self.page_id!r})"

    async def _get(self, version: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{BASE}/{version}/pages/{self.page_id}/{path}"
        q = {**params, "page_access_token": self._token}
        for attempt in range(self._retries + 1):
            await self._bucket.acquire()
            try:
                r = await self._http.get(url, params=q)
            except httpx.TransportError as e:
                status, err = 0, type(e).__name__
            else:
                status, err = r.status_code, ""
                if status == 200:
                    return r.json()
                if status not in (429, 500, 502, 503, 504):
                    raise PancakeError(f"GET {path} -> HTTP {status}")
            if attempt == self._retries:
                raise PancakeError(f"GET {path} failed after retries (HTTP {status} {err})".strip())
            await self._sleep(min(30.0, 0.5 * 2 ** attempt))
        raise AssertionError("unreachable")

    async def conversations(self, *, since: int | None = None,
                            last_conversation_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"order_by": "updated_at", "type": "INBOX"}
        if since is not None:
            params["since"] = since
        if last_conversation_id:
            params["last_conversation_id"] = last_conversation_id
        return (await self._get("v2", "conversations", params)).get("conversations", [])

    async def messages(self, conversation_id: str, current_count: int = 0) -> dict[str, Any]:
        params = {"current_count": current_count} if current_count else {}
        return await self._get("v1", f"conversations/{conversation_id}/messages", params)

    async def aclose(self) -> None:
        await self._http.aclose()
