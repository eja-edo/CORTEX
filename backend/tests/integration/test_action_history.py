"""
Integration tests for the `action_history` table.

The table itself is not tied to a single planning-doc milestone — it is the
PostgreSQL half of `ActionSnapshotStore`, which has existed since Milestone
1.5/1.6. What's tested here is a real gap found by exercising the chat
endpoint end to end: the table never existed, so every audit INSERT had
been silently failing since the store was written. `revert_action` still
worked because Redis carries the 24h hot path, so the failure mode was a
slowly-growing gap in history, not a broken feature — exactly the kind of
bug a broad `except Exception: logger.warning(...)` is built to hide.

Two things are checked, both found the hard way:
  1. the table has to exist with the right shape, including a **server-side**
     default for `id` — a raw `text()` INSERT never sees the ORM column's
     Python-side `default=uuid.uuid4`, so the first version of this fix
     still failed, just on a different constraint (NOT NULL on `id` instead
     of "relation does not exist").
  2. a failing (or merely happening) audit write must never touch the
     caller's own session/objects — that coupling is what turned a missing
     table into a 500 on an otherwise-successful chat turn.
"""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.ai.agents.action_snapshot_store import (
    ActionSnapshot,
    get_snapshot_store,
    set_audit_session_factory,
)
from app.ai.agents.tool_context import ToolContext
from app.models import ActionHistory, Task
from app.services.tasks import TaskService

TEST_USER_ID = UUID("73552833-a6de-40a1-bb69-6e034ca75460")
MARKER = "[test-action-history]"


@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    # ActionSnapshotStore's PG write always opens its own session, bound to
    # whichever loop it runs on. pytest-asyncio hands every test a fresh
    # loop, but the module-level singleton stays bound to whichever loop
    # first touched it — so its writes intermittently vanish into the same
    # broad `except Exception: logger.warning(...)` that hid the missing
    # table in the first place. Point the audit write at this test's own
    # engine instead, the same session-factory-override fix used elsewhere.
    set_audit_session_factory(session_maker)
    async with session_maker() as db:
        yield db
        set_audit_session_factory(None)
        await db.execute(delete(ActionHistory).where(ActionHistory.tool_name.like(f"{MARKER}%")))
        await db.execute(delete(Task).where(Task.title.startswith(MARKER)))
        await db.commit()
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _reset_event_bus_between_tests():
    from app.events.event_bus import reset_event_bus

    reset_event_bus()
    yield
    import app.events.event_bus as event_bus_module
    if event_bus_module._event_bus is not None:
        try:
            await event_bus_module._event_bus.disconnect()
        except Exception:
            pass
        event_bus_module._event_bus = None


def _snapshot(action_id: str | None = None, conversation_id: str | None = None) -> ActionSnapshot:
    return ActionSnapshot(
        tool_name=f"{MARKER}.tool",
        user_id=str(TEST_USER_ID),
        conversation_id=conversation_id,
        snapshot={"note": "probe"},
        action_id=action_id or str(uuid4()),
    )


# ============================================================================
# The table actually receives rows (the bug: it silently never did)
# ============================================================================

@pytest.mark.asyncio
async def test_save_writes_a_row_with_no_conversation(async_db):
    """The common case for an AI tool call outside a conversation context
    (conversation_id=None) — the exact shape that first exposed the missing
    `id` server default, since `conversation_id` being NULL was never the
    problem; `id` being unset was."""
    snapshot = _snapshot(conversation_id=None)

    await get_snapshot_store().save(snapshot, db_session=async_db)

    row = (await async_db.execute(
        select(ActionHistory).where(ActionHistory.action_id == snapshot.action_id)
    )).scalar_one()
    assert row.id is not None  # the server default actually fired
    assert row.user_id == TEST_USER_ID
    assert row.conversation_id is None
    assert row.tool_name == snapshot.tool_name
    assert row.action_type == "snapshot"
    assert row.before_state == {"note": "probe"}
    assert row.is_reverted is False
    assert row.reverted_at is None


@pytest.mark.asyncio
async def test_id_has_a_server_side_default(async_db):
    """The specific regression: a Python-side `Column(default=...)` never
    fires for a raw SQL INSERT, only through the ORM's session.add(). This
    asserts the fix at the level that actually matters — the database itself
    supplies the value, independent of which code path writes the row."""
    result = (await async_db.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'action_history' AND column_name = 'id'"
        )
    )).scalar_one()
    assert result is not None and "gen_random_uuid" in result


