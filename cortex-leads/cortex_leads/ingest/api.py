"""POST /ingest/v1/events — the single entrance for bridges (DESIGN §5.2)."""
import json
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select

from cortex_leads.config import get_settings
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.ingest.format import Event, EventEnvelope
from cortex_leads.ingest.normalize import apply_event_detailed, claim_event
from cortex_leads.ingest.signing import verify

router = APIRouter()
MAX_BODY_BYTES = 5_000_000


def get_now() -> datetime:
    return datetime.now(UTC)


def _err(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())[:500]


@router.post("/v1/events", status_code=202)
async def ingest_events(request: Request, now: datetime = Depends(get_now)) -> dict[str, Any]:
    settings = get_settings()
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "body too large")
    cid = request.headers.get("X-Connector-Id", "")
    sig = request.headers.get("X-Signature", "")
    try:
        ts = int(request.headers.get("X-Timestamp", ""))
    except ValueError:
        raise HTTPException(401, "invalid signature") from None
    async with system_session() as s:
        connector = (await s.execute(select(m.Connector).where(m.Connector.id == cid))).scalar_one_or_none()
    # Same 401 for unknown connector / bad signature / skew: no oracle for connector ids.
    secret = Fernet(settings.CONNECTOR_SECRET_KEY).decrypt(connector.secret_enc) if connector else b""
    if connector is None or not verify(secret, ts, body, sig, now=now,
                                       max_skew_s=settings.INGEST_MAX_SKEW_S):
        raise HTTPException(401, "invalid signature")
    if connector.status != "active":  # per-connector kill switch (DESIGN §5.2)
        raise HTTPException(403, "connector disabled")
    try:
        raw = json.loads(body)
        if isinstance(raw, dict) and isinstance(raw.get("events"), list) \
                and len(raw["events"]) > settings.INGEST_MAX_BATCH:
            raise HTTPException(413, "batch too large")
        envelope = EventEnvelope.model_validate(raw)
    except (ValueError, ValidationError) as e:
        raise HTTPException(400, f"invalid envelope: {str(e)[:300]}") from None

    results: list[dict[str, Any]] = []
    async with tenant_session(connector.tenant_id) as session:
        for item in envelope.events:
            ext = item.get("external_id") if isinstance(item, dict) else None
            try:
                event = Event.model_validate(item)
            except ValidationError as e:
                error = _err(e)
                if isinstance(ext, str) and ext:
                    await claim_event(session, connector, ext, str(item.get("type")), item,
                                      "rejected", error)
                results.append({"external_id": ext, "status": "rejected", "error": error})
                continue
            status, error = await apply_event_detailed(session, connector, event, now)
            results.append({"external_id": event.external_id, "status": status, "error": error})
    return {"results": results}
