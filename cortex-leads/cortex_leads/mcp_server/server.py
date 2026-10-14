"""Read-only MCP stdio server for the human builder (DESIGN §5.9).
Every call goes through the ToolRegistry with a read-only allowlist and effect ceiling, so no write
tool exists here to expose. PII is redacted inside the server (registry tools / list_drafts)."""
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from sqlalchemy import select

from cortex_leads.core.context import RunContext, Scope, SystemPrincipal
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.privacy.redact import redact
from cortex_leads.tools.registry import ToolRegistry, default_registry

READ_ALLOWLIST = frozenset({"read_messages", "lookup_catalog", "list_dropped_leads"})  # never draft_followup


class ReadOnlyHandlers:
    def __init__(self, tenant_id: UUID, sandbox_id: UUID, *, registry: ToolRegistry | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.tenant_id, self.sandbox_id = tenant_id, sandbox_id
        self.registry = registry or default_registry(clock)

    def _ctx(self, conversation_id: UUID | None = None) -> RunContext:
        return RunContext(run_id=uuid7(), tenant_id=self.tenant_id, sandbox_id=self.sandbox_id,
                          profile="mcp", profile_version=0, principal=SystemPrincipal("mcp"),
                          scope=Scope(conversation_id=conversation_id))

    async def _call(self, name: str, args: dict[str, Any], conversation_id: UUID | None = None
                    ) -> dict[str, Any]:
        async with tenant_session(self.tenant_id) as s:
            res = await self.registry.execute(self._ctx(conversation_id), s, name, args,
                                              allowlist=READ_ALLOWLIST, effect_ceiling="read")
        return res.model_dump(mode="json", exclude_none=True)

    async def list_dropped_leads(self, silent_hours: int = 24, limit: int = 20) -> dict[str, Any]:
        """Open conversations where the customer wrote last and nobody replied for N hours."""
        return await self._call("list_dropped_leads", {"silent_hours": silent_hours, "limit": limit})

    async def read_conversation(self, conversation_id: str, last_n: int = 10) -> dict[str, Any]:
        """Latest messages of a conversation with phone, email and names masked."""
        try:
            cid = UUID(conversation_id)
        except ValueError:
            return {"status": "error", "note": "conversation_id must be a UUID"}
        return await self._call("read_messages", {"last_n": last_n}, cid)

    async def lookup_catalog(self, query: str, category: str | None = None) -> dict[str, Any]:
        """Look up an active catalog item by code or name."""
        return await self._call("lookup_catalog", {"query": query, "category": category})

    async def list_drafts(self, status: str = "proposed", limit: int = 20) -> dict[str, Any]:
        """Drafts written by the AI, text redacted. Read-only: approving happens in the review UI."""
        async with tenant_session(self.tenant_id) as s:
            rows = (await s.execute(
                select(m.Draft, m.Contact.display_name)
                .join(m.Conversation, m.Conversation.id == m.Draft.conversation_id)
                .join(m.Contact, m.Contact.id == m.Conversation.contact_id)
                .where(m.Draft.tenant_id == self.tenant_id, m.Draft.sandbox_id == self.sandbox_id,
                       m.Draft.status == status)
                .order_by(m.Draft.created_at.desc()).limit(max(1, min(limit, 50))))).all()
        drafts = [{"draft_id": str(d.id), "conversation_id": str(d.conversation_id),
                   "status": d.status, "reason_code": d.reason_code,
                   "created_at": d.created_at.isoformat(),
                   "text": redact(d.text, [name] if name else []).text} for d, name in rows]
        return {"status": "ok", "data": {"drafts": drafts},
                **({} if drafts else {"note": "Không có nháp nào ở trạng thái này."})}


def build_server(handlers: ReadOnlyHandlers) -> MCPServer:
    server = MCPServer("cortex-leads")
    for fn in (handlers.list_dropped_leads, handlers.read_conversation, handlers.lookup_catalog,
               handlers.list_drafts):
        server.add_tool(fn, name=fn.__name__, description=fn.__doc__)
    return server


def main() -> None:
    handlers = ReadOnlyHandlers(UUID(os.environ["CL_MCP_TENANT_ID"]),
                                UUID(os.environ["CL_MCP_SANDBOX_ID"]),
                                clock=lambda: datetime.now(UTC))
    build_server(handlers).run("stdio")
