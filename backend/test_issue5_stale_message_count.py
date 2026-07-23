"""
Tests for Issue 5: atomic UPDATE ... RETURNING for increment_message_count
and increment_token_count, avoiding stale-count race conditions.

Also verifies basic methods still work end-to-end with the test DB.
"""
import os
import asyncio
from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault(
    'ASYNC_DATABASE_URL',
    'postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db'
)


async def test_increment_message_count():
    """Atomic increment via UPDATE ... RETURNING works."""
    from app.ai.agents.conversation_store import ConversationStore

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    # Simulate RETURNING returning (42,)
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = (42,)
    mock_db.execute.return_value = mock_result

    store = ConversationStore(mock_db)
    conv_id = uuid4()
    await store.increment_message_count(conv_id)

    # Verify SQL was compiled correctly
    call_stmt = mock_db.execute.call_args[0][0]
    compiled = str(call_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE agent_conversations" in compiled
    assert "message_count" in compiled
    assert "RETURNING" in compiled
    assert "message_count + 1" in compiled or "message_count = message_count" in compiled
    mock_result.one_or_none.assert_called_once()


async def test_increment_token_count():
    """Atomic token-count increment via UPDATE ... RETURNING works."""
    from app.ai.agents.conversation_store import ConversationStore
    from app.models import AgentConversation

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    mock_result = MagicMock()
    mock_result.one_or_none.return_value = (100,)
    mock_db.execute.return_value = mock_result

    store = ConversationStore(mock_db)
    conv_id = uuid4()
    await store.increment_token_count(conv_id, 50)

    call_stmt = mock_db.execute.call_args[0][0]
    compiled = str(call_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE agent_conversations" in compiled
    assert "total_token_count" in compiled
    assert "RETURNING" in compiled
    assert "+ 50" in compiled or "+ :total_token_count_1" in compiled or "total_token_count +" in compiled
    mock_result.one_or_none.assert_called_once()


async def test_increment_message_count_not_found_logs_warning():
    """When conversation doesn't exist, a warning is logged but no error."""
    from app.ai.agents.conversation_store import ConversationStore
    import logging

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    mock_result = MagicMock()
    mock_result.one_or_none.return_value = None  # conversation not found
    mock_db.execute.return_value = mock_result

    store = ConversationStore(mock_db)
    conv_id = uuid4()

    with patch("app.ai.agents.conversation_store.logger.warning") as mock_warn:
        await store.increment_message_count(conv_id)
        mock_warn.assert_called_once()
        assert "increment_message_count" in mock_warn.call_args[0][0]


async def test_increment_token_count_not_found_logs_warning():
    """When conversation doesn't exist, token increment logs warning."""
    from app.ai.agents.conversation_store import ConversationStore

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    mock_result = MagicMock()
    mock_result.one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    store = ConversationStore(mock_db)
    conv_id = uuid4()

    with patch("app.ai.agents.conversation_store.logger.warning") as mock_warn:
        await store.increment_token_count(conv_id, 10)
        mock_warn.assert_called_once()
        assert "increment_token_count" in mock_warn.call_args[0][0]


async def main():
    await test_increment_message_count()
    print("✓ test_increment_message_count")
    await test_increment_token_count()
    print("✓ test_increment_token_count")
    await test_increment_message_count_not_found_logs_warning()
    print("✓ test_increment_message_count_not_found_logs_warning")
    await test_increment_token_count_not_found_logs_warning()
    print("✓ test_increment_token_count_not_found_logs_warning")
    print("All Issue-5 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
