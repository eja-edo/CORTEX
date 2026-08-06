"""
Context schemas for Cortex.

⚠️ 2026-08-06: Adapted from the Milestone 1.7 plan to match what the system
actually does today, not the plan's invented shape. The frontend sends a
free-form `context: dict | None` per chat request with (at most) three keys:
`pills` (list of `{"text": ..., "source": ...}`), `page` (dict), `runtime`
(dict) — see `app/ai/agents/conversation_service.py::_inject_context_into_text`.
There is no `view`/`ViewType`/`CurrentObject` contract anywhere in the
frontend payload, so this module does NOT invent one (a strict schema for
fields the frontend doesn't actually send would just raise ValidationError
on real traffic). `pills`/`page`/`runtime` are kept here as loosely-typed
passthroughs; `workspace`/`recent_notes`/`recent_schedules` are the genuinely
new, DB-sourced sections `ContextService` adds.
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ContextPill(BaseModel):
    """User-provided or system-generated context snippet (frontend `pills[]`)."""
    text: str
    source: str = Field(default="user", description="user, system, or agent")


class WorkspaceContext(BaseModel):
    """Context about the active workspace."""
    workspace_id: UUID
    workspace_name: str
    role: str = Field(..., description="owner, editor, or viewer")
    member_count: int = 0


class UnifiedContext(BaseModel):
    """
    Everything Cortex knows about "what the user is doing right now".

    `pills`/`page`/`runtime` mirror the frontend's existing context dict
    verbatim (already injected into the per-message text by
    `_inject_context_into_text` — NOT re-rendered by `to_llm_string()` below,
    to avoid duplicating the same information twice in the prompt).
    `workspace`/`recent_notes`/`recent_schedules` are new: DB-sourced,
    proactively surfaced without the LLM needing to call a search tool first.
    """
    pills: list[ContextPill] = Field(default_factory=list)
    page: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)

    workspace: Optional[WorkspaceContext] = None
    recent_notes: list[dict] = Field(default_factory=list, description="Recently edited notes")
    recent_schedules: list[dict] = Field(default_factory=list, description="Upcoming schedules (next 7 days)")

    def to_llm_string(self, max_items: int = 5) -> str:
        """
        Render only the DB-sourced sections (workspace/recent_notes/
        recent_schedules) for the system prompt. pills/page/runtime are
        deliberately excluded — they're already in the user message via
        _inject_context_into_text; rendering them again here would waste
        tokens on duplicate content instead of reducing them.
        """
        parts = []

        if self.workspace:
            parts.append(f"Current workspace: {self.workspace.workspace_name} (role: {self.workspace.role})")

        if self.recent_notes:
            notes_text = "\n".join(f"- {n.get('title', 'Untitled')}" for n in self.recent_notes[:max_items])
            parts.append(f"Recently edited notes:\n{notes_text}")

        if self.recent_schedules:
            sched_text = "\n".join(
                f"- {s.get('title', 'Untitled')} at {s.get('start_time', '?')}"
                for s in self.recent_schedules[:max_items]
            )
            parts.append(f"Upcoming schedule (next 7 days):\n{sched_text}")

        if not parts:
            return ""

        return "User context:\n" + "\n\n".join(parts)
