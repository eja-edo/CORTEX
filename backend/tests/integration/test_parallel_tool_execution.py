"""End-to-end test of `ToolExecutionService.execute_tools_pass` under
`AGENT_PARALLEL_TOOL_EXECUTION` — the exact method containing the
`_exec_parallel` closure that broke in production.

Live incident: `_exec_parallel` acquired its per-call session as
`db = AsyncSessionLocal()` instead of `async with AsyncSessionLocal() as
db:`. `AsyncSessionLocal` is `_AsyncSessionLocalProxy`
(`app/database_async.py`), not a plain `async_sessionmaker` — calling it
only builds the proxy; the real `AsyncSession` only comes back from
`__aenter__()`. Every parallel tool call failed with `AttributeError:
'_AsyncSessionLocalProxy' object has no attribute 'scalars'` the moment a
handler did `async with ctx.async_db() as db: await db.scalars(...)`
(`tool_context.py`'s `async_db` context manager just yields the broken
proxy straight through). `test_parallel_tool_session_cleanup.py` covers
the *cancellation* half of this fix with a fake session and never caught
this, because a fake object doesn't know the real proxy's contract — only
a test that goes through the real `AsyncSessionLocal` catches it
(`test_database_async.py` pins the contract directly; this file pins the
consequence, running two real tool calls through the real parallel path).

Deliberately uses `list_projects` — one of the two tools that actually
failed in production — twice, to force genuine concurrent execution via
`asyncio.gather` rather than a single call that could pass by accident.
"""

from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.ai.agents.conversation_store import ConversationStore
from app.ai.agents.provider_types import ToolCall
from app.ai.agents.tool_context import ToolContext
from app.ai.agents.tool_execution_service import ToolExecutionService
from app.ai.agents.tool_registry import get_tool_registry
from app.models import AgentConversation, AgentMessage
from tests.integration.isolated_user import ensure_isolated_user


@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        user_id = await ensure_isolated_user(db)
        yield db, user_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_two_parallel_tool_calls_both_succeed(async_db, monkeypatch):
    db, user_id = async_db
    monkeypatch.setattr(
        "app.ai.agents.tool_execution_service.settings.AGENT_PARALLEL_TOOL_EXECUTION", True
    )

    store = ConversationStore(db)
    conv = await store.get_or_create_conversation(user_id=user_id)
    await db.commit()

    try:
        ctx = ToolContext(user_id=user_id, async_db=db)
        service = ToolExecutionService(user=None, db=db, store=store, registry=get_tool_registry())
        tool_calls = [
            ToolCall(id="tc-1", name="list_projects", args={}),
            ToolCall(id="tc-2", name="list_projects", args={}),
        ]

        tool_result_messages, exec_results, should_break, reply_text, _ = (
            await service.execute_tools_pass(
                tool_calls=tool_calls,
                conv=conv,
                ctx=ctx,
                turn=1,
                tool_call_counts={},
                source_id_counter=0,
                project_id=None,
            )
        )

        assert len(exec_results) == 2
        for _, tool_name, result in exec_results:
            assert tool_name == "list_projects"
            # The regression: a broken session made every call return
            # {"error": "'_AsyncSessionLocalProxy' object has no attribute
            # 'scalars'", "success": False} instead of ever touching the DB.
            assert result.get("success") is True, result
            assert "scalars" not in str(result.get("error", ""))

        assert len(tool_result_messages) == 2
        assert should_break is False
    finally:
        await db.execute(delete(AgentMessage).where(AgentMessage.conversation_id == conv.id))
        await db.execute(delete(AgentConversation).where(AgentConversation.id == conv.id))
        await db.commit()
