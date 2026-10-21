"""Multi-cell front door (T2, DESIGN §5.10). A cell is a full copy of the system: its own database, its own
workers, its own tenants. Growth is adding a cell, not enlarging one.

The router is deliberately dumb: it reads ONE thing, the connector id in `X-Connector-Id` (which names its cell),
and forwards the request byte for byte, so the bridge's signature still verifies in the cell. It has no database,
no secret and no tenant data, and it never opens the body. Staff and owners reach their cell directly (one
hostname per cell); only bridges, which have one ingest URL, come through here.

    CL_CELLS='{"c1": "http://10.0.0.1:8100", "c2": "http://10.0.0.2:8100"}'
    uvicorn cortex_leads.cells.router:create_app --factory --port 8100"""
import json
import os

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

from cortex_leads.core.ids import DEFAULT_CELL, cell_of

MAX_BODY_BYTES = 5_000_000
FORWARD = ("x-connector-id", "x-timestamp", "x-signature", "content-type")  # nothing else crosses


def create_router(cells: dict[str, str], *, client: httpx.AsyncClient | None = None) -> FastAPI:
    if DEFAULT_CELL not in cells:
        raise RuntimeError(f"cells must include the default cell {DEFAULT_CELL!r} (ids minted before cells belong to it)")
    http = client or httpx.AsyncClient(follow_redirects=False)
    app = FastAPI(title="cortex-leads cell router")

    @app.post("/ingest/v1/events")
    async def route(request: Request) -> Response:
        cid = request.headers.get("X-Connector-Id", "")
        cell = cell_of(cid)
        if cell is None or cell not in cells:  # same answer as a bad signature: no map of our cells for a stranger
            raise HTTPException(401, "invalid signature")
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "body too large")
        try:
            r = await http.post(cells[cell].rstrip("/") + "/ingest/v1/events", content=body, timeout=15,
                                headers={k: v for k, v in request.headers.items() if k in FORWARD})
        except httpx.HTTPError:
            raise HTTPException(503, "cell unavailable") from None  # the bridge keeps its batch and retries
        return Response(r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", "cells": sorted(cells)}

    return app


def create_app() -> FastAPI:
    raw = os.environ.get("CL_CELLS", "")
    if not raw:
        raise RuntimeError("set CL_CELLS to a JSON object of cell -> base URL")
    return create_router(json.loads(raw))
