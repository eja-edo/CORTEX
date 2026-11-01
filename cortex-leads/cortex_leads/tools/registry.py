# port từ backend/app/commands/registry.py (chỉ thứ tự pipeline) và
# backend/app/ai/agents/tool_registry.py::_sanitize_args (che args trước khi ghi log)
"""Tool registry. Pipeline order: allowlist -> effect ceiling -> validate -> run -> audit.
Tenant / actor / scope come from RunContext only (DESIGN A3); tool args forbid extra keys, so an
LLM that passes `tenant_id` gets INVALID_ARGS."""
import logging
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.context import RunContext
from cortex_leads.core.envelope import BlockedCode, ErrorCode, ErrorInfo, ToolResult, Violation
from cortex_leads.core.errors import CortexError, TenantScopeError
from cortex_leads.db.models import ActionLog
from cortex_leads.privacy.redact import redact
from cortex_leads.tools.empty import empty_note, is_empty

log = logging.getLogger(__name__)

Effect = Literal["read", "internal", "customer"]
_RANK = {"read": 0, "internal": 1, "customer": 2}
_FREE_TEXT_KEYS = {"text", "edited_text", "message", "content", "body"}


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


Handler = Callable[[RunContext, AsyncSession, Any], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str  # <= 2 sentences
    input_model: type[BaseModel]
    effect: Effect
    tier: str
    handler: Handler
    taints: bool = False  # its result is untrusted outside data: after it, this run may not write (DESIGN §5.8)


def mask_args(args: Any, depth: int = 0) -> Any:
    """Free text is dropped, other strings lose PII and are truncated, before action_log."""
    if depth > 4:
        return "[MAX_DEPTH]"
    if isinstance(args, dict):
        return {k: "[REDACTED]" if k in _FREE_TEXT_KEYS else mask_args(v, depth + 1)
                for k, v in args.items()}
    if isinstance(args, list):
        return [mask_args(v, depth + 1) for v in args]
    if isinstance(args, str):
        return redact(args[:200]).text
    return args


TAINT_MEMORY = 2048  # runs remembered; a run is minutes long, so this is far more than enough


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._tainted: OrderedDict[UUID, None] = OrderedDict()

    def register(self, spec: ToolSpec) -> None:
        if spec.effect == "customer" and spec.name != "send_message":  # DESIGN A9: one path only
            raise CortexError(f"tool {spec.name!r}: only send_message may have effect 'customer'")
        if len([s for s in re.split(r"[.!?]+(?:\s|$)", spec.description.strip()) if s]) > 2:
            raise CortexError(f"tool {spec.name!r}: description must be at most 2 sentences")
        if spec.name in self._tools:
            raise CortexError(f"tool {spec.name!r} already registered")
        self._tools[spec.name] = spec

    def specs_for(self, allowlist: Collection[str]) -> list[ToolSpec]:
        return [s for n, s in self._tools.items() if n in allowlist]

    def openai_schemas(self, allowlist: Collection[str]) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {
            "name": s.name, "description": s.description,
            "parameters": s.input_model.model_json_schema()}} for s in self.specs_for(allowlist)]

    async def execute(
        self, ctx: RunContext, session: AsyncSession, name: str, raw_args: dict[str, Any], *,
        allowlist: Collection[str], effect_ceiling: Effect,
        idempotency_key: str | None = None,
    ) -> ToolResult:
        spec = self._tools.get(name)
        if name not in allowlist:
            return _blocked(BlockedCode.NOT_ALLOWED, f"tool {name!r} is not in the allowlist")
        if spec is None:
            return ToolResult(status="error", error=ErrorInfo(code=ErrorCode.NOT_FOUND))
        if _RANK[spec.effect] > _RANK[effect_ceiling]:
            return _blocked(BlockedCode.EFFECT_CEILING, f"{spec.effect} > {effect_ceiling}")
        if spec.effect != "read" and ctx.run_id in self._tainted:  # it read outside data: no writes after that
            return _blocked(BlockedCode.NOT_ALLOWED, "tainted_by_external_data")
        try:
            args = spec.input_model.model_validate(raw_args)
        except ValidationError as e:
            fields = sorted({".".join(str(p) for p in err["loc"]) or "?" for err in e.errors()})
            return ToolResult(
                status="error", error=ErrorInfo(code=ErrorCode.INVALID_ARGS, retryable=True,
                                                fields=fields),
                next_step="Sửa các trường lỗi rồi gọi lại.")
        # Defence in depth for A3: the session must be scoped to the same tenant as the context.
        scoped = (await session.execute(text("select current_setting('app.tenant_id', true)"))).scalar()
        if scoped != str(ctx.tenant_id):
            raise TenantScopeError(f"session tenant {scoped!r} != context tenant {ctx.tenant_id}")

        action_id = uuid5(NAMESPACE_URL, f"{ctx.run_id}:{name}:{idempotency_key}") \
            if idempotency_key else None
        if spec.effect != "read" and action_id and (prior := await _replay(session, action_id)):
            return prior

        try:
            async with session.begin_nested():  # a failing handler must not poison the txn
                result = await spec.handler(ctx, session, args)
        except Exception:
            log.exception("tool %s failed", name)
            result = ToolResult(status="error", error=ErrorInfo(code=ErrorCode.INTERNAL))
        if spec.taints and result.status == "ok":
            self._tainted[ctx.run_id] = None
            while len(self._tainted) > TAINT_MEMORY:
                self._tainted.popitem(last=False)
        if result.status == "ok" and is_empty(result.data) and not result.note:
            result = result.model_copy(update={"note": empty_note(f"{name} không có kết quả")})
        if spec.effect != "read":
            result = await _audit(ctx, session, spec, raw_args, result, action_id)
        return result


def _blocked(code: BlockedCode, detail: str) -> ToolResult:
    return ToolResult(status="blocked", violations=[Violation(code=code, detail=detail)])


async def _replay(session: AsyncSession, action_id: UUID) -> ToolResult | None:
    row = (await session.execute(
        select(ActionLog.evidence).where(ActionLog.action_id == action_id).limit(1))).scalar()
    if not row:
        return None
    return ToolResult.model_validate(row["result"]).model_copy(update={"replayed": True})


async def _audit(ctx: RunContext, session: AsyncSession, spec: ToolSpec, raw_args: dict[str, Any],
                 result: ToolResult, action_id: UUID | None) -> ToolResult:
    from cortex_leads.core.ids import uuid7

    action_id = action_id or result.action_id or uuid7()
    result = result.model_copy(update={"action_id": action_id})
    session.add(ActionLog(
        tenant_id=ctx.tenant_id, action_id=action_id, actor=ctx.actor, tool=spec.name,
        args_masked=mask_args(raw_args), status=result.status,
        evidence={"conversation_id": str(ctx.scope.conversation_id), "run_id": str(ctx.run_id),
                  "result": result.model_dump(mode="json")}))
    await session.flush()
    return result


def default_registry(clock: Callable[[], Any] | None = None) -> ToolRegistry:
    from cortex_leads.tools.v0 import register_v0

    reg = ToolRegistry()
    register_v0(reg, clock)
    from cortex_leads.tools.booking import register_booking
    from cortex_leads.tools.memory import register_memory
    from cortex_leads.tools.send import register_send

    register_memory(reg, clock)
    register_send(reg, clock)
    register_booking(reg, clock)
    from cortex_leads.tools.external import register_external

    register_external(reg)
    return reg
