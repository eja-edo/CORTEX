"""Manual execution mode — the turn loop pauses before executing any tool
call and waits for `POST .../tool-calls/resolve` (see `AgentService.
_run_tool_loop`'s manual-mode guard and `resume_after_tool_decisions`).

Runs against the real dev Postgres with a throwaway isolated user (same
convention as `test_procedure_create_command.py`) and the real
`ToolRegistry`/`CommandRegistry` execution path — a real `get_today` call
really runs once approved. Only the model gateway is stubbed
(`agent_service._model_client`): a live LLM's tool-calling judgment isn't
what this test needs to control, and a live call can't reliably prove a
tool was *not* executed before approval — that has to be deterministic.
"""

from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.ai.agents.provider_types import ProviderStreamChunk, ToolCall
from app.models import AgentConversation, AgentMessage, AgentPendingToolCall, User

pytestmark = pytest.mark.asyncio


class _FakeModelClient:
    """Replaces `agent_service._model_client` for the duration of a test.
    Each entry in `batches` is the list of chunks one `.stream()` call
    yields, consumed in order — one batch per model turn."""

    def __init__(self, batches):
        self._batches = list(batches)
        self.call_count = 0

    async def stream(self, messages, gen_config, tools=None, preferred_model=None):
        batch = self._batches[self.call_count]
        self.call_count += 1
        for chunk in batch:
            yield chunk


@pytest_asyncio.fixture
async def manual_conv():
    from app.database_async import make_async_sessionmaker
    from tests.integration.isolated_user import ensure_isolated_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
        user = (await db.execute(select(User).where(User.id == uid))).scalar_one()

        conv = AgentConversation(user_id=uid, execution_mode="manual")
        db.add(conv)
        await db.flush()
        conv_id = conv.id
        await db.commit()

        yield uid, user, conv_id

        await db.execute(text("DELETE FROM agent_pending_tool_calls WHERE conversation_id = :c"), {"c": str(conv_id)})
        await db.execute(text("DELETE FROM agent_messages WHERE conversation_id = :c"), {"c": str(conv_id)})
        await db.execute(text("DELETE FROM agent_conversations WHERE id = :c"), {"c": str(conv_id)})
        await db.commit()
    await engine.dispose()


def _patch_model_client(monkeypatch, batches):
    from app.ai.agents import agent_service as agent_service_module

    fake = _FakeModelClient(batches)
    monkeypatch.setattr(agent_service_module, "_model_client", fake)
    return fake


def _patch_registry_spy(monkeypatch):
    from app.ai.agents.tool_registry import get_tool_registry

    registry = get_tool_registry()
    original_execute = registry.execute
    calls: list[str] = []

    async def _spy_execute(name, args, ctx):
        calls.append(name)
        return await original_execute(name, args, ctx)

    monkeypatch.setattr(registry, "execute", _spy_execute)
    return calls


