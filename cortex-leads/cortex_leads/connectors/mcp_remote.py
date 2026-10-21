"""T2 connector `mcp` (DESIGN §5.8 "MCP bên ngoài"): a remote MCP server over HTTPS, read-only, never stdio.

What a person approves is pinned, so the server cannot change it afterwards:
  * `source.tool_pin` is the hash of the definition (name, description, input schema) of each exposed tool as
    the reviewer saw it; every call lists the tools again and refuses on any difference (rug-pull, tool poisoning);
  * only exposed tools are callable, a tool the server itself marks as writing or destructive is refused;
  * the same walls as http_readonly: https, `allow_hosts`, no redirects, DNS answers must be public, size caps,
    the query leaves redacted, the answer is scrubbed and returned as untrusted data.
The registry then forbids every write tool for the rest of the run (`ToolSpec.taints`)."""
import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet

from cortex_leads.config import get_settings
from cortex_leads.connectors.http_readonly import (
    MAX_BYTES,
    TIMEOUT_S,
    ConnectorError,
    Resolver,
    is_public,
    pin_of,
    resolve_host,
    scrub,
)
from cortex_leads.db import models as m
from cortex_leads.privacy.redact import redact

PROTOCOL = "2025-06-18"


def tool_pin(tools: list[dict[str, Any]]) -> str:
    keep = [{"name": t.get("name"), "description": t.get("description", ""), "inputSchema": t.get("inputSchema", {})}
            for t in sorted(tools, key=lambda t: str(t.get("name")))]
    return hashlib.sha256(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_source(source: dict[str, Any]) -> None:
    parts = urlsplit(str(source.get("url", "")))
    hosts, expose = source.get("allow_hosts"), source.get("expose")
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("url must be https:// (a remote MCP server; stdio is never run)")
    if not (isinstance(hosts, list) and parts.hostname in hosts):
        raise ValueError("url host must be in allow_hosts")
    if not (isinstance(expose, list) and len(expose) == 1 and isinstance(expose[0].get("remote"), str)):
        raise ValueError("expose must name exactly one remote tool")
    if not isinstance(source.get("tool_pin"), str):
        raise ValueError("tool_pin is required (hash of the reviewed tool definition)")


def read_only(tool: dict[str, Any]) -> bool:
    a = tool.get("annotations") or {}
    return a.get("readOnlyHint") is not False and a.get("destructiveHint") is not True


def _parse(r: httpx.Response, body: bytes, rid: int) -> dict[str, Any]:
    ctype = r.headers.get("content-type", "")
    if "event-stream" in ctype:
        msgs = [json.loads(line[5:]) for line in body.decode().splitlines() if line.startswith("data:")]
        data = next((x for x in reversed(msgs) if isinstance(x, dict) and x.get("id") == rid), None)
    elif "json" in ctype:
        data = json.loads(body)
    else:
        raise ConnectorError("BAD_RESPONSE")
    if not isinstance(data, dict) or "error" in data or "result" not in data:
        raise ConnectorError("UPSTREAM")
    return data["result"]


class _Rpc:
    def __init__(self, client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> None:
        self.client, self.url, self.headers, self._id = client, url, dict(headers), 0

    async def call(self, method: str, params: dict[str, Any] | None = None, *, notify: bool = False) -> Any:
        self._id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})}
        if not notify:
            msg["id"] = self._id
        try:
            async with self.client.stream("POST", self.url, json=msg, timeout=TIMEOUT_S, follow_redirects=False,
                                          headers={**self.headers, "Accept": "application/json, text/event-stream"}) as r:
                if r.status_code not in (200, 202):
                    raise ConnectorError("UPSTREAM")
                body = b""
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise ConnectorError("TOO_LARGE")
        except httpx.HTTPError as e:
            raise ConnectorError("UPSTREAM") from e
        if sid := r.headers.get("mcp-session-id"):
            self.headers["Mcp-Session-Id"] = sid
        if notify:
            return None
        try:
            return _parse(r, body, self._id)
        except ValueError as e:
            raise ConnectorError("BAD_RESPONSE") from e


async def _open(source: dict[str, Any], secret: bytes | None, client: httpx.AsyncClient, resolve: Resolver | None) -> _Rpc:
    host = urlsplit(source["url"]).hostname
    if host not in source.get("allow_hosts", []):
        raise ConnectorError("HOST_NOT_ALLOWED")
    if not all(is_public(a) for a in await (resolve or resolve_host)(host)):
        raise ConnectorError("PRIVATE_ADDRESS")
    headers = {"MCP-Protocol-Version": PROTOCOL}
    if secret:
        headers[source.get("auth_header", "Authorization")] = secret.decode()
    rpc = _Rpc(client, source["url"], headers)
    await rpc.call("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                  "clientInfo": {"name": "cortex-leads", "version": "1"}})
    await rpc.call("notifications/initialized", notify=True)
    return rpc


async def _tools(rpc: _Rpc) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = None
    for _ in range(5):  # a server with more than a few pages of tools is not one we pin
        res = await rpc.call("tools/list", {"cursor": cursor} if cursor else None)
        out += res.get("tools", [])
        if not (cursor := res.get("nextCursor")):
            return out
    raise ConnectorError("BAD_RESPONSE")


async def describe(source: dict[str, Any], secret: bytes | None, *, client: httpx.AsyncClient | None = None,
                   resolve: Resolver | None = None) -> list[dict[str, Any]]:
    """For the person adding the connector: the tools the server offers, to choose one and pin it."""
    own = client is None
    client = client or httpx.AsyncClient(follow_redirects=False)
    try:
        return await _tools(await _open(source, secret, client, resolve))
    finally:
        if own:
            await client.aclose()


async def call(conn: m.ToolConnector, query: str, *, client: httpx.AsyncClient | None = None,
               resolve: Resolver | None = None) -> dict[str, Any]:
    if conn.status != "active":
        raise ConnectorError("DISABLED")
    if conn.pin_sha256 != pin_of(conn.kind, conn.source):
        raise ConnectorError("PIN_MISMATCH")
    src, own = conn.source, client is None
    client = client or httpx.AsyncClient(follow_redirects=False)
    secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).decrypt(conn.secret_enc) if conn.secret_enc else None
    try:
        rpc = await _open(src, secret, client, resolve)
        remote = src["expose"][0]["remote"]
        tool = next((t for t in await _tools(rpc) if t.get("name") == remote), None)
        if tool is None or tool_pin([tool]) != src["tool_pin"]:
            raise ConnectorError("TOOL_CHANGED")  # the definition a person reviewed is not the one on offer
        if not read_only(tool):
            raise ConnectorError("NOT_READ_ONLY")
        res = await rpc.call("tools/call", {"name": remote, "arguments": {src["expose"][0].get("arg", "query"):
                                                                          redact(query[:200]).text}})
    finally:
        if own:
            await client.aclose()
    if res.get("isError"):
        raise ConnectorError("UPSTREAM")
    text = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")[:MAX_BYTES]
    payload: Any = res.get("structuredContent")
    if payload is None:
        try:
            payload = json.loads(text)
        except ValueError:
            payload = text
    return {"untrusted": True, "source": conn.name, "result": scrub(payload)}
