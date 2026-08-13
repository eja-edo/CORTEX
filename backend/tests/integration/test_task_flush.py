"""
Integration tests for the idle flush (M5) and M6 of conversation task
extraction.

Formerly `test_commitment_flush.py` — Commitment was folded into Task (see
"Xoá bỏ Commitment, gộp vào Task"): a suggested task now starts life as a
`Task` in `pending_confirm`, not a separate `Commitment` row, and there is
no `direction`/`counterparty` field anymore (only `title`, which folds a
counterparty in as context when the LLM extracts one).

**M6 is the most important test here.** It protects the most common shape
of conversation there is: *"thứ 6 tôi gửi proposal cho John"*, said in two
messages, after which the user closes the app. The 20-message threshold can
never be reached by that conversation, so without the idle flush the task is
lost permanently — silently, with nothing anywhere to indicate it.

The LLM call itself is stubbed. Everything else is the real pipeline: real
idle detection, the real L0 scan, the real advisory lock, the real prompt
builder, the real response parser, the real validator, and real rows in
Postgres.
"""

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from tests.integration.isolated_user import (
    ISOLATED_TEST_USER_ID,
    ensure_isolated_user,
)
from app.models import AgentConversation, AgentMessage, Task, TaskStatus
from app.services.task_extraction import (
    CANDIDATE_EXPIRY_DAYS,
    TaskCandidateService,
)
from app.services.task_flush_worker import IDLE_MINUTES, TaskFlushWorker
from app.services.tasks import TaskService

# NOT the seeded dev account: these tests clear the whole account to get
# a clean fixture, and that account belongs to a real person. See
# tests/integration/isolated_user.py.
TEST_USER_ID = ISOLATED_TEST_USER_ID
MARKER = "[test-2.3]"


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================================
# Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await ensure_isolated_user(db)
        yield db
        await db.execute(delete(Task).where(Task.user_id == TEST_USER_ID))
        await db.execute(
            delete(AgentMessage).where(
                AgentMessage.conversation_id.in_(
                    select(AgentConversation.id).where(
                        AgentConversation.title.startswith(MARKER)
                    )
                )
            )
        )
        await db.execute(delete(AgentConversation).where(AgentConversation.title.startswith(MARKER)))
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


@pytest.fixture
def stub_llm(monkeypatch):
    """Stub only the network call.

    Everything downstream — prompt assembly, JSON parsing, the validation
    conditions, the write — is the production path. Returns the recorded
    prompts so a test can assert the task-extraction instructions really
    were appended to the *existing* memory call rather than sent as a
    second one.
    """
    calls: list[dict] = []

    def _make(tasks: list[dict]):
        async def fake_generate(messages, config, estimated_tokens=None, **kwargs):
            calls.append({"messages": [m.content for m in messages]})

            class _Response:
                content = json.dumps({
                    "episodic_summary": "user committed to something",
                    "semantic_memories": [],
                    "title": f"{MARKER} extracted",
                    "tasks": tasks,
                })

            return "stub-model", _Response()

        import app.services.memory_extraction_service as extraction_module

        monkeypatch.setattr(extraction_module._model_client, "generate", fake_generate)
        return calls

    _make.calls = calls
    return _make


async def _make_conversation(db, title: str, messages: list[str], idle_minutes: int) -> UUID:
    """A conversation whose last activity was `idle_minutes` ago."""
    last_activity = _naive_utcnow() - timedelta(minutes=idle_minutes)

    conversation = AgentConversation(
        user_id=TEST_USER_ID,
        title=f"{MARKER} {title}",
        messages_since_last_summary=len(messages),
        tokens_since_last_summary=50,
        updated_at=last_activity,
    )
    db.add(conversation)
    await db.flush()

    for index, content in enumerate(messages):
        db.add(AgentMessage(
            conversation_id=conversation.id,
            role="user" if index % 2 == 0 else "assistant",
            content=content,
            created_at=last_activity,
        ))
    await db.commit()
    return conversation.id


# ============================================================================
# M6 — the two-message conversation
# ============================================================================

