"""Twenty CRM webhook -> signed `deal.updated` to the ingest API.
Run: uvicorn --factory bridges.twenty.app:create_app. Env: TWENTY_WEBHOOK_SECRET, TWENTY_STAGE_MAP
(JSON, e.g. {"WON":"won","LOST":"lost","MEETING":"booked"}), CL_INGEST_URL, CL_CONNECTOR_ID, CL_CONNECTOR_SECRET.
Twenty signs `{timestamp}:{raw body}` with HMAC-SHA256 (hex) in X-Twenty-Webhook-Signature /
X-Twenty-Webhook-Timestamp (docs.twenty.com/developers/extend/webhooks). ASSUMED, not in the docs:
the timestamp unit (s or ms), and that `data` carries the linked person as `pointOfContact`."""
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

from bridges.pancake.run import post_events


def verify(secret: str, ts: str, body: bytes, sig: str, now: float) -> bool:
    t = float(ts) / 1000 if float(ts) > 1e11 else float(ts)
    mac = hmac.new(secret.encode(), ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return abs(now - t) <= 300 and hmac.compare_digest(mac, sig)


def map_event(payload: dict[str, Any], stage_map: dict[str, str]) -> dict[str, Any] | str:
    """A deal.updated event, or the reason it was skipped (a string)."""
    data = payload.get("data") or {}
    status = stage_map.get(str(data.get("stage") or ""))
    if status is None:
        return "stage_not_mapped"
    person = data.get("pointOfContact") or {}
    ref = str(person.get("cortexRef") or data.get("cortexRef") or "")  # "<connector_id>:<external_id>"
    phone = (person.get("phones") or {}).get("primaryPhoneNumber")
    if ":" in ref:
        contact: dict[str, Any] = {"ref": dict(zip(("connector_id", "external_id"), ref.split(":", 1)))}
    elif phone:
        contact = {"phone": (person["phones"].get("primaryPhoneCallingCode") or "") + phone}
    else:
        return "no_contact"
    amount = data.get("amount") or {}
    deal: dict[str, Any] = {"external_id": f"twenty:{data['id']}", "status": status, "currency": amount.get("currencyCode") or "VND"}
    if amount.get("amountMicros") is not None:
        deal["value"] = int(amount["amountMicros"]) / 1_000_000
    return {"type": "deal.updated", "external_id": f"twenty:{data['id']}:{status}",
            "occurred_at": payload.get("timestamp") or datetime.now(UTC).isoformat(), "contact": contact, "deal": deal}


def create_app(http: httpx.AsyncClient | None = None, *, env: dict[str, str] | None = None) -> FastAPI:
    e = env if env is not None else os.environ
    secret, ingest = e["TWENTY_WEBHOOK_SECRET"], e["CL_INGEST_URL"]
    stage_map = json.loads(e["TWENTY_STAGE_MAP"])
    app, client = FastAPI(), http or httpx.AsyncClient(timeout=30)

    @app.post("/webhook")
    async def webhook(request: Request) -> dict[str, Any]:
        body = await request.body()
        h = request.headers
        try:
            if not verify(secret, h.get("X-Twenty-Webhook-Timestamp", ""), body,
                          h.get("X-Twenty-Webhook-Signature", ""), time.time()):
                raise ValueError
        except ValueError:
            raise HTTPException(401, "invalid signature") from None
        payload = json.loads(body)
        if payload.get("event") not in ("opportunity.created", "opportunity.updated"):
            return {"skipped": "event_type"}
        ev = map_event(payload, stage_map)
        if isinstance(ev, str):
            return {"skipped": ev}
        counts = await post_events(client, ingest, e["CL_CONNECTOR_ID"], e["CL_CONNECTOR_SECRET"], [ev])
        return {"posted": ev["external_id"], **counts}

    return app
