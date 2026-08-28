"""Integration tests for F2/M2's R5 schema work — docs/mezon-bot-plan.md §V.

Covers three things `AgentMessage.source` and `role="system"` have to get
right for the Mezon conversation to work at all:

- a system note doesn't collapse against another system note the way a
  repeated user/assistant turn does (`ConversationStore.save_message`);
- `_build_history_contents` folds a system note into the next real turn
  instead of feeding it to the LLM as a message of its own, or dropping it
  silently before the alternation state machine even sees it;
- `get_or_create_mezon_conversation` finds the one existing Mezon
  conversation instead of creating a new one every call.

Runs against the real dev Postgres on the throwaway isolated account (see
`tests/integration/isolated_user.py`) — same convention as
`test_delivery_worker.py`.
"""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.ai.agents.conversation_service import _build_history_contents
from app.ai.agents.conversation_store import ConversationStore
from app.database_async import make_async_sessionmaker
from app.models import AgentConversation, AgentMessage
from tests.integration.isolated_user import ensure_isolated_user


@pytest_asyncio.fixture
async def user_id():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
    await engine.dispose()
    return uid


@pytest_asyncio.fixture
async def async_db(user_id):
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        await db.execute(delete(AgentConversation).where(AgentConversation.user_id == user_id))
        await db.commit()
    await engine.dispose()


async def _make_conversation(db, user_id) -> AgentConversation:
    store = ConversationStore(db)
    conv = await store.get_or_create_conversation(user_id=user_id)
    await db.commit()
    return conv


class _Rec:
    """A stand-in for an `AgentMessage` row — `_build_history_contents` only
    reads these five attributes (see its `getattr` calls), so a plain
    object is enough and keeps these tests from needing a conversation at
    all for the pure-function cases."""

    def __init__(self, role, content=None, created_at=None, context=None, turn_id=None,
                 tool_name=None, tool_input=None, tool_output=None, tool_call_id=None):
        self.role = role
        self.content = content
        self.created_at = created_at or datetime.now(timezone.utc)
        self.context = context
        self.turn_id = turn_id
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.tool_output = tool_output
        self.tool_call_id = tool_call_id


@pytest.mark.asyncio
async def test_save_message_system_role_does_not_collapse(async_db, user_id):
    conv = await _make_conversation(async_db, user_id)
    store = ConversationStore(async_db)

    first = await store.save_message(conversation_id=conv.id, role="system", content="Đã nhắc: A", source="mezon")
    second = await store.save_message(conversation_id=conv.id, role="system", content="Đã nhắc: B", source="mezon")
    await async_db.commit()

    assert first is not None and second is not None
    assert first.id != second.id

    rows = (await async_db.execute(
        select(AgentMessage).where(AgentMessage.conversation_id == conv.id).order_by(AgentMessage.created_at)
    )).scalars().all()
    assert [r.content for r in rows] == ["Đã nhắc: A", "Đã nhắc: B"]
    assert all(r.source == "mezon" for r in rows)


@pytest.mark.asyncio
async def test_save_message_system_role_stores_source(async_db, user_id):
    conv = await _make_conversation(async_db, user_id)
    store = ConversationStore(async_db)

    msg = await store.save_message(conversation_id=conv.id, role="system", content="Đã nhắc: X", source="mezon")
    await async_db.commit()

    assert msg.source == "mezon"
    assert msg.role == "system"


def test_build_history_contents_folds_system_note_into_next_user_message():
    records = [
        _Rec("system", content="Đã nhắc: Task X quá hạn"),
        _Rec("user", content="sao anh không nói sớm"),
        _Rec("assistant", content="Mình đã nhắc bạn lúc nãy rồi nè"),
    ]
    messages = _build_history_contents(records)

    # The system note must not become its own Message (that path is
    # unsupported by the provider layer — see openai_provider.py) and must
    # not break user/assistant alternation.
    assert [m.role for m in messages] == ["user", "assistant"]
    assert "Đã nhắc: Task X quá hạn" in messages[0].content
    assert "sao anh không nói sớm" in messages[0].content
    assert messages[1].content.endswith("Mình đã nhắc bạn lúc nãy rồi nè") or "Mình đã nhắc" in messages[1].content


def test_build_history_contents_leading_system_note_is_not_trimmed():
    # A notification arrives before the user has ever said anything in this
    # conversation. The old leading-trim (`role != "user"`) would have
    # discarded this before the loop ever saw it.
    records = [
        _Rec("system", content="Đã nhắc: chào mừng"),
        _Rec("user", content="ê bot"),
    ]
    messages = _build_history_contents(records)

    assert len(messages) == 1
    assert messages[0].role == "user"
    assert "Đã nhắc: chào mừng" in messages[0].content
    assert "ê bot" in messages[0].content


def test_build_history_contents_dangling_system_note_is_dropped_not_erroring():
    # A notification with nothing after it in this batch (the most recent
    # thing in the conversation). It must not crash and must not surface as
    # its own message; it stays in the DB for a later call to pick up once
    # a real turn follows.
    records = [
        _Rec("user", content="hello"),
        _Rec("assistant", content="hi there"),
        _Rec("system", content="Đã nhắc: việc gì đó"),
    ]
    messages = _build_history_contents(records)

    assert [m.role for m in messages] == ["user", "assistant"]
    assert all("Đã nhắc" not in (m.content or "") for m in messages)


@pytest.mark.asyncio
async def test_get_or_create_mezon_conversation_creates_then_reuses(async_db, user_id):
    store = ConversationStore(async_db)

    first = await store.get_or_create_mezon_conversation(user_id)
    await async_db.commit()
    # No source="mezon" message exists yet, so a second call before any
    # real Mezon turn happens still can't find `first` — that's the known,
    # documented edge (see get_or_create_mezon_conversation's docstring).
    # Once a real turn is saved against it, every later call must return
    # exactly that conversation.
    await store.save_message(conversation_id=first.id, role="user", content="hi from mezon", source="mezon")
    await async_db.commit()

    second = await store.get_or_create_mezon_conversation(user_id)
    third = await store.get_or_create_mezon_conversation(user_id)

    assert second.id == first.id
    assert third.id == first.id