@pytest.mark.asyncio
async def test_two_message_conversation_produces_a_suggestion_after_idle(async_db, stub_llm):
    """2.3 M6 — the test that protects the most common case.

    Two messages, then the user closes the app. `messages_since_last_summary`
    is 2 and will never reach 20, so the inline trigger never fires. The idle
    flush is the only thing standing between this task and permanent loss.
    """
    stub_llm([{
        "counterparty": "John",
        "expected_action": "gửi proposal",
        "deadline": None,
        "source_quote": "thứ 6 tôi gửi proposal cho John",
    }])

    conversation_id = await _make_conversation(
        async_db,
        "two messages",
        ["thứ 6 tôi gửi proposal cho John", "Đã ghi nhận nhé."],
        idle_minutes=IDLE_MINUTES + 1,
    )

    worker = TaskFlushWorker()
    flushable = await worker.find_flushable(async_db)
    assert conversation_id in flushable, "idle conversation with an L0 signal was not picked up"

    assert await worker.flush_conversation(async_db, conversation_id) is True

    suggestions = (await async_db.execute(
        select(Task).where(Task.source_conversation_id == conversation_id)
    )).scalars().all()

    assert len(suggestions) == 1, "the task in a 2-message conversation was lost"
    suggestion = suggestions[0]
    assert suggestion.status is TaskStatus.PENDING_CONFIRM
    assert "gửi proposal" in suggestion.title
    assert "John" in suggestion.title
    # Provenance, so "where did this come from?" is answerable.
    assert suggestion.source_message_id is not None


@pytest.mark.asyncio
async def test_the_threshold_alone_would_have_lost_it(async_db):
    """The gap this milestone exists to close, stated as a test.

    The same two-message conversation is nowhere near either threshold, so
    the inline trigger is correct to do nothing — which is precisely why the
    flush has to exist.
    """
    from app.ai.agents.conversation_summarizer import ConversationSummarizer

    conversation_id = await _make_conversation(
        async_db, "below threshold",
        ["thứ 6 tôi gửi proposal cho John", "ok"],
        idle_minutes=IDLE_MINUTES + 1,
    )
    conv = await async_db.get(AgentConversation, conversation_id)

    assert conv.messages_since_last_summary < ConversationSummarizer.MESSAGE_THRESHOLD
    assert conv.tokens_since_last_summary < ConversationSummarizer.TOKEN_THRESHOLD


@pytest.mark.asyncio
async def test_flush_bypasses_the_five_message_memory_floor(async_db, stub_llm):
    """`extract_and_store` skips conversations with fewer than 5 new messages
    — right for memory, fatal for task suggestions. The flush passes 1."""
    calls = stub_llm([{
        "counterparty": "John",
        "expected_action": "gửi proposal",
        "deadline": None,
        "source_quote": "thứ 6 tôi gửi proposal cho John",
    }])

    conversation_id = await _make_conversation(
        async_db, "two messages only",
        ["thứ 6 tôi gửi proposal cho John", "ok"],
        idle_minutes=IDLE_MINUTES + 1,
    )

    assert await TaskFlushWorker().flush_conversation(async_db, conversation_id) is True
    assert calls, "the LLM was never called — the 5-message floor blocked the flush"


# ============================================================================
# The flush only fires when it should
# ============================================================================

@pytest.mark.asyncio
async def test_a_conversation_without_an_l0_signal_is_left_alone(async_db):
    """No signal → wait for the 20-message threshold as before. Memory is not
    in a hurry, and this is what keeps the added cost near zero."""
    conversation_id = await _make_conversation(
        async_db, "no signal",
        ["cho tôi xem note hôm qua", "đây rồi bạn"],
        idle_minutes=IDLE_MINUTES + 1,
    )

    flushable = await TaskFlushWorker().find_flushable(async_db)
    assert conversation_id not in flushable


@pytest.mark.asyncio
async def test_an_active_conversation_is_not_flushed(async_db):
    """Firing mid-conversation would extract a half-finished thought and
    spend a call that the inline trigger is about to make anyway."""
    conversation_id = await _make_conversation(
        async_db, "still typing",
        ["thứ 6 tôi gửi proposal cho John"],
        idle_minutes=1,
    )

    flushable = await TaskFlushWorker().find_flushable(async_db)
    assert conversation_id not in flushable


