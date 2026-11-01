"""WP27: the built console is served by the API itself, as one origin."""
import pytest
from httpx import ASGITransport, AsyncClient

from cortex_leads.app import create_app


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<!doctype html><title>Cortex</title><div id=root></div>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("outside")
    return tmp_path


async def client(dist):
    return AsyncClient(transport=ASGITransport(app=create_app(dist)), base_url="http://test")


async def test_the_app_and_any_client_route_get_the_page_with_strict_headers(dist):
    async with await client(dist) as c:
        for path in ("/app/", "/app/inbox", "/app/inbox/0194f3a0-1111-7000-8000-000000000001", "/app/skills/new"):
            r = await c.get(path)
            assert r.status_code == 200 and "Cortex" in r.text, path
            assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"
            assert "script-src 'self'" in r.headers["content-security-policy"] and "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert (await c.get("/app", follow_redirects=False)).headers["location"] == "/app/"


async def test_assets_and_files_are_served_and_a_missing_file_is_a_404_not_the_app(dist):
    async with await client(dist) as c:
        assert (await c.get("/app/assets/app-abc123.js")).text == "console.log(1)"
        assert (await c.get("/app/favicon.svg")).text == "<svg/>"
        assert (await c.get("/app/assets/nope.js")).status_code == 404
        assert (await c.get("/app/whatever.js")).status_code == 404


async def test_nothing_outside_the_build_can_be_read(dist):
    async with await client(dist) as c:
        for path in ("/app/../secret.txt", "/app/%2e%2e/secret.txt", "/app/assets/../../secret.txt"):
            r = await c.get(path)
            assert "outside" not in r.text, path


async def test_without_a_build_the_api_still_works_and_the_ui_is_absent(tmp_path):
    async with await client(tmp_path / "missing") as c:
        assert (await c.get("/health")).json() == {"status": "ok"}
        assert (await c.get("/app/")).status_code == 404
