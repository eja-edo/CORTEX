"""
Tests for get_recent_messages_by_token_budget (Bước 4 + Mục 1 fix).

Run: python -m pytest test_token_budget_history.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from types import SimpleNamespace

import pytest

from app.ai.agents.conversation_store import ConversationStore


def _fake_message(role: str, content: str | None = None, tool_name: str | None = None,
                   tool_output: dict | None = None, created_at_idx: int = 0) -> SimpleNamespace:
    """Create a fake DB record-like object mimicking AgentMessage."""
    return SimpleNamespace(
        id=uuid4(),
        role=role,
        content=content,
        tool_name=tool_name,
        tool_input=tool_output,
        tool_output=tool_output,
        tool_call_id=None,
        turn_id=None,
        context=None,
        created_at_idx=created_at_idx,
    )


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_keeps_newest_messages_within_budget(mock_db):
    """
    10 messages (newest = idx 9, oldest = idx 0).
    First 3 newest (idx 9, 8, 7) fit within budget.
    Message idx 6 would exceed it.
    """
    store = ConversationStore(mock_db)

    # 10 messages with ascending idx (0=oldest, 9=newest)
    all_msgs = [_fake_message("user", f"m{i}", created_at_idx=i) for i in range(10)]
    db_order = list(reversed(all_msgs))  # newest first: idx 9, 8, 7 ...

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = db_order
    mock_db.execute.return_value = mock_result

    # Determine actual tokens for newest 3 messages
    from app.utils.tokens import estimate_message_tokens
    budget = sum(estimate_message_tokens("user", f"m{i}") for i in range(9, 6, -1))
    # Add a tiny margin so 3 newest fit but 4th doesn't
    budget += 1

    result = await store.get_recent_messages_by_token_budget(
            conversation_id=uuid4(), max_tokens=budget
        )

    assert len(result) == 3, f"Expected 3 messages, got {len(result)}"
    # oldest -> newest: idx 7, 8, 9
    assert [m.created_at_idx for m in result] == [7, 8, 9], (
        f"Expected [7, 8, 9], got {[m.created_at_idx for m in result]}"
    )


@pytest.mark.asyncio
async def test_single_message_exceeds_budget(mock_db):
    """Single message exceeding max_tokens is still kept (edge case)."""
    store = ConversationStore(mock_db)

    long_msg = _fake_message("user", "A" * 50000, created_at_idx=0)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [long_msg]
    mock_db.execute.return_value = mock_result

    result = await store.get_recent_messages_by_token_budget(
        conversation_id=uuid4(), max_tokens=100
    )

    assert len(result) == 1, f"Expected 1 message (edge case), got {len(result)}"
    assert result[0].created_at_idx == 0


@pytest.mark.asyncio
async def test_fallback_on_exception(mock_db):
    """If DB raises, fallback to get_recent_messages(limit=10)."""
    store = ConversationStore(mock_db)

    mock_db.execute.side_effect = Exception("DB error")

    with patch.object(store, 'get_recent_messages', return_value=["fallback"]) as mock_fallback:
        result = await store.get_recent_messages_by_token_budget(
            conversation_id=uuid4(), max_tokens=100
        )
        assert result == ["fallback"]
        mock_fallback.assert_called_once()


@pytest.mark.asyncio
async def test_empty_conversation(mock_db):
    """Empty conversation returns empty list."""
    store = ConversationStore(mock_db)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    result = await store.get_recent_messages_by_token_budget(
        conversation_id=uuid4(), max_tokens=100
    )
    assert result == []


@pytest.mark.asyncio
async def test_result_order_is_oldest_to_newest(mock_db):
    """Returned messages are always in chronological order."""
    store = ConversationStore(mock_db)

    all_msgs = [_fake_message("user", "x", created_at_idx=i) for i in range(10)]
    db_order = list(reversed(all_msgs))

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = db_order
    mock_db.execute.return_value = mock_result

    result = await store.get_recent_messages_by_token_budget(
        conversation_id=uuid4(), max_tokens=9999
    )

    assert len(result) == 10
    # Must be ascending chronological order
    indices = [m.created_at_idx for m in result]
    assert indices == sorted(indices), f"Result not in chronological order: {indices}"
