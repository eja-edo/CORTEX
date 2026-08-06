"""Unit tests for Milestone 1.7 — Context schemas."""

from uuid import uuid4

from app.context.schemas import ContextPill, UnifiedContext, WorkspaceContext


def test_context_pill_defaults():
    pill = ContextPill(text="Working on CS homework")
    assert pill.source == "user"


def test_workspace_context():
    ws = WorkspaceContext(workspace_id=uuid4(), workspace_name="My Workspace", role="editor")
    assert ws.member_count == 0


def test_unified_context_defaults_are_empty():
    ctx = UnifiedContext()
    assert ctx.pills == []
    assert ctx.page == {}
    assert ctx.runtime == {}
    assert ctx.workspace is None
    assert ctx.recent_notes == []
    assert ctx.recent_schedules == []


def test_to_llm_string_empty_context_returns_empty_string():
    ctx = UnifiedContext()
    assert ctx.to_llm_string() == ""


def test_to_llm_string_does_not_render_pills_page_runtime():
    """pills/page/runtime are already injected per-message elsewhere
    (_inject_context_into_text) — to_llm_string() must not duplicate them."""
    ctx = UnifiedContext(
        pills=[ContextPill(text="I'm working on project X")],
        page={"url": "/notes/123"},
        runtime={"device": "mobile"},
    )
    rendered = ctx.to_llm_string()
    assert rendered == ""
    assert "project X" not in rendered
    assert "mobile" not in rendered


def test_to_llm_string_includes_workspace():
    ctx = UnifiedContext(workspace=WorkspaceContext(workspace_id=uuid4(), workspace_name="Team Alpha", role="owner"))
    rendered = ctx.to_llm_string()
    assert "Team Alpha" in rendered
    assert "owner" in rendered


def test_to_llm_string_includes_recent_notes():
    ctx = UnifiedContext(recent_notes=[{"id": "1", "title": "Meeting notes"}])
    rendered = ctx.to_llm_string()
    assert "Meeting notes" in rendered
    assert "Recently edited notes" in rendered


def test_to_llm_string_includes_upcoming_schedules():
    ctx = UnifiedContext(recent_schedules=[{"id": "1", "title": "Standup", "start_time": "2026-08-07T09:00:00+00:00"}])
    rendered = ctx.to_llm_string()
    assert "Standup" in rendered
    assert "Upcoming schedule" in rendered


def test_to_llm_string_respects_max_items():
    ctx = UnifiedContext(recent_notes=[{"id": str(i), "title": f"Note {i}"} for i in range(10)])
    rendered = ctx.to_llm_string(max_items=3)
    assert "Note 0" in rendered
    assert "Note 2" in rendered
    assert "Note 3" not in rendered
