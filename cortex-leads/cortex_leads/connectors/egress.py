"""Where a webhook the business typed in may be called (WP32). The address of a push target is text an operator entered, and the
worker will POST to it from inside our network: unchecked, `https://169.254.169.254/...` or `https://10.0.0.5/admin` would be
called with a recap in the body. So a target must be https, name a host from a short list (CL_WEBHOOK_ALLOW_HOSTS), carry no
credentials in the address, and resolve to public addresses only; checked when it is saved and again before every call."""
from urllib.parse import urlsplit

from cortex_leads.config import get_settings
from cortex_leads.connectors import http_readonly
from cortex_leads.core.errors import CortexError

LOCAL_HOSTS = {"localhost", "127.0.0.1"}
resolve_host = http_readonly.resolve_host  # tests replace this name


class EgressError(CortexError):
    """`.code`: BAD_SCHEME | BAD_ADDRESS | HOST_NOT_ALLOWED | PRIVATE_ADDRESS"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def allowed_hosts() -> set[str]:
    return {h.strip().lower() for h in get_settings().WEBHOOK_ALLOW_HOSTS.split(",") if h.strip()}


def check_webhook(url: str) -> str:
    """The host of a webhook address that could be called, or EgressError. No network."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    local = get_settings().WEBHOOK_ALLOW_LOCAL and host in LOCAL_HOSTS
    if parts.scheme != "https" and not (local and parts.scheme == "http"):
        raise EgressError("BAD_SCHEME")
    if not host or parts.username or parts.password or len(url) > 600:
        raise EgressError("BAD_ADDRESS")
    if not local:
        if host not in allowed_hosts():
            raise EgressError("HOST_NOT_ALLOWED")
        if parts.port not in (None, 443):
            raise EgressError("BAD_ADDRESS")
    return host


async def ensure_callable(url: str) -> None:
    """`check_webhook`, then the DNS answer: every address the name resolves to must be public."""
    host = check_webhook(url)
    if get_settings().WEBHOOK_ALLOW_LOCAL and host in LOCAL_HOSTS:
        return
    try:
        addresses = await resolve_host(host)
    except OSError:
        raise EgressError("BAD_ADDRESS") from None
    if not addresses or not all(http_readonly.is_public(a) for a in addresses):
        raise EgressError("PRIVATE_ADDRESS")