@pytest.mark.asyncio
async def test_a_conversation_with_nothing_new_is_not_flushed(async_db):
    """Already extracted — `messages_since_last_summary` is 0."""
    conversation_id = await _make_conversation(
        async_db, "already done",
        ["thứ 6 tôi gửi proposal cho John"],
        idle_minutes=IDLE_MINUTES + 1,
    )
    conv = await async_db.get(AgentConversation, conversation_id)
    conv.messages_since_last_summary = 0
    await async_db.commit()

    flushable = await TaskFlushWorker().find_flushable(async_db)
    assert conversation_id not in flushable


@pytest.mark.asyncio
async def test_flush_yields_to_the_inline_trigger_holding_the_lock(async_db, stub_llm):
    """M5's requirement: the flush takes the **same** advisory lock as
    `MemoryTriggerService`. Without it the two would race on one conversation
    and both call the LLM — double cost, duplicate suggestions."""
    stub_llm([])
    conversation_id = await _make_conversation(
        async_db, "contended",
        ["thứ 6 tôi gửi proposal cho John", "ok"],
        idle_minutes=IDLE_MINUTES + 1,
    )

    # A second session takes the lock first, standing in for an in-flight
    # inline extraction.
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as holder:
        lock_key = conversation_id.hex
        acquired = (await holder.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))").bindparams(k=lock_key)
        )).scalar()
        assert acquired is True

        flushed = await TaskFlushWorker().flush_conversation(async_db, conversation_id)
        assert flushed is False, "the flush ignored the lock and raced the inline trigger"

        await holder.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_the_task_extraction_rides_on_the_existing_memory_call(async_db, stub_llm):
    """M4: no separate job and no second round trip — the task-extraction
    instructions are appended to the prompt that was already being sent."""
    calls = stub_llm([])
    conversation_id = await _make_conversation(
        async_db, "one call",
        ["thứ 6 tôi gửi proposal cho John", "ok"],
        idle_minutes=IDLE_MINUTES + 1,
    )

    await TaskFlushWorker().flush_conversation(async_db, conversation_id)

    assert len(calls) == 1, "task extraction made its own LLM call"
    prompt = "\n".join(calls[0]["messages"])
    assert "TWO CONDITIONS" in prompt             # the task task...
    assert "episodic_summary" in prompt           # ...on the memory call


# ============================================================================
# Suggestion lifecycle (M3)
# ============================================================================

@pytest.mark.asyncio
async def test_a_rejected_suggestion_is_never_proposed_again(async_db, stub_llm):
    """Without this the same suggestion resurfaces after every extraction —
    notification fatigue in a different costume, and the fastest route to the
    user switching the feature off."""
    proposal = {
        "counterparty": "John",
        "expected_action": "gửi proposal",
        "deadline": None,
        "source_quote": "thứ 6 tôi gửi proposal cho John",
    }
    stub_llm([proposal])

    first = await _make_conversation(
        async_db, "first ask",
        ["thứ 6 tôi gửi proposal cho John", "ok"],
        idle_minutes=IDLE_MINUTES + 1,
    )
    await TaskFlushWorker().flush_conversation(async_db, first)

    suggestion = (await async_db.execute(
        select(Task).where(Task.source_conversation_id == first)
    )).scalar_one()
    await TaskService(async_db).reject_task(suggestion.id, TEST_USER_ID)

    # The user says the same thing again in a new conversation.
    second = await _make_conversation(
        async_db, "second ask",
        ["thứ 6 tôi gửi proposal cho John", "ok"],
        idle_minutes=IDLE_MINUTES + 1,
    )
    await TaskFlushWorker().flush_conversation(async_db, second)

    reproposed = (await async_db.execute(
        select(Task).where(Task.source_conversation_id == second)
    )).scalars().all()
    assert reproposed == [], "a rejected task was proposed again"


