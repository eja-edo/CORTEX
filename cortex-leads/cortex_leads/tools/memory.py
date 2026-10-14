"""record_facts: the runner's write path for what the model learned (DESIGN N5). Internal effect,
not offered to the model as a callable; the runner invokes it with evidence already mapped to
message ids server-side."""
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.context import RunContext
from cortex_leads.core.envelope import ErrorCode, ErrorInfo, ToolResult
from cortex_leads.memory.service import MemoryError, record_fact
from cortex_leads.tools.registry import ToolArgs, ToolRegistry, ToolSpec

MAX_AI_FACTS = 5


class FactIn(ToolArgs):
    kind: str = Field(min_length=1, max_length=50)
    value: dict[str, Any]
    evidence_msg_ids: list[UUID] = Field(default_factory=list, max_length=10)


class RecordFactsArgs(ToolArgs):
    facts: list[FactIn] = Field(max_length=50)


def _make_record_facts(clock: Callable[[], datetime]):
    async def record_facts(ctx: RunContext, session: AsyncSession, a: RecordFactsArgs) -> ToolResult:
        if ctx.scope.conversation_id is None:
            return ToolResult(status="error", error=ErrorInfo(code=ErrorCode.PERMISSION_DENIED))
        if len(a.facts) > MAX_AI_FACTS:  # one run cannot flood the memory
            return ToolResult(status="error", note="TOO_MANY_FACTS",
                              error=ErrorInfo(code=ErrorCode.INVALID_ARGS, fields=["facts"]))
        data: dict[str, Any] = {"recorded": 0, "rejected": [], "promised_active": False,
                                "outcome_candidate": False}
        for f in a.facts:
            try:
                async with session.begin_nested():  # one bad fact must not poison the others
                    fact = await record_fact(
                        session, conversation_id=ctx.scope.conversation_id, kind=f.kind,
                        value=f.value, evidence_msg_ids=f.evidence_msg_ids, source=ctx.actor,
                        now=clock())
            except MemoryError as e:
                data["rejected"].append(e.code)
                continue
            data["recorded"] += 1
            data["promised_active"] |= fact.kind == "promised_date" and fact.status == "active"
            data["outcome_candidate"] |= fact.kind == "outcome" and fact.status == "candidate"
        return ToolResult(status="ok", data=data)

    return record_facts


def register_memory(reg: ToolRegistry, clock: Callable[[], datetime] | None = None) -> None:
    reg.register(ToolSpec(
        "record_facts", "Ghi các điều khách đã nói rõ vào trí nhớ, kèm bằng chứng là tin của khách.",
        RecordFactsArgs, "internal", "v1", _make_record_facts(clock or (lambda: datetime.now(UTC)))))
