"""Who is asking, from where: bound once per request by the middleware, read by `audit.record` so no call site has to
thread the address, the browser and the request id through its arguments."""
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import FastAPI, Request

from cortex_leads.config import get_settings
from cortex_leads.core.ids import uuid7


@dataclass
class RequestInfo:
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    session_id: str | None = None  # set by the console session (a short fingerprint of the cookie, never the cookie)


_current: ContextVar[RequestInfo | None] = ContextVar("audit_request", default=None)


def current() -> RequestInfo:
    return _current.get() or RequestInfo()


def client_ip(request: Request) -> str | None:
    if get_settings().TRUST_PROXY_HEADERS and (fwd := request.headers.get("x-forwarded-for")):
        return fwd.split(",")[0].strip()[:64] or None
    return request.client.host if request.client else None


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def bind(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id", "")
        rid = rid if 8 <= len(rid) <= 64 and rid.replace("-", "").replace("_", "").isalnum() else f"req_{uuid7().hex[:20]}"
        token = _current.set(RequestInfo(ip=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:300] or None,
                                         request_id=rid))
        try:
            response = await call_next(request)
        finally:
            _current.reset(token)
        response.headers["X-Request-Id"] = rid
        return response