async def test_manual_mode_pauses_before_executing_tool(manual_conv, monkeypatch):
    uid, user, conv_id = manual_conv
    calls = _patch_registry_spy(monkeypatch)
    _patch_model_client(monkeypatch, [
        [ProviderStreamChunk(tool_calls=[ToolCall(id="tc1", name="get_today", args={})])],
    ])

    from app.ai.agents.agent_service import AgentService
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        service = AgentService(user=user, db=db)
        events = [ev async for ev in service.handle_streaming_generator(
            message="hôm nay có gì cần làm", conversation_id=conv_id,
        )]
    await engine.dispose()

    assert calls == [], "manual mode must not execute the tool before approval"
    assert not any(e.get("event") == "tool_result" for e in events)
    assert not any(e.get("event") == "done" for e in events)

    awaiting = [e for e in events if e.get("event") == "awaiting_approval"]
    assert len(awaiting) == 1, events
    pending = awaiting[0]["pending"]
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "get_today"

    engine2, session_maker2 = make_async_sessionmaker()
    async with session_maker2() as db:
        rows = (await db.execute(
            select(AgentPendingToolCall).where(AgentPendingToolCall.conversation_id == conv_id)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].tool_name == "get_today"
        assert rows[0].tool_call_id == "tc1"
    await engine2.dispose()


async def test_approve_executes_tool_and_continues_turn(manual_conv, monkeypatch):
    uid, user, conv_id = manual_conv
    calls = _patch_registry_spy(monkeypatch)
    _patch_model_client(monkeypatch, [
        [ProviderStreamChunk(tool_calls=[ToolCall(id="tc1", name="get_today", args={})])],
        [ProviderStreamChunk(content="Đã xong.")],
    ])

    from app.ai.agents.agent_service import AgentService
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        service = AgentService(user=user, db=db)
        pause_events = [ev async for ev in service.handle_streaming_generator(
            message="hôm nay có gì cần làm", conversation_id=conv_id,
        )]
    await engine.dispose()

    awaiting = next(e for e in pause_events if e.get("event") == "awaiting_approval")
    turn_id = UUID(awaiting["turn_id"])
    pending_id = UUID(awaiting["pending"][0]["id"])

    engine2, session_maker2 = make_async_sessionmaker()
    async with session_maker2() as db:
        service = AgentService(user=user, db=db)
        resume_events = [ev async for ev in service.resume_after_tool_decisions(
            conversation_id=conv_id, turn_id=turn_id,
            decisions=[{"pending_id": pending_id, "approved": True}],
        )]
    await engine2.dispose()

    assert calls == ["get_today"], "approval must execute the tool exactly once"
    assert any(e.get("event") == "tool_result" and e.get("tool_name") == "get_today" for e in resume_events)
    assert any(e.get("event") == "done" for e in resume_events)

    engine3, session_maker3 = make_async_sessionmaker()
    async with session_maker3() as db:
        pending_left = (await db.execute(
            select(AgentPendingToolCall).where(AgentPendingToolCall.conversation_id == conv_id)
        )).scalars().all()
        assert pending_left == []

        tool_msg = (await db.execute(
            select(AgentMessage).where(
                AgentMessage.conversation_id == conv_id,
                AgentMessage.role == "tool",
                AgentMessage.tool_call_id == "tc1",
            )
        )).scalar_one()
        assert tool_msg.tool_name == "get_today"
        assert tool_msg.tool_output.get("success") is True
    await engine3.dispose()


async def test_reject_records_rejection_and_does_not_execute(manual_conv, monkeypatch):
    uid, user, conv_id = manual_conv
    calls = _patch_registry_spy(monkeypatch)
    _patch_model_client(monkeypatch, [
        [ProviderStreamChunk(tool_calls=[ToolCall(id="tc1", name="get_today", args={})])],
        [ProviderStreamChunk(content="Được rồi, mình không làm nữa.")],
    ])

    from app.ai.agents.agent_service import AgentService
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        service = AgentService(user=user, db=db)
        pause_events = [ev async for ev in service.handle_streaming_generator(
            message="hôm nay có gì cần làm", conversation_id=conv_id,
        )]
    await engine.dispose()

    awaiting = next(e for e in pause_events if e.get("event") == "awaiting_approval")
    turn_id = UUID(awaiting["turn_id"])
    pending_id = UUID(awaiting["pending"][0]["id"])

    engine2, session_maker2 = make_async_sessionmaker()
    async with session_maker2() as db:
        service = AgentService(user=user, db=db)
        resume_events = [ev async for ev in service.resume_after_tool_decisions(
            conversation_id=conv_id, turn_id=turn_id,
            decisions=[{"pending_id": pending_id, "approved": False}],
        )]
    await engine2.dispose()

    assert calls == [], "rejecting a pending call must never execute it"
    assert any(e.get("event") == "tool_result" and e.get("success") is False for e in resume_events)
    assert any(e.get("event") == "done" for e in resume_events)

    engine3, session_maker3 = make_async_sessionmaker()
    async with session_maker3() as db:
        tool_msg = (await db.execute(
            select(AgentMessage).where(
                AgentMessage.conversation_id == conv_id,
                AgentMessage.role == "tool",
                AgentMessage.tool_call_id == "tc1",
            )
        )).scalar_one()
        assert tool_msg.tool_output.get("rejected_by_user") is True
    await engine3.dispose()
