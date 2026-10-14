import hashlib
import hmac
import json
import time

import httpx
import pytest

from bridges.twenty.app import create_app, map_event
from cortex_leads.ingest.signing import verify as ingest_verify

SECRET = "twenty-secret"
STAGES = {"WON": "won", "LOST": "lost", "MEETING": "booked"}
OPP = {"event": "opportunity.updated", "timestamp": "2026-10-12T03:00:00Z", "data": {
    "id": "opp-1", "stage": "WON", "amount": {"amountMicros": 2_500_000_000_000, "currencyCode": "VND"},
    "pointOfContact": {"cortexRef": "conn_abc:psid_1001", "phones": {"primaryPhoneNumber": "901234567",
                                                                       "primaryPhoneCallingCode": "+84"}}}}


def signed(payload: dict, *, secret: str = SECRET, ts: int | None = None) -> tuple[bytes, dict]:
    body, ts = json.dumps(payload).encode(), str(ts or int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return body, {"X-Twenty-Webhook-Signature": sig, "X-Twenty-Webhook-Timestamp": ts}


def build():
    posted: list[httpx.Request] = []

    def sink(req: httpx.Request) -> httpx.Response:
        posted.append(req)
        return httpx.Response(202, json={"results": [{"status": "accepted"}]})

    env = {"TWENTY_WEBHOOK_SECRET": SECRET, "TWENTY_STAGE_MAP": json.dumps(STAGES), "CL_INGEST_URL": "http://core/ingest",
           "CL_CONNECTOR_ID": "conn_abc", "CL_CONNECTOR_SECRET": "cs"}
    app = create_app(httpx.AsyncClient(transport=httpx.MockTransport(sink)), env=env)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bridge"), posted


def test_map_stage_and_cortex_ref() -> None:
    ev = map_event(OPP, STAGES)
    assert ev["deal"] == {"external_id": "twenty:opp-1", "status": "won", "currency": "VND", "value": 2_500_000.0}
    assert ev["contact"] == {"ref": {"connector_id": "conn_abc", "external_id": "psid_1001"}}  # ref beats phone
    assert ev["external_id"] == "twenty:opp-1:won" and ev["type"] == "deal.updated"


def test_phone_fallback_and_skips() -> None:
    person = {"phones": {"primaryPhoneNumber": "901234567", "primaryPhoneCallingCode": "+84"}}
    ev = map_event({"data": {"id": "o", "stage": "MEETING", "pointOfContact": person}}, STAGES)
    assert ev["contact"] == {"phone": "+84901234567"} and ev["deal"]["status"] == "booked"
    assert map_event({"data": {"id": "o", "stage": "NEW", "pointOfContact": person}}, STAGES) == "stage_not_mapped"
    assert map_event({"data": {"id": "o", "stage": "WON"}}, STAGES) == "no_contact"


async def test_signature_required() -> None:
    client, posted = build()
    body, hdr = signed(OPP, secret="wrong")
    assert (await client.post("/webhook", content=body, headers=hdr)).status_code == 401
    body, hdr = signed(OPP, ts=int(time.time()) - 3600)  # replay
    assert (await client.post("/webhook", content=body, headers=hdr)).status_code == 401
    assert (await client.post("/webhook", content=body)).status_code == 401
    assert posted == []


async def test_valid_webhook_posts_signed_deal_event() -> None:
    client, posted = build()
    body, hdr = signed(OPP, ts=int(time.time() * 1000))  # ms timestamps accepted
    r = await client.post("/webhook", content=body, headers=hdr)
    assert r.status_code == 200 and r.json()["accepted"] == 1
    (req,) = posted
    ts = int(req.headers["X-Timestamp"])
    from datetime import UTC, datetime
    assert ingest_verify(b"cs", ts, req.content, req.headers["X-Signature"], now=datetime.now(UTC), max_skew_s=60)
    assert json.loads(req.content)["events"][0]["deal"]["status"] == "won"


@pytest.mark.parametrize("payload", [{**OPP, "event": "person.created"},
                                     {**OPP, "data": {**OPP["data"], "stage": "NEW"}}])
async def test_ignored_events_post_nothing(payload) -> None:
    client, posted = build()
    body, hdr = signed(payload)
    assert (await client.post("/webhook", content=body, headers=hdr)).json().get("skipped")
    assert posted == []