@pytest.mark.asyncio
async def test_an_open_suggestion_is_not_duplicated(async_db, stub_llm):
    """Asking twice is asking twice, whichever extraction pass produced it."""
    proposal = {
        "counterparty": "John",
        "expected_action": "gửi proposal",
        "deadline": None,
        "source_quote": "thứ 6 tôi gửi proposal cho John",
    }
    stub_llm([proposal])

    for title in ("dup one", "dup two"):
        conversation_id = await _make_conversation(
            async_db, title,
            ["thứ 6 tôi gửi proposal cho John", "ok"],
            idle_minutes=IDLE_MINUTES + 1,
        )
        await TaskFlushWorker().flush_conversation(async_db, conversation_id)

    suggestions = (await async_db.execute(
        select(Task).where(
            Task.user_id == TEST_USER_ID,
            Task.title.like("%gửi proposal%"),
        )
    )).scalars().all()
    assert len(suggestions) == 1


@pytest.mark.asyncio
async def test_unanswered_suggestions_expire_after_seven_days(async_db, stub_llm):
    stub_llm([])
    service = TaskService(async_db)
    from app.schemas import TaskCreate

    stale = await service.create_task(
        TaskCreate(
            title=f"{MARKER} bị bỏ quên (John)",
            status=TaskStatus.PENDING_CONFIRM,
        ),
        TEST_USER_ID,
    )
    fresh = await service.create_task(
        TaskCreate(
            title=f"{MARKER} vừa hỏi (Mary)",
            status=TaskStatus.PENDING_CONFIRM,
        ),
        TEST_USER_ID,
    )
    stale_id, fresh_id = stale.id, fresh.id

    # Backdate past the window.
    stale.created_at = _naive_utcnow() - timedelta(days=CANDIDATE_EXPIRY_DAYS + 1)
    await async_db.commit()

    expired = await TaskCandidateService(async_db).expire_stale_candidates()
    assert expired == 1

    await async_db.refresh(stale)
    await async_db.refresh(fresh)
    assert stale.status is TaskStatus.CANCELLED
    assert fresh.status is TaskStatus.PENDING_CONFIRM


@pytest.mark.asyncio
async def test_a_confirmed_suggestion_is_not_expired(async_db, stub_llm):
    """Expiry only retires questions nobody answered."""
    stub_llm([])
    from app.schemas import TaskCreate

    service = TaskService(async_db)
    task = await service.create_task(
        TaskCreate(
            title=f"{MARKER} đã xác nhận (John)",
            status=TaskStatus.PENDING_CONFIRM,
        ),
        TEST_USER_ID,
    )
    await service.confirm_task(task.id, TEST_USER_ID)
    task.created_at = _naive_utcnow() - timedelta(days=CANDIDATE_EXPIRY_DAYS + 1)
    await async_db.commit()

    assert await TaskCandidateService(async_db).expire_stale_candidates() == 0
    await async_db.refresh(task)
    assert task.status is TaskStatus.TODO


# ============================================================================
# Validation still applies on the real path
# ============================================================================

@pytest.mark.asyncio
async def test_a_hedged_sentence_produces_no_suggestion_end_to_end(async_db, stub_llm):
    """The model proposed it; the validator threw it out."""
    stub_llm([{
        "counterparty": "John",
        "expected_action": "gửi proposal",
        "deadline": None,
        "source_quote": "Chắc thứ 6 tôi gửi proposal cho John",
    }])

    conversation_id = await _make_conversation(
        async_db, "hedged",
        ["Chắc thứ 6 tôi gửi proposal cho John", "ok"],
        idle_minutes=IDLE_MINUTES + 1,
    )
    await TaskFlushWorker().flush_conversation(async_db, conversation_id)

    suggestions = (await async_db.execute(
        select(Task).where(Task.source_conversation_id == conversation_id)
    )).scalars().all()
    assert suggestions == []


@pytest.mark.asyncio
async def test_an_empty_task_list_is_the_normal_outcome(async_db, stub_llm):
    """Most conversations contain no task. Extracting nothing must be a
    clean success, not an error path."""
    stub_llm([])
    conversation_id = await _make_conversation(
        async_db, "nothing to find",
        ["thứ 6 tôi rảnh", "ok"],
        idle_minutes=IDLE_MINUTES + 1,
    )

    assert await TaskFlushWorker().flush_conversation(async_db, conversation_id) is True
    suggestions = (await async_db.execute(
        select(Task).where(Task.source_conversation_id == conversation_id)
    )).scalars().all()
    assert suggestions == []


