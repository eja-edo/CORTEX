"""T1 connector `http_readonly` (DESIGN §5.8): a GET to a host the business named, nothing else.

  * https only, host must be in `allow_hosts`, redirects never followed, DNS answers that point at a private,
    loopback or link-local address are refused (SSRF);
  * the query leaves redacted (no phone / email), the answer is JSON, capped in size and depth, scrubbed of
    PII, and handed back as UNTRUSTED data;
  * the config is pinned by a hash: a row edited after review is refused until it is pinned again.

Nothing here can write: the verb is fixed, there is no body."""
import asyncio
import hashlib
import ipaddress
import json
import socket
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from cryptography.fernet import Fernet

from cortex_leads.config import get_settings
from cortex_leads.db import models as m
from cortex_leads.privacy.redact import redact

MAX_BYTES = 64 * 1024
MAX_DEPTH = 5
MAX_ITEMS = 50
TIMEOUT_S = 8
Resolver = Callable[[str], Awaitable[list[str]]]


class ConnectorError(Exception):
    """.code: PIN_MISMATCH | DISABLED | HOST_NOT_ALLOWED | PRIVATE_ADDRESS | BAD_RESPONSE | UPSTREAM | TOO_LARGE"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def pin_of(kind: str, source: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"kind": kind, "source": source}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_source(source: dict[str, Any]) -> None:
    """Raises ValueError for a config that could never be safe. `url` holds `{q}` where the query goes."""
    parts = urlsplit(str(source.get("url", "")))
    hosts = source.get("allow_hosts")
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("url must be https://")
    if not (isinstance(hosts, list) and hosts and all(isinstance(h, str) for h in hosts)):
        raise ValueError("allow_hosts must list the hosts that may be called")
    if parts.hostname not in hosts:
        raise ValueError("url host must be in allow_hosts")
    if "{q}" not in source["url"] or parts.hostname.count("{"):
        raise ValueError("url must hold {q} (in the path or query, never the host)")


async def resolve_host(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return [i[4][0] for i in infos]


def is_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    return ip.is_global and not ip.is_multicast


def scrub(v: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        return None
    if isinstance(v, dict):
        return {str(k)[:60]: scrub(x, depth + 1) for k, x in list(v.items())[:MAX_ITEMS]}
    if isinstance(v, list):
        return [scrub(x, depth + 1) for x in v[:MAX_ITEMS]]
    if isinstance(v, str):
        return redact(v[:500]).text
    return v if isinstance(v, int | float | bool) or v is None else str(v)[:100]


async def fetch(conn: m.ToolConnector, query: str, *, client: httpx.AsyncClient | None = None,
                resolve: Resolver | None = None) -> dict[str, Any]:
    if conn.status != "active":
        raise ConnectorError("DISABLED")
    if conn.pin_sha256 != pin_of(conn.kind, conn.source):
        raise ConnectorError("PIN_MISMATCH")
    parts = urlsplit(conn.source["url"])
    if parts.hostname not in conn.source.get("allow_hosts", []):
        raise ConnectorError("HOST_NOT_ALLOWED")
    if not all(is_public(a) for a in await (resolve or resolve_host)(parts.hostname)):
        raise ConnectorError("PRIVATE_ADDRESS")
    url = conn.source["url"].replace("{q}", quote(redact(query[:200]).text, safe=""))
    headers = {"Accept": "application/json"}
    if conn.secret_enc:
        headers[conn.source.get("auth_header", "Authorization")] = Fernet(
            get_settings().CONNECTOR_SECRET_KEY).decrypt(conn.secret_enc).decode()
    own = client is None
    client = client or httpx.AsyncClient(follow_redirects=False)
    try:
        async with client.stream("GET", url, headers=headers, timeout=TIMEOUT_S, follow_redirects=False) as r:
            if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
                raise ConnectorError("BAD_RESPONSE" if r.status_code == 200 else "UPSTREAM")
            body = b""
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise ConnectorError("TOO_LARGE")
    except httpx.HTTPError as e:
        raise ConnectorError("UPSTREAM") from e
    finally:
        if own:
            await client.aclose()
    try:
        return {"untrusted": True, "source": conn.name, "result": scrub(json.loads(body))}
    except ValueError as e:
        raise ConnectorError("BAD_RESPONSE") from e
