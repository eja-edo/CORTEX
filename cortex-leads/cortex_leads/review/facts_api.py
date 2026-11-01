"""Staff API for contact memory and conversation outcomes (DESIGN N5). Same auth as review/api.py;
every call is audited because fact values contain customer words."""
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.memory import service as mem
from cortex_leads.review.auth import Caller, require

router = APIRouter()
STAFF = require("staff", "owner")


class FactBody(BaseModel):
    kind: str
    value: dict[str, Any]


class OutcomeBody(BaseModel):
    status: Literal["booked", "won", "lost", "cancelled", "reopen"]


class OffchannelBody(BaseModel):
    channel: Literal["phone", "zalo_personal", "in_person"]


def _ref(c: Caller) -> str:
    return c.staff_ref or c.role


def _audit(s: AsyncSession, c: Caller, tool: str, **evidence: Any) -> None:
    s.add(m.ActionLog(tenant_id=c.tenant_id, action_id=uuid7(), actor=f"staff:{_ref(c)}",
                      tool=tool, args_masked={}, status="ok", evidence=evidence))


def _out(f: m.ContactFact) -> dict[str, Any]:
    return {"id": str(f.id), "conversation_id": str(f.conversation_id), "kind": f.kind,
            "value": f.value, "source": f.source, "status": f.status,
            "created_at": wire(f.created_at)}


async def _guard(coro: Any) -> Any:
    try:
        return await coro
    except mem.MemoryError as e:
        raise HTTPException(404 if e.code == "NOT_FOUND" else 422, {"code": e.code}) from None


@router.get("/conversations/{conversation_id}/facts")
async def get_facts(conversation_id: UUID, include_inactive: bool = False, caller: Caller = STAFF) -> dict[str, Any]:
    async with tenant_session(caller.tenant_id) as s:
        conv = await s.get(m.Conversation, conversation_id)
        if conv is None:
            raise HTTPException(404, "conversation not found")
        facts = await mem.list_facts(s, contact_id=conv.contact_id, include_inactive=include_inactive)
        _audit(s, caller, "review.list_facts", count=len(facts))
    return {"facts": [_out(f) for f in facts]}


@router.post("/conversations/{conversation_id}/facts")
async def add_fact(conversation_id: UUID, body: FactBody, caller: Caller = STAFF) -> dict[str, Any]:
    async with tenant_session(caller.tenant_id) as s:
        f = await _guard(mem.record_fact(
            s, conversation_id=conversation_id, kind=body.kind, value=body.value, evidence_msg_ids=[],
            source=f"staff:{_ref(caller)}", now=datetime.now(UTC)))
        _audit(s, caller, "review.add_fact", kind=body.kind)
        return _out(f)


@router.post("/conversations/{conversation_id}/outcome")
async def set_outcome(conversation_id: UUID, body: OutcomeBody, caller: Caller = STAFF) -> dict[str, Any]:
    async with tenant_session(caller.tenant_id) as s:
        conv = await _guard(mem.record_outcome(
            s, conversation_id=conversation_id, status=body.status, source=f"staff:{_ref(caller)}",
            evidence_msg_ids=[], now=datetime.now(UTC)))
        _audit(s, caller, "review.set_outcome", status=body.status)
        return {"state": conv.state}


@router.post("/conversations/{conversation_id}/offchannel")
async def set_offchannel(conversation_id: UUID, body: OffchannelBody, caller: Caller = STAFF) -> dict[str, Any]:
    async with tenant_session(caller.tenant_id) as s:
        f = await _guard(mem.mark_offchannel(
            s, conversation_id=conversation_id, channel=body.channel, staff_ref=_ref(caller),
            now=datetime.now(UTC)))
        _audit(s, caller, "review.offchannel", channel=body.channel)
        return _out(f)


@router.post("/facts/{fact_id}/{op}")
async def decide_fact(fact_id: UUID, op: Literal["confirm", "reject"], caller: Caller = STAFF) -> dict[str, Any]:
    fn = mem.confirm_fact if op == "confirm" else mem.reject_fact
    async with tenant_session(caller.tenant_id) as s:
        f = await _guard(fn(s, fact_id, staff_ref=_ref(caller), now=datetime.now(UTC)))
        _audit(s, caller, f"review.{op}_fact", kind=f.kind)
        return _out(f)


@router.get("/confirmations")
async def confirmations(caller: Caller = STAFF) -> dict[str, Any]:
    async with tenant_session(caller.tenant_id) as s:
        facts = [f for sb in (await s.execute(select(m.Sandbox.id))).scalars().all()
                 for f in await mem.pending_confirmations(s, sandbox_id=sb)]
        _audit(s, caller, "review.confirmations", count=len(facts))
    return {"facts": [_out(f) for f in sorted(facts, key=lambda f: f.created_at)]}
