"""
Tests for Issue 8: remove dead code from get_or_create_conversation.

Verifies that the `conversation_id` parameter is removed, making the
method a pure "create" function as actually used.
"""
import os
import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault(
    'ASYNC_DATABASE_URL',
    'postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db'
)


async def test_get_or_create_conversation_signature():
    """get_or_create_conversation no longer accepts conversation_id."""
    import inspect
    from app.ai.agents.conversation_store import ConversationStore
    sig = inspect.signature(ConversationStore.get_or_create_conversation)
    params = list(sig.parameters.keys())
    assert "conversation_id" not in params, \
        f"conversation_id should be removed, got params={params}"
    # Should have: self, user_id, workspace_id, title
    assert "user_id" in params
    assert "workspace_id" in params


async def test_get_or_create_conversation_creates_new():
    """Method creates and returns a new conversation."""
    from app.ai.agents.conversation_store import ConversationStore
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    store = ConversationStore(mock_db)
    user_id = uuid4()
    conv = await store.get_or_create_conversation(
        user_id=user_id,
        workspace_id=uuid4(),
    )
    assert conv is not None
    assert conv.user_id == user_id
    assert mock_db.add.called


async def test_callers_dont_pass_conversation_id():
    """Both call sites pass only user_id and workspace_id."""
    import inspect
    from app.ai.agents import agent_service

    # Check handle() call site
    handle_src = inspect.getsource(agent_service.AgentService.handle)
    handle_get_or_create = False
    for line in handle_src.split("\n"):
        if "get_or_create_conversation" in line:
            handle_get_or_create = True
            assert "conversation_id" not in line, \
                f"handle() should not pass conversation_id: {line}"
    assert handle_get_or_create, "handle() should call get_or_create_conversation"

    # Check handle_streaming_generator() call site
    streaming_src = inspect.getsource(agent_service.AgentService.handle_streaming_generator)
    streaming_get_or_create = False
    for line in streaming_src.split("\n"):
        if "get_or_create_conversation" in line:
            streaming_get_or_create = True
            assert "conversation_id" not in line, \
                f"handle_streaming_generator() should not pass conversation_id: {line}"
    assert streaming_get_or_create, "handle_streaming_generator() should call get_or_create_conversation"


async def main():
    await test_get_or_create_conversation_signature()
    print("✓ test_get_or_create_conversation_signature")
    await test_get_or_create_conversation_creates_new()
    print("✓ test_get_or_create_conversation_creates_new")
    await test_callers_dont_pass_conversation_id()
    print("✓ test_callers_dont_pass_conversation_id")
    print("All Issue-8 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
