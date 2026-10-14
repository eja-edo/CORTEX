"""WP8 test world: free window, outbound on, the dev skill `thu-nhanh` live, a signing mock bridge."""
import json
from datetime import datetime, timedelta

import httpx
from sqlalchemy import text, update
from wp5_support import GOOD_DRAFT, NOW, World, gateway, reply

from cortex_leads.core.context import CustomerPrincipal, RunContext, Scope, StaffPrincipal
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.ingest.signing import verify
from cortex_leads.runner.customer_run import run_job
from cortex_leads.skills.registry import promote
from cortex_leads.tools.registry import default_registry
from cortex_leads.triggers.engine import on_conversation_event

URL = "http://bridge/actions"
SECRET = "test-connector-secret"  # connector_factory default
__all__ = ["GOOD_DRAFT", "NOW", "reply"]


async def configure(w: World, owner_engine, *, now: datetime = NOW, silent_h: float = 2,
                    mode: str = "manual", outbound: bool = True, trust: str = "official") -> None:
    last = now - timedelta(hours=silent_h)
    async with tenant_session(w.t.id) as s:
        await s.execute(update(m.Message).values(occurred_at=last))
        await s.execute(update(m.Conversation).values(last_customer_at=last))
        await s.execute(update(m.Sandbox).values(send_mode=mode))
        if (await s.execute(text("select status from skill_version where name = 'thu-nhanh'"))).scalar() == "draft":
            for st in ("shadow", "live"):
                await promote(s, w.sb.id, "thu-nhanh", 1, st)
    out = json.dumps({"enabled": True, "url": URL}) if outbound else None
    async with owner_engine.begin() as c:
        await c.execute(text("update connector set trust = :t, outbound = cast(:o as jsonb) where id = :i"),
                        {"t": trust, "o": out, "i": w.cn.id})


async def sql(owner_engine, stmt: str, **params) -> None:
    async with owner_engine.begin() as c:
        await c.execute(text(stmt), params)


class Bridge:
    """Mock of a bridge's /actions: verifies the core's signature like the real one, records calls."""

    def __init__(self, answer=None, *, status: int = 200, now: datetime = NOW) -> None:
        self.calls: list[dict] = []
        self.answer = answer or {"status": "sent", "external_message_id": "mid.1"}
        self.status, self.now = status, now
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = request.content
        ok = verify(SECRET.encode(), int(request.headers["X-Cortex-Timestamp"]), body,
                    request.headers["X-Cortex-Signature"], now=self.now, max_skew_s=300)
        assert ok, "bad signature"
        self.calls.append(json.loads(body))
        return httpx.Response(self.status, json=self.answer)


async def make_job(w: World, now: datetime = NOW) -> m.FollowupJob:
    async with tenant_session(w.t.id) as s:
        conv = await s.get(m.Conversation, w.conv.id)
        jobs = await on_conversation_event(s, conv, "conversation.silent", now)
        assert jobs and jobs[0].skill_name == "thu-nhanh"
        return jobs[0]


async def run(w: World, *, now: datetime = NOW, draft: dict = GOOD_DRAFT) -> m.TriggerRun:
    job = await make_job(w, now)
    gw, _ = gateway(reply(draft))
    async with tenant_session(w.t.id) as s:
        j = await s.get(m.FollowupJob, job.id)
        return await run_job(s, j, gw, default_registry(clock=lambda: now), now)


def ctx_for(w: World, draft: m.Draft, *, staff: str | None = None) -> RunContext:
    return RunContext(
        run_id=draft.run_id or uuid7(), tenant_id=w.t.id, sandbox_id=w.sb.id, profile="customer_drafter",
        profile_version=1, scope=Scope(conversation_id=w.conv.id),
        principal=StaffPrincipal(staff) if staff else CustomerPrincipal(contact_id=w.conv.contact_id))


async def send(w: World, draft: m.Draft, *, staff: str | None = None, now: datetime = NOW,
               text_: str | None = None):
    """Call the tool the way the runner (ai) or the approve button (staff) does."""
    async with tenant_session(w.t.id) as s:
        return await default_registry(clock=lambda: now).execute(
            ctx_for(w, draft, staff=staff), s, "send_message",
            {"draft_id": str(draft.id), "text": text_}, allowlist=["send_message"],
            effect_ceiling="customer")
