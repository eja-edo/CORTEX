"""
Integration tests for Milestone 1.7 — ContextService.

Runs against the real dev Postgres, reusing the seeded user (same
convention as test_core_events.py / test_command_registry.py). Also verifies
ConversationService.build_system_prompt() and AgentService._build_context_string()
wire the resulting string into the system prompt without needing a live LLM
call (those two only do string-building + DB/summarizer/skill-retriever
work, no model API calls).
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.context.context_service import ContextService
from app.models import Note, Schedule, ScheduleType

TEST_USER_ID = UUID("73552833-a6de-40a1-bb69-6e034ca75460")


@pytest_asyncio.fixture(autouse=True)
async def _seeded_user():
    """Tài khoản dev mà tệp này hardcode — dựng nếu DB không còn nó.

    Xem `tests/integration/seeded_user.py`: giả định "hàng này luôn có sẵn"
    đã sai một lần và làm 120 test đỏ cùng lúc.
    """
    from app.database_async import make_async_sessionmaker
    from tests.integration.seeded_user import ensure_seeded_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await ensure_seeded_user(db)
    await engine.dispose()

# Note vẫn có `workspace_id` nullable trong giai đoạn chuyển; các test
# dưới chỉ cần một Note hợp lệ, nên chúng dựng nó không kèm container.


@pytest_asyncio.fixture
async def seeded_project():
    """Dự án của `TEST_USER_ID`, tạo lười đúng như đường thật làm."""
    from app.database_async import make_async_sessionmaker
    from app.services.projects import ProjectService

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        project = await ProjectService(db).get_or_create_personal(TEST_USER_ID)
        await db.commit()
        project_id = project.id
    await engine.dispose()
    return project_id


@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
    await engine.dispose()


@pytest.fixture
def sync_db():
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# pills / page / runtime passthrough
# ============================================================================

@pytest.mark.asyncio
async def test_build_context_extracts_pills(async_db):
    service = ContextService(async_db)
    context = await service.build_context(
        user_id=TEST_USER_ID,
        runtime_context={
            "pills": [{"text": "Working on CS homework"}, {"text": "Due Friday", "source": "system"}],
        },
    )
    assert len(context.pills) == 2
    assert context.pills[0].text == "Working on CS homework"
    assert context.pills[0].source == "user"
    assert context.pills[1].source == "system"


@pytest.mark.asyncio
async def test_build_context_ignores_pills_without_text(async_db):
    service = ContextService(async_db)
    context = await service.build_context(
        user_id=TEST_USER_ID,
        runtime_context={"pills": [{"source": "user"}, {"text": ""}, "not-a-dict"]},
    )
    assert context.pills == []


@pytest.mark.asyncio
async def test_build_context_passes_through_page_and_runtime(async_db):
    service = ContextService(async_db)
    context = await service.build_context(
        user_id=TEST_USER_ID,
        runtime_context={"page": {"url": "/notes/123"}, "runtime": {"device": "mobile"}},
    )
    assert context.page == {"url": "/notes/123"}
    assert context.runtime == {"device": "mobile"}


@pytest.mark.asyncio
async def test_build_context_tolerates_malformed_page_runtime(async_db):
    """Frontend context is free-form input, not a validated contract —
    non-dict page/runtime must not raise."""
    service = ContextService(async_db)
    context = await service.build_context(
        user_id=TEST_USER_ID,
        runtime_context={"page": "not-a-dict", "runtime": 42},
    )
    assert context.page == {}
    assert context.runtime == {}


@pytest.mark.asyncio
async def test_build_context_with_no_runtime_context(async_db):
    service = ContextService(async_db)
    context = await service.build_context(user_id=TEST_USER_ID)
    assert context.pills == []
    assert context.page == {}


# ============================================================================
# project
# ============================================================================

@pytest.mark.asyncio
async def test_build_context_includes_real_project(async_db, seeded_project):
    service = ContextService(async_db)
    context = await service.build_context(user_id=TEST_USER_ID, project_id=seeded_project)

    assert context.project is not None
    assert context.project.project_id == seeded_project
    assert context.project.member_count >= 1


@pytest.mark.asyncio
async def test_build_context_project_none_when_not_provided(async_db):
    service = ContextService(async_db)
    context = await service.build_context(user_id=TEST_USER_ID)
    assert context.project is None


@pytest.mark.asyncio
async def test_build_context_project_none_for_non_member(async_db, seeded_project):
    service = ContextService(async_db)
    context = await service.build_context(user_id=uuid4(), project_id=seeded_project)
    assert context.project is None


@pytest.mark.asyncio
async def test_build_context_project_none_for_unknown_project_id(async_db):
    service = ContextService(async_db)
    context = await service.build_context(user_id=TEST_USER_ID, project_id=uuid4())
    assert context.project is None


# ============================================================================
# recent notes / upcoming schedules
# ============================================================================

@pytest.mark.asyncio
async def test_build_context_includes_recent_note(async_db):
    note = Note(user_id=TEST_USER_ID, title="Context Test Note", content="x")
    async_db.add(note)
    await async_db.commit()
    try:
        service = ContextService(async_db)
        context = await service.build_context(user_id=TEST_USER_ID)
        assert any(n["title"] == "Context Test Note" for n in context.recent_notes)
    finally:
        await async_db.execute(delete(Note).where(Note.id == note.id))
        await async_db.commit()


@pytest.mark.asyncio
async def test_build_context_excludes_deleted_notes(async_db):
    note = Note(user_id=TEST_USER_ID, title="Deleted Note", content="x", is_deleted=True)
    async_db.add(note)
    await async_db.commit()
    try:
        service = ContextService(async_db)
        context = await service.build_context(user_id=TEST_USER_ID)
        assert not any(n["title"] == "Deleted Note" for n in context.recent_notes)
    finally:
        await async_db.execute(delete(Note).where(Note.id == note.id))
        await async_db.commit()


@pytest.mark.asyncio
async def test_build_context_includes_upcoming_schedule(async_db, sync_db):
    now = datetime.now(timezone.utc)
    schedule = Schedule(
        user_id=TEST_USER_ID, title="Context Test Meeting", type=ScheduleType.PERSONAL,
        start_time=now + timedelta(hours=2), end_time=now + timedelta(hours=3), is_completed=False,
    )
    sync_db.add(schedule)
    sync_db.commit()
    sync_db.refresh(schedule)
    try:
        service = ContextService(async_db)
        context = await service.build_context(user_id=TEST_USER_ID)
        assert any(s["title"] == "Context Test Meeting" for s in context.recent_schedules)
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


@pytest.mark.asyncio
async def test_build_context_excludes_schedule_beyond_7_days(async_db, sync_db):
    now = datetime.now(timezone.utc)
    schedule = Schedule(
        user_id=TEST_USER_ID, title="Far Future Meeting", type=ScheduleType.PERSONAL,
        start_time=now + timedelta(days=30), end_time=now + timedelta(days=30, hours=1), is_completed=False,
    )
    sync_db.add(schedule)
    sync_db.commit()
    sync_db.refresh(schedule)
    try:
        service = ContextService(async_db)
        context = await service.build_context(user_id=TEST_USER_ID)
        assert not any(s["title"] == "Far Future Meeting" for s in context.recent_schedules)
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


@pytest.mark.asyncio
async def test_build_context_excludes_completed_schedule(async_db, sync_db):
    now = datetime.now(timezone.utc)
    schedule = Schedule(
        user_id=TEST_USER_ID, title="Already Done", type=ScheduleType.PERSONAL,
        start_time=now + timedelta(hours=2), end_time=now + timedelta(hours=3), is_completed=True,
    )
    sync_db.add(schedule)
    sync_db.commit()
    sync_db.refresh(schedule)
    try:
        service = ContextService(async_db)
        context = await service.build_context(user_id=TEST_USER_ID)
        assert not any(s["title"] == "Already Done" for s in context.recent_schedules)
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


# ============================================================================
# relevance filtering
# ============================================================================

@pytest.mark.asyncio
async def test_build_context_filters_notes_for_schedule_intent(async_db, sync_db):
    now = datetime.now(timezone.utc)
    note = Note(user_id=TEST_USER_ID, title="Some Note", content="x")
    async_db.add(note)
    await async_db.commit()
    schedule = Schedule(
        user_id=TEST_USER_ID, title="Some Meeting", type=ScheduleType.PERSONAL,
        start_time=now + timedelta(hours=2), end_time=now + timedelta(hours=3), is_completed=False,
    )
    sync_db.add(schedule)
    sync_db.commit()
    sync_db.refresh(schedule)
    try:
        service = ContextService(async_db)
        context = await service.build_context(user_id=TEST_USER_ID, intent="schedule meeting")
        assert context.recent_notes == []
        assert any(s["title"] == "Some Meeting" for s in context.recent_schedules)
    finally:
        await async_db.execute(delete(Note).where(Note.id == note.id))
        await async_db.commit()
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


@pytest.mark.asyncio
async def test_build_context_filters_schedules_for_note_intent(async_db, sync_db):
    now = datetime.now(timezone.utc)
    note = Note(user_id=TEST_USER_ID, title="Some Note", content="x")
    async_db.add(note)
    await async_db.commit()
    schedule = Schedule(
        user_id=TEST_USER_ID, title="Some Meeting", type=ScheduleType.PERSONAL,
        start_time=now + timedelta(hours=2), end_time=now + timedelta(hours=3), is_completed=False,
    )
    sync_db.add(schedule)
    sync_db.commit()
    sync_db.refresh(schedule)
    try:
        service = ContextService(async_db)
        context = await service.build_context(user_id=TEST_USER_ID, intent="write a note about X")
        assert context.recent_schedules == []
        assert any(n["title"] == "Some Note" for n in context.recent_notes)
    finally:
        await async_db.execute(delete(Note).where(Note.id == note.id))
        await async_db.commit()
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


# ============================================================================
# ConversationService / AgentService integration (no live LLM call needed)
# ============================================================================

@pytest.mark.asyncio
async def test_build_system_prompt_appends_context_string(async_db):
    from app.ai.agents.conversation_service import ConversationService
    from app.models import User

    user = (await async_db.execute(
        __import__("sqlalchemy").select(User).where(User.id == TEST_USER_ID)
    )).scalar_one()
    service = ConversationService(user, async_db)
    conv = await service.store.get_or_create_conversation(user_id=TEST_USER_ID)
    await async_db.commit()

    try:
        prompt = await service.build_system_prompt(
            conv, "hello", None, None, "BASE PROMPT", context_string="User context:\nDự án đang mở: Test",
        )
        assert "BASE PROMPT" in prompt
        assert "Dự án đang mở: Test" in prompt
    finally:
        from app.models import AgentConversation
        await async_db.execute(delete(AgentConversation).where(AgentConversation.id == conv.id))
        await async_db.commit()


@pytest.mark.asyncio
async def test_build_system_prompt_omits_section_when_context_string_empty(async_db):
    from app.ai.agents.conversation_service import ConversationService
    from app.models import User

    user = (await async_db.execute(
        __import__("sqlalchemy").select(User).where(User.id == TEST_USER_ID)
    )).scalar_one()
    service = ConversationService(user, async_db)
    conv = await service.store.get_or_create_conversation(user_id=TEST_USER_ID)
    await async_db.commit()

    try:
        prompt = await service.build_system_prompt(conv, "hello", None, None, "BASE PROMPT", context_string=None)
        assert prompt.startswith("BASE PROMPT")
    finally:
        from app.models import AgentConversation
        await async_db.execute(delete(AgentConversation).where(AgentConversation.id == conv.id))
        await async_db.commit()


@pytest.mark.asyncio
async def test_agent_service_build_context_string_helper(async_db, seeded_project):
    from app.ai.agents.agent_service import AgentService
    from app.models import User

    user = (await async_db.execute(
        __import__("sqlalchemy").select(User).where(User.id == TEST_USER_ID)
    )).scalar_one()
    agent_service = AgentService(user, async_db)

    result = await agent_service._build_context_string(seeded_project, uuid4(), None)
    assert result is None or "Dự án đang mở" in result


@pytest.mark.asyncio
async def test_agent_service_build_context_string_never_raises_on_bad_project(async_db):
    """A project_id that isn't a real UUID-shaped value some caller might
    pass shouldn't crash request handling — ContextService swallows lookup
    failures internally."""
    from app.ai.agents.agent_service import AgentService
    from app.models import User

    user = (await async_db.execute(
        __import__("sqlalchemy").select(User).where(User.id == TEST_USER_ID)
    )).scalar_one()
    agent_service = AgentService(user, async_db)

    result = await agent_service._build_context_string(uuid4(), uuid4(), {"pills": "not-a-list"})
    assert result is None or isinstance(result, str)