# ============================================================================
# Worker loop affinity — the real production crash this class caused
# ============================================================================
#
# `TaskFlushWorker` (then `CommitmentFlushWorker`) runs in its own OS thread
# with its own event loop (`WorkerThread` in app/__init__.py — the same
# mechanism ReminderWorker and GoogleSyncWorker use). The first version of
# this class reached for the module-level `AsyncSessionLocal` singleton when
# no session was supplied, which is bound to whichever loop initialises it
# first — the main FastAPI loop in production, since `init_async_engine()`
# runs there deliberately before any worker thread starts. Using it from
# this worker's own thread failed with "Future attached to a different
# loop", and in production it went further: it corrupted the pooled
# connection badly enough that a LATER unrelated query on that same
# connection raised `AttributeError: 'NoneType' object has no attribute
# '_init_types'` deep inside asyncpg — a real crash, caught from the
# server's own logs rather than by any test, because every test up to this
# point called `find_flushable`/`flush_conversation` with a session passed
# in directly and never exercised `sweep_once()`/`_sessions()`/`start()` at
# all.


@pytest.mark.asyncio
async def test_sweep_before_start_fails_loudly_instead_of_using_the_wrong_loop():
    """The old bug's silent half, closed: `_sessions()` no longer has a
    "just use the singleton" fallback to fall into. A worker asked to sweep
    before `start()` has created its own engine raises immediately, with a
    message that says what to do about it — never a connection borrowed
    from a loop this worker doesn't own."""
    worker = TaskFlushWorker()
    with pytest.raises(RuntimeError, match="start\\(\\)"):
        await worker.sweep_once()


@pytest.mark.asyncio
async def test_start_creates_a_worker_owned_engine_that_survives_a_real_thread(
    async_db, stub_llm, monkeypatch
):
    """The reproduction: a genuinely separate OS thread with a genuinely
    separate event loop — not a stand-in, the exact mechanism `WorkerThread`
    uses — runs the real `start()` loop against a real flushable
    conversation. A regression here would fail the same way production did:
    a `RuntimeError`/`AttributeError` raised deep inside asyncpg on the
    worker thread, which `start()`'s own `except Exception` logs and
    swallows — so the meaningful assertion is not "no exception surfaced"
    but that the task this sweep exists to produce actually landed.
    """
    import app.services.task_flush_worker as flush_worker_module

    # Real work happens fast so the thread's first loop iteration finds it.
    monkeypatch.setattr(flush_worker_module, "SWEEP_INTERVAL_SECONDS", 0.05)

    stub_llm([{
        "counterparty": "John",
        "expected_action": "gửi proposal",
        "deadline": None,
        "source_quote": "thứ 6 tôi gửi proposal cho John",
    }])

    conversation_id = await _make_conversation(
        async_db, "cross-thread",
        ["thứ 6 tôi gửi proposal cho John", "ok"],
        idle_minutes=IDLE_MINUTES + 1,
    )

    worker = TaskFlushWorker()
    loop_holder: dict = {}

    def _run_in_new_thread():
        loop = asyncio.new_event_loop()
        loop_holder["loop"] = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(worker.start())
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()

    thread = threading.Thread(target=_run_in_new_thread, name="test-task-flush", daemon=True)
    thread.start()
    try:
        # Poll from the test's own loop for the side effect, rather than a
        # fixed sleep — the worker thread's first sweep is what we're
        # actually waiting on.
        deadline = asyncio.get_event_loop().time() + 10
        suggestion = None
        while asyncio.get_event_loop().time() < deadline:
            suggestions = (await async_db.execute(
                select(Task).where(Task.source_conversation_id == conversation_id)
            )).scalars().all()
            if suggestions:
                suggestion = suggestions[0]
                break
            await asyncio.sleep(0.1)
    finally:
        worker._running = False
        loop = loop_holder.get("loop")
        if loop is not None:
            loop.call_soon_threadsafe(lambda: None)  # wake it from sleep
        thread.join(timeout=5)

    assert suggestion is not None, (
        "the worker thread never produced the task — its own engine "
        "did not survive running on a genuinely separate event loop"
    )
    assert suggestion.status is TaskStatus.PENDING_CONFIRM
    assert "John" in suggestion.title