@pytest.mark.asyncio
async def test_save_is_idempotent_on_duplicate_action_id(async_db):
    """`ON CONFLICT DO NOTHING` needs the UNIQUE constraint on action_id to
    have a target to resolve against — without it the statement would raise
    instead of silently no-op on a retry."""
    snapshot = _snapshot()

    await get_snapshot_store().save(snapshot, db_session=async_db)
    await get_snapshot_store().save(snapshot, db_session=async_db)  # must not raise

    rows = (await async_db.execute(
        select(ActionHistory).where(ActionHistory.action_id == snapshot.action_id)
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_mark_reverted_updates_the_row(async_db):
    snapshot = _snapshot()
    await get_snapshot_store().save(snapshot, db_session=async_db)

    ok = await get_snapshot_store().mark_reverted(
        user_id=str(TEST_USER_ID), action_id=snapshot.action_id, db_session=async_db
    )
    assert ok is True

    row = (await async_db.execute(
        select(ActionHistory).where(ActionHistory.action_id == snapshot.action_id)
    )).scalar_one()
    assert row.is_reverted is True
    assert row.reverted_at is not None


@pytest.mark.asyncio
async def test_conversation_id_survives_the_conversation_being_deleted(async_db):
    """SET NULL, not CASCADE: the audit record that a command ran has to
    outlive the conversation it happened in — deleting a conversation must
    not erase the fact that something was done during it."""
    from app.models import AgentConversation

    conversation = AgentConversation(user_id=TEST_USER_ID, title=f"{MARKER} conv")
    async_db.add(conversation)
    await async_db.commit()
    await async_db.refresh(conversation)
    conversation_id = conversation.id

    snapshot = _snapshot(conversation_id=str(conversation_id))
    await get_snapshot_store().save(snapshot, db_session=async_db)

    await async_db.delete(conversation)
    await async_db.commit()

    row = (await async_db.execute(
        select(ActionHistory).where(ActionHistory.action_id == snapshot.action_id)
    )).scalar_one()
    assert row.conversation_id is None
    assert row.tool_name == snapshot.tool_name  # the row itself is untouched


# ============================================================================
# End to end through the real command path
# ============================================================================

@pytest_asyncio.fixture
async def ctx(async_db):
    context = ToolContext(user_id=TEST_USER_ID, async_db=async_db)
    yield context
    context.close()


@pytest.mark.asyncio
async def test_a_real_command_leaves_a_matching_audit_row(async_db, ctx):
    """Not a synthetic ActionSnapshot — task.create through CommandRegistry,
    the exact path a chat turn takes."""
    from app.ai.tools.create_task import create_task_handler

    result = await create_task_handler({"title": f"{MARKER} real task"}, ctx)

    row = (await async_db.execute(
        select(ActionHistory).where(ActionHistory.action_id == result["action_id"])
    )).scalar_one()
    assert row.tool_name == "task.create"
    assert row.user_id == TEST_USER_ID


@pytest.mark.asyncio
async def test_reverting_a_real_command_marks_the_audit_row(async_db, ctx):
    from app.ai.tools.create_task import create_task_handler
    from app.ai.tools.revert_action import revert_action_handler

    created = await create_task_handler({"title": f"{MARKER} to revert"}, ctx)
    revert_result = await revert_action_handler({"action_id": created["action_id"]}, ctx)
    assert revert_result["success"] is True

    row = (await async_db.execute(
        select(ActionHistory).where(ActionHistory.action_id == created["action_id"])
    )).scalar_one()
    assert row.is_reverted is True


# ============================================================================
# The write must never break the caller
# ============================================================================

@pytest.mark.asyncio
async def test_snapshot_save_does_not_touch_the_callers_session(async_db):
    """The bug that made the missing table a 500 instead of a quiet gap:
    `save()`'s PG write used to run on the *caller's* session and roll it
    back on failure, expiring every ORM object that session held. A live
    conversation object read right after would then raise MissingGreenlet.

    The audit write now runs on its own session unconditionally, so the
    caller's objects survive regardless of whether the write succeeds —
    verified here with a real ORM object the caller still holds afterwards.
    """
    from app.models import AgentConversation

    conversation = AgentConversation(user_id=TEST_USER_ID, title=f"{MARKER} isolation")
    async_db.add(conversation)
    await async_db.commit()
    await async_db.refresh(conversation)
    conversation_id = conversation.id

    await get_snapshot_store().save(
        ActionSnapshot(
            tool_name=f"{MARKER}.isolation",
            user_id=str(TEST_USER_ID),
            conversation_id=str(conversation_id),
            snapshot={"task_id": str(uuid4())},
            action_id=str(uuid4()),
        ),
        db_session=async_db,
    )

    # The access that used to raise MissingGreenlet after a failed audit write.
    assert conversation.id == conversation_id
    assert conversation.title == f"{MARKER} isolation"

    await async_db.execute(delete(AgentConversation).where(AgentConversation.id == conversation_id))
    await async_db.commit()
