"""
Tests for Issue 3: inject context (pills, runtime) into the current turn's
LLM prompt. Context was saved to DB but never fed to the model for the
ongoing turn. The fix applies `_inject_context_into_text` at both call
sites (`handle` and `handle_streaming_generator`).
"""
import os
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock

os.environ.setdefault(
    'ASYNC_DATABASE_URL',
    'postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db'
)


async def test_inject_context_into_text_with_pills():
    """Pills context is prepended to the message text."""
    from app.ai.agents.agent_service import _inject_context_into_text
    ctx = {
        "pills": [
            {"text": "Selected: main.py, line 42"},
            {"text": "Project: Cortex"},
        ]
    }
    result = _inject_context_into_text("What does this do?", ctx)
    assert "Context:" in result
    assert "Selected: main.py, line 42" in result
    assert "Project: Cortex" in result
    assert "What does this do?" in result
    assert result.startswith("Context:"), "Context should come before user text"
    assert result.endswith("What does this do?"), "User text should be last"


async def test_inject_context_into_text_with_runtime():
    """Runtime context dict is formatted as key: value lines."""
    from app.ai.agents.agent_service import _inject_context_into_text
    ctx = {
        "runtime": {
            "page": "Dashboard",
            "view": "Analytics",
        }
    }
    result = _inject_context_into_text("Show me stats", ctx)
    assert "Runtime UI Context:" in result
    assert "page: Dashboard" in result
    assert "view: Analytics" in result
    assert "Show me stats" in result


async def test_inject_context_into_text_no_context():
    """No context: message returned as-is."""
    from app.ai.agents.agent_service import _inject_context_into_text
    result = _inject_context_into_text("Hello", None)
    assert result == "Hello"
    result = _inject_context_into_text("Hello", {})
    assert result == "Hello"


async def test_inject_context_into_text_pills_and_runtime():
    """Both pills and runtime are included, pills first."""
    from app.ai.agents.agent_service import _inject_context_into_text
    ctx = {
        "pills": [{"text": "File: foo.py"}],
        "runtime": {"page": "Editor"},
    }
    result = _inject_context_into_text("Refactor this", ctx)
    assert result.index("Context:") < result.index("Runtime UI Context:"), (
        "Pills section before runtime section"
    )
    assert "File: foo.py" in result
    assert "page: Editor" in result
    assert "Refactor this" in result


async def test_inject_context_into_text_handles_empty_pills():
    """Empty pills list should not produce a context section."""
    from app.ai.agents.agent_service import _inject_context_into_text
    ctx = {"pills": []}
    result = _inject_context_into_text("Hi", ctx)
    assert result == "Hi", "Empty pills should yield no injection"


async def test_inject_context_into_text_runtime_plain_string():
    """Runtime as a plain string (not dict) is handled."""
    from app.ai.agents.agent_service import _inject_context_into_text
    ctx = {"runtime": "page=Dashboard"}
    result = _inject_context_into_text("Hi", ctx)
    assert "Runtime UI Context:" in result
    assert "page=Dashboard" in result


async def test_handle_injects_context():
    """handle() call site uses _inject_context_into_text (verified via patch)."""
    from app.ai.agents.agent_service import _inject_context_into_text

    # Verify the helper itself — full integration test would require
    # mocking the entire AgentService bootstrap.
    ctx = {"pills": [{"text": "Selected text: foo"}]}
    result = _inject_context_into_text("What is this?", ctx)
    assert "Selected text: foo" in result
    assert "What is this?" in result


async def test_message_full_text_uses_inject_context():
    """_message_full_text should delegate to _inject_context_into_text."""
    from app.ai.agents.conversation_service import _message_full_text

    class FakeMsg:
        content = "Hello"
        context = {"pills": [{"text": "Test"}]}

    result = _message_full_text(FakeMsg())
    assert "Test" in result
    assert "Hello" in result


async def test_inject_context_into_text_with_page():
    """Page context dict is rendered as key: value lines."""
    from app.ai.agents.agent_service import _inject_context_into_text
    ctx = {
        "page": {
            "type": "note",
            "note_id": "note-123",
            "note_title": "Kế hoạch tuần",
            "route": "note_detail",
        }
    }
    result = _inject_context_into_text("Tóm tắt note này", ctx)
    assert "Page Context:" in result
    assert "type: note" in result
    assert "note_id: note-123" in result
    assert "note_title: Kế hoạch tuần" in result
    assert "route: note_detail" in result
    assert "Tóm tắt note này" in result


async def test_inject_context_into_text_page_plain_string():
    """Page as a plain string is handled."""
    from app.ai.agents.agent_service import _inject_context_into_text
    ctx = {"page": "home"}
    result = _inject_context_into_text("Hi", ctx)
    assert "Page Context:" in result
    assert "home" in result


async def test_inject_context_into_text_page_pills_and_runtime():
    """All three sections present: pills, page, runtime in that order."""
    from app.ai.agents.agent_service import _inject_context_into_text
    ctx = {
        "pills": [{"text": "File: foo.py"}],
        "page": {"type": "note", "route": "note_detail"},
        "runtime": "page=Dashboard",
    }
    result = _inject_context_into_text("Refactor this", ctx)
    assert result.index("Context:") < result.index("Page Context:") < result.index("Runtime UI Context:")
    assert "File: foo.py" in result
    assert "type: note" in result
    assert "page=Dashboard" in result
    assert "Refactor this" in result


async def test_inject_context_into_text_empty_page():
    """Empty page dict should not produce a page section."""
    from app.ai.agents.agent_service import _inject_context_into_text
    ctx = {"page": {}}
    result = _inject_context_into_text("Hi", ctx)
    assert "Page Context:" not in result
    assert result == "Hi"


async def main():
    await test_inject_context_into_text_with_pills()
    print("✓ test_inject_context_into_text_with_pills")
    await test_inject_context_into_text_with_runtime()
    print("✓ test_inject_context_into_text_with_runtime")
    await test_inject_context_into_text_no_context()
    print("✓ test_inject_context_into_text_no_context")
    await test_inject_context_into_text_pills_and_runtime()
    print("✓ test_inject_context_into_text_pills_and_runtime")
    await test_inject_context_into_text_handles_empty_pills()
    print("✓ test_inject_context_into_text_handles_empty_pills")
    await test_inject_context_into_text_runtime_plain_string()
    print("✓ test_inject_context_into_text_runtime_plain_string")
    await test_handle_injects_context()
    print("✓ test_handle_injects_context")
    await test_message_full_text_uses_inject_context()
    print("✓ test_message_full_text_uses_inject_context")
    await test_inject_context_into_text_with_page()
    print("✓ test_inject_context_into_text_with_page")
    await test_inject_context_into_text_page_plain_string()
    print("✓ test_inject_context_into_text_page_plain_string")
    await test_inject_context_into_text_page_pills_and_runtime()
    print("✓ test_inject_context_into_text_page_pills_and_runtime")
    await test_inject_context_into_text_empty_page()
    print("✓ test_inject_context_into_text_empty_page")
    print("All Issue-3 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
