"""
Tests for Issue 6: generate conversation title in the non-streaming handle()
method, matching the existing streaming behavior.

Focuses on unit-testing _generate_conversation_title and verifying the
code change in handle() via source-level checks.
"""
import os
import asyncio

os.environ.setdefault(
    'ASYNC_DATABASE_URL',
    'postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db'
)


async def test_generate_conversation_title_success():
    """_generate_conversation_title returns a valid title."""
    import app.ai.agents.agent_service as svc
    from unittest.mock import MagicMock, AsyncMock, patch

    service = svc.AgentService.__new__(svc.AgentService)
    service.llm = MagicMock()
    service.tool_registry = MagicMock()

    mock_client = MagicMock()
    mock_client.generate = AsyncMock()
    mock_client.generate.return_value = (None, MagicMock(content="  My Test Title  "))

    with patch.object(svc, '_model_client', mock_client), \
         patch.object(svc, 'MAX_TOOL_TURNS', 1):
        title = await service._generate_conversation_title("Hello world")
        assert title == "My Test Title"


async def test_generate_conversation_title_fallback_on_failure():
    """_generate_conversation_title returns fallback on failure."""
    import app.ai.agents.agent_service as svc
    from unittest.mock import MagicMock, AsyncMock, patch

    service = svc.AgentService.__new__(svc.AgentService)
    service.llm = MagicMock()
    service.tool_registry = MagicMock()

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(side_effect=RuntimeError("API down"))

    with patch.object(svc, '_model_client', mock_client), \
         patch.object(svc, 'MAX_TOOL_TURNS', 1):
        title = await service._generate_conversation_title("Hello world test message")
        assert isinstance(title, str)
        assert len(title) > 0


async def test_generate_conversation_title_empty_response():
    """Fallback when generated title is empty."""
    import app.ai.agents.agent_service as svc
    from unittest.mock import MagicMock, AsyncMock, patch

    service = svc.AgentService.__new__(svc.AgentService)
    service.llm = MagicMock()
    service.tool_registry = MagicMock()

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=(None, MagicMock(content="")))

    with patch.object(svc, '_model_client', mock_client), \
         patch.object(svc, 'MAX_TOOL_TURNS', 1):
        title = await service._generate_conversation_title("Hello")
        assert isinstance(title, str)
        assert len(title) > 0


def test_handle_code_has_title_generation():
    """Verify handle() source contains the title generation block (Issue 6)."""
    import inspect
    from app.ai.agents.agent_service import AgentService

    source = inspect.getsource(AgentService.handle)
    assert "_generate_conversation_title" in source
    assert "generated_title" in source


async def main():
    await test_generate_conversation_title_success()
    print("✓ test_generate_conversation_title_success")
    await test_generate_conversation_title_fallback_on_failure()
    print("✓ test_generate_conversation_title_fallback_on_failure")
    await test_generate_conversation_title_empty_response()
    print("✓ test_generate_conversation_title_empty_response")
    test_handle_code_has_title_generation()
    print("✓ test_handle_code_has_title_generation")
    print("All Issue-6 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
