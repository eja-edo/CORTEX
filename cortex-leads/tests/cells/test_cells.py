"""WP25: multi-cell. The id names the cell; the router forwards untouched; a cell refuses what is not its own."""
import json
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from cortex_leads.cells.router import FORWARD, create_router
from cortex_leads.core.ids import DEFAULT_CELL, cell_of, new_connector_id
from cortex_leads.ingest.signing import sign


def test_ids_name_their_cell_and_old_ids_belong_to_the_default():
    assert cell_of(new_connector_id()) == DEFAULT_CELL and "-" not in new_connector_id()
    assert cell_of(new_connector_id("c1")) == DEFAULT_CELL  # the default stays in the old shape
    cid = new_connector_id("c2")
    assert cid.startswith("conn_c2-") and cell_of(cid) == "c2"
    assert cell_of("conn_abc") == DEFAULT_CELL  # a legacy / test id
    for junk in ("", "x", "conn_", "conn_C2-abc", "conn_c2-", "conn_c2-ABC", "conn_c2-abc/../d"):
        assert cell_of(junk) is None, junk


class Cell:
    """A stand-in for a cell's ingest endpoint: records exactly what reached it."""

    def __init__(self, status=202, body=None):
        self.seen, self.status, self.body = [], status, body or {"results": []}
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self))

    def __call__(self, req):
        self.seen.append((str(req.url), dict(req.headers), req.content))
        return httpx.Response(self.status, json=self.body)


def router(cells: dict[str, Cell]):
    transport = httpx.MockTransport(lambda req: next(c for n, c in cells.items() if str(req.url).startswith(f"http://{n}"))(req))
    app = create_router({n: f"http://{n}" for n in cells}, client=httpx.AsyncClient(transport=transport))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://router")


def signed(cid, body=b'{"format":"cortex.event/1","events":[]}'):
    ts = int(datetime.now(UTC).timestamp())
    return body, {"X-Connector-Id": cid, "X-Timestamp": str(ts), "X-Signature": sign(b"secret", ts, body),
                  "Content-Type": "application/json"}


async def test_a_batch_goes_to_the_cell_its_connector_names_byte_for_byte():
    c1, c2 = Cell(), Cell(body={"results": [{"external_id": "e1", "status": "accepted"}]})
    async with router({"c1": c1, "c2": c2}) as r:
        cid = new_connector_id("c2")
        body, headers = signed(cid)
        res = await r.post("/ingest/v1/events", content=body, headers={**headers, "Cookie": "x=1", "X-Other": "no"})
    assert res.status_code == 202 and res.json()["results"][0]["status"] == "accepted"  # the cell's own answer comes back
    assert not c1.seen
    (url, sent_headers, sent_body) = c2.seen[0]
    assert url == "http://c2/ingest/v1/events" and sent_body == body  # the signature still verifies there
    assert sent_headers["x-signature"] == headers["X-Signature"] and "cookie" not in sent_headers and "x-other" not in sent_headers
    assert set(FORWARD) >= {"x-connector-id", "x-timestamp", "x-signature"}


async def test_a_legacy_id_goes_to_the_default_cell():
    c1, c2 = Cell(), Cell()
    async with router({"c1": c1, "c2": c2}) as r:
        await r.post("/ingest/v1/events", **dict(zip(("content", "headers"), signed("conn_abc"))))
    assert len(c1.seen) == 1 and not c2.seen


@pytest.mark.parametrize("cid", ["", "garbage", "conn_c9-abc", "conn_C2-abc"])
async def test_unknown_or_malformed_ids_look_like_a_bad_signature(cid):
    c1 = Cell()
    async with router({"c1": c1}) as r:
        res = await r.post("/ingest/v1/events", **dict(zip(("content", "headers"), signed(cid))))
    assert res.status_code == 401 and not c1.seen  # a stranger learns nothing about which cells exist


async def test_a_cell_that_is_down_is_a_503_the_bridge_will_retry():
    def boom(req):
        raise httpx.ConnectError("down")
    app = create_router({"c1": "http://c1"}, client=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://router") as r:
        res = await r.post("/ingest/v1/events", **dict(zip(("content", "headers"), signed("conn_abc"))))
    assert res.status_code == 503


async def test_a_cell_error_passes_through_and_the_router_needs_the_default_cell():
    async with router({"c1": Cell(status=401, body={"detail": "invalid signature"})}) as r:
        res = await r.post("/ingest/v1/events", **dict(zip(("content", "headers"), signed("conn_abc"))))
    assert res.status_code == 401 and res.json() == {"detail": "invalid signature"}
    with pytest.raises(RuntimeError):
        create_router({"c2": "http://c2"})


async def test_a_cell_refuses_another_cells_connector_with_421(app_client):
    body, headers = signed(new_connector_id("c2"))
    res = await app_client.post("/ingest/v1/events", content=body, headers=headers)
    assert res.status_code == 421 and "cell c2" in res.json()["detail"]
    body, headers = signed("conn_unknown")
    assert (await app_client.post("/ingest/v1/events", content=body, headers=headers)).status_code == 401  # own cell: normal path
    assert json.loads(body)["format"]  # (sanity: the helper built a real envelope)
