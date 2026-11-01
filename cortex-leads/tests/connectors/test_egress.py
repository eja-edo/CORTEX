"""WP32: a webhook address is called only if it is https, on the list, without credentials, and resolves to public addresses."""
import pytest

from cortex_leads.config import get_settings
from cortex_leads.connectors import egress
from cortex_leads.connectors.egress import EgressError, check_webhook, ensure_callable

PUBLIC = ["93.184.216.34"]


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    monkeypatch.delenv("CL_WEBHOOK_ALLOW_HOSTS", raising=False)
    monkeypatch.delenv("CL_WEBHOOK_ALLOW_LOCAL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def code(url: str) -> str:
    with pytest.raises(EgressError) as e:
        check_webhook(url)
    return e.value.code


def test_the_mezon_webhook_is_accepted():
    assert check_webhook("https://webhook.mezon.ai/webhooks/123/abc.def") == "webhook.mezon.ai"


@pytest.mark.parametrize("url,why", [
    ("http://webhook.mezon.ai/x", "BAD_SCHEME"),
    ("ftp://webhook.mezon.ai/x", "BAD_SCHEME"),
    ("https://169.254.169.254/latest/meta-data", "HOST_NOT_ALLOWED"),
    ("https://10.0.0.5/admin", "HOST_NOT_ALLOWED"),
    ("https://localhost/x", "HOST_NOT_ALLOWED"),
    ("https://evil.example/x", "HOST_NOT_ALLOWED"),
    ("https://webhook.mezon.ai.evil.example/x", "HOST_NOT_ALLOWED"),
    ("https://webhook.mezon.ai@evil.example/x", "BAD_ADDRESS"),  # the host is evil.example; also a login in the address
    ("https://user:pw@webhook.mezon.ai/x", "BAD_ADDRESS"),
    ("https://webhook.mezon.ai:8443/x", "BAD_ADDRESS"),
    ("", "BAD_SCHEME"),
])
def test_everything_else_is_refused_with_a_reason(url, why):
    assert code(url) == why


def test_http_localhost_is_only_for_development(monkeypatch):
    assert code("http://127.0.0.1:8301/hook") == "BAD_SCHEME"
    monkeypatch.setenv("CL_WEBHOOK_ALLOW_LOCAL", "true")
    get_settings.cache_clear()
    assert check_webhook("http://127.0.0.1:8301/hook") == "127.0.0.1"
    assert code("http://10.0.0.5/x") == "BAD_SCHEME"  # development opens localhost, nothing else


def test_the_list_is_configurable(monkeypatch):
    monkeypatch.setenv("CL_WEBHOOK_ALLOW_HOSTS", "webhook.mezon.ai, hooks.example.vn")
    get_settings.cache_clear()
    assert check_webhook("https://hooks.example.vn/x") == "hooks.example.vn"


async def test_a_name_that_resolves_inside_is_refused_even_if_listed(monkeypatch):
    async def inside(host):
        return ["93.184.216.34", "10.0.0.7"]  # one public, one private: refused (rebinding)

    monkeypatch.setattr(egress, "resolve_host", inside)
    with pytest.raises(EgressError) as e:
        await ensure_callable("https://webhook.mezon.ai/x")
    assert e.value.code == "PRIVATE_ADDRESS"


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "10.1.2.3", "192.168.0.9", "::1", "fd00::1"])
async def test_every_private_kind_of_address_is_refused(monkeypatch, ip):
    async def only(host):
        return [ip]

    monkeypatch.setattr(egress, "resolve_host", only)
    with pytest.raises(EgressError):
        await ensure_callable("https://webhook.mezon.ai/x")


async def test_a_public_name_passes(monkeypatch):
    async def ok(host):
        return PUBLIC

    monkeypatch.setattr(egress, "resolve_host", ok)
    await ensure_callable("https://webhook.mezon.ai/x")


async def test_a_name_that_does_not_resolve_is_refused(monkeypatch):
    async def gone(host):
        raise OSError("no such host")

    monkeypatch.setattr(egress, "resolve_host", gone)
    with pytest.raises(EgressError) as e:
        await ensure_callable("https://webhook.mezon.ai/x")
    assert e.value.code == "BAD_ADDRESS"
