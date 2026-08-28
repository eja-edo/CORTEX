"""
Integration tests for Milestone 1.5 — CommandRegistry.

Runs against the real dev Postgres + Redis, reusing the seeded user/
seeded user. Covers: registration,
argument validation, permission checks (project membership + container-less
scoped ownership), snapshot creation, audit logging, event publishing,
and the revert pipeline (generic mechanics + real note/schedule handlers
exercising the actual `_default_revert` branches).
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic import BaseModel
from sqlalchemy import delete

from app.ai.agents.action_snapshot_store import ActionSnapshot, get_snapshot_store
from app.ai.agents.tool_context import ToolContext
from app.commands.args import (
    NoteCreateArgs,
    ScheduleCreateArgs,
    ScheduleUpdateArgs,
)
from app.commands.registry import CommandRegistry
from app.commands.schemas import Command, CommandStatus, PermissionScope
from app.events.event_bus import EventBus, reset_event_bus
from app.events.schemas import EventEnvelope
from app.models import Note, Schedule, ScheduleType, User
from app.schemas import NoteCreate
from app.services.notes import NoteService
from app.services.schedule_service import ScheduleService

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



# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def registry():
    """
    A fresh, LOCAL CommandRegistry — deliberately not touching the global
    singleton (get_command_registry()/reset_command_registry()). The real
    tool handlers (create_note.py etc., see test_tool_command_migration.py)
    call get_command_registry() and expect it to still hold the commands
    app.commands.handlers registered once at import time; resetting the
    global here would wipe that for every test in the same pytest session,
    not just this file.
    """
    return CommandRegistry()


@pytest_asyncio.fixture(autouse=True)
async def _reset_event_bus_between_tests():
    """
    NoteService/ScheduleService fire-and-forget `command.*`/`note.*`/
    `schedule.*` events via the global EventBus singleton regardless of
    whether a given test cares about events. pytest-asyncio gives each test
    its own event loop; a singleton connected on a previous test's (now
    closed) loop breaks with "attached to a different loop" here — same
    class of issue as test_core_events.py's async_db fixture. Force a fresh
    singleton per test.
    """
    reset_event_bus()
    yield
    import app.events.event_bus as event_bus_module
    if event_bus_module._event_bus is not None:
        try:
            await event_bus_module._event_bus.disconnect()
        except Exception:
            pass
        event_bus_module._event_bus = None


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
    """Dedicated engine per test — see test_core_events.py's `async_db` for
    why the module-level AsyncSessionLocal singleton isn't safe here."""
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


@pytest_asyncio.fixture
async def ctx(async_db):
    context = ToolContext(user_id=TEST_USER_ID, async_db=async_db)
    yield context
    context.close()


@pytest_asyncio.fixture
async def event_subscriber():
    reset_event_bus()
    bus = EventBus()
    await bus.connect()

    received: list[EventEnvelope] = []

    async def collector(event: EventEnvelope):
        received.append(event)

    bus.subscribe("*.*", collector)
    bus.subscribe("*.*.*", collector)

    import app.events.event_bus as event_bus_module
    event_bus_module._event_bus = bus

    yield received

    bus.unsubscribe("*.*", collector)
    bus.unsubscribe("*.*.*", collector)
    event_bus_module._event_bus = None
    await bus.disconnect()


@pytest_asyncio.fixture
async def other_user_id(async_db):
    """A second, throwaway user — needed to test permission-denial paths.
    The dev DB only seeds one real user."""
    user = User(
        email=f"cmdreg-test-{uuid4().hex[:8]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="CommandRegistry Test User",
    )
    async_db.add(user)
    await async_db.commit()
    yield user.id
    await async_db.execute(delete(User).where(User.id == user.id))
    await async_db.commit()


async def _add_member(async_db, project_id: UUID, user_id: UUID) -> None:
    """Thêm một người vào dự án.

    Không có tham số `role`: `ProjectMember` cố ý không có cột đó (QĐ-1) —
    "ai được đọc tài liệu" và "ai chịu trách nhiệm việc" là hai câu hỏi
    khác nhau, và ba mức owner/editor/viewer chỉ trả lời câu thứ nhất.
    """
    from app.models import ProjectJoinSource, ProjectMember

    async_db.add(
        ProjectMember(
            project_id=project_id, user_id=user_id, joined_via=ProjectJoinSource.MANUAL
        )
    )
    await async_db.commit()



def _events_of_type(events: list[EventEnvelope], event_type: str) -> list[EventEnvelope]:
    return [e for e in events if e.type == event_type]


class _NoArgs(BaseModel):
    pass


class _TitleArgs(BaseModel):
    title: str


async def dummy_success_handler(command: Command, ctx: ToolContext) -> dict:
    return {"result": "ok", "title": command.args.get("title"), "prev_state": {}}


async def dummy_failing_handler(command: Command, ctx: ToolContext) -> dict:
    raise RuntimeError("handler exploded")


# ============================================================================
# Real handlers (test-local — Milestone 1.6 will formalize these under
# app/commands/handlers/). Used to exercise CommandRegistry's snapshot +
# default-revert logic against real DB rows, not just dummy handlers.
# ============================================================================

async def real_note_create_handler(command: Command, ctx: ToolContext) -> dict:
    args = NoteCreateArgs(**command.args)
    async with ctx.async_db() as db:
        service = NoteService(db)
        note = await service.create_note(
            payload=NoteCreate(
                project_id=args.project_id,
                title=args.title,
                content=args.content or "empty note",
                parent_note_id=args.parent_note_id,
                content_type=args.content_type,
            ),
            user_id=ctx.user_id,
        )
        return {
            "id": str(note.id),
            "title": note.title,
            "prev_state": {"note_id": str(note.id)},
        }


async def real_schedule_create_handler(command: Command, ctx: ToolContext) -> dict:
    args = ScheduleCreateArgs(**command.args)
    with ctx:
        db = ctx.get_sync_db()
        service = ScheduleService(db)
        schedule = service.create_schedule_simple(
            user_id=ctx.user_id,
            title=args.title,
            schedule_type=args.schedule_type,
            start_time=args.start_time,
            end_time=args.end_time,
            location=args.location,
            description=args.description,
        )
        return {
            "id": str(schedule.id),
            "title": schedule.title,
            "prev_state": {"schedule_id": str(schedule.id)},
        }


async def real_schedule_update_handler(command: Command, ctx: ToolContext) -> dict:
    args = ScheduleUpdateArgs(**command.args)
    with ctx:
        db = ctx.get_sync_db()
        service = ScheduleService(db)
        current = service.get_schedule_by_id(args.schedule_id, ctx.user_id)
        if not current:
            raise ValueError(f"Schedule not found: {args.schedule_id}")

        prev_fields = {
            "schedule_id": str(args.schedule_id),
            "title": current.title,
            "start_time": current.start_time.isoformat(),
            "end_time": current.end_time.isoformat(),
            "description": current.description,
            "is_completed": current.is_completed,
        }

        updated = service.update_schedule_fields(
            schedule_id=args.schedule_id,
            user_id=ctx.user_id,
            title=args.title,
            start_time=args.start_time,
            end_time=args.end_time,
            description=args.description,
            is_completed=args.is_completed,
        )
        return {
            "id": str(updated.id),
            "title": updated.title,
            "prev_state": prev_fields,
        }


# ============================================================================
# Registration
# ============================================================================

def test_register_command(registry):
    registry.register(
        name="note.create",
        description="Create a note",
        args_schema=NoteCreateArgs,
        handler=dummy_success_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
    )

    commands = registry.list_commands()
    assert len(commands) == 1
    assert commands[0]["name"] == "note.create"
    assert commands[0]["revertable"] is True
    assert commands[0]["permission_scope"] == "write"


def test_register_duplicate_raises(registry):
    registry.register(name="note.create", description="", args_schema=_NoArgs, handler=dummy_success_handler)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(name="note.create", description="", args_schema=_NoArgs, handler=dummy_success_handler)


def test_list_commands_empty_registry(registry):
    assert registry.list_commands() == []


def test_list_commands_multiple(registry):
    registry.register(name="note.create", description="", args_schema=_NoArgs, handler=dummy_success_handler, revertable=True)
    registry.register(name="note.delete", description="", args_schema=_NoArgs, handler=dummy_success_handler, revertable=True)

    names = {c["name"] for c in registry.list_commands()}
    assert names == {"note.create", "note.delete"}


# ============================================================================
# Execution — happy path
# ============================================================================

@pytest.mark.asyncio
async def test_execute_success_non_revertable(registry, ctx):
    registry.register(name="dummy.op", description="", args_schema=_TitleArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ)

    command = Command(command_name="dummy.op", args={"title": "Hello"}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    assert result.success is True
    assert result.data["title"] == "Hello"
    assert result.action_id is None
    assert result.revert_hint is None
    assert result.duration_ms >= 0
    assert command.status == CommandStatus.COMPLETED


@pytest.mark.asyncio
async def test_execute_success_revertable_creates_snapshot(registry, ctx):
    registry.register(name="dummy.op", description="", args_schema=_TitleArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ, revertable=True)

    command = Command(command_name="dummy.op", args={"title": "Hello"}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    assert result.success is True
    assert result.action_id == command.command_id
    assert result.revert_hint is not None and result.action_id in result.revert_hint

    store = get_snapshot_store()
    snapshot = await store.get(str(ctx.user_id), result.action_id)
    assert snapshot is not None
    assert snapshot.tool_name == "dummy.op"


# ============================================================================
# Execution — validation errors
# ============================================================================

@pytest.mark.asyncio
async def test_execute_missing_required_arg(registry, ctx):
    registry.register(name="dummy.op", description="", args_schema=_TitleArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ)

    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    assert result.success is False
    assert "Invalid arguments" in result.error
    assert command.status == CommandStatus.FAILED


@pytest.mark.asyncio
async def test_execute_wrong_type_arg(registry, ctx):
    registry.register(name="note.create", description="", args_schema=NoteCreateArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ)

    command = Command(
        command_name="note.create",
        args={"project_id": "not-a-uuid", "title": "Test"},
        requested_by=ctx.user_id,
    )
    result = await registry.execute(command, ctx)

    assert result.success is False
    assert "Invalid arguments" in result.error


@pytest.mark.asyncio
async def test_execute_unknown_command(registry, ctx):
    command = Command(command_name="unknown.command", args={}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    assert result.success is False
    assert "Unknown command" in result.error


@pytest.mark.asyncio
async def test_execute_handler_exception_is_reported(registry, ctx):
    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_failing_handler, permission_scope=PermissionScope.READ)

    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    assert result.success is False
    assert "handler exploded" in result.error
    assert command.status == CommandStatus.FAILED


# ============================================================================
# Execution — permission checks
# ============================================================================

@pytest.mark.asyncio
async def test_permission_read_scope_always_allowed(registry, async_db, other_user_id, seeded_project):
    """READ luôn được phép, kể cả với người không ở trong dự án nào."""
    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ)

    other_ctx = ToolContext(user_id=other_user_id, async_db=async_db, project_id=seeded_project)
    command = Command(command_name="dummy.op", args={}, requested_by=other_user_id, project_id=seeded_project)
    result = await registry.execute(command, other_ctx)

    assert result.success is True


@pytest.mark.asyncio
async def test_permission_write_scope_member_allowed(registry, ctx, seeded_project):
    """TEST_USER_ID là chủ sở hữu — và do đó là thành viên — của dự án này."""
    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.WRITE)

    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id, project_id=seeded_project)
    result = await registry.execute(command, ctx)

    assert result.success is True


@pytest.mark.asyncio
async def test_permission_write_scope_added_member_allowed(
    registry, async_db, other_user_id, seeded_project
):
    """Vào dự án là ghi được — không có bậc vai nào ở giữa (QĐ-1)."""
    await _add_member(async_db, seeded_project, other_user_id)
    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.WRITE)

    other_ctx = ToolContext(user_id=other_user_id, async_db=async_db, project_id=seeded_project)
    command = Command(command_name="dummy.op", args={}, requested_by=other_user_id, project_id=seeded_project)
    result = await registry.execute(command, other_ctx)

    assert result.success is True


@pytest.mark.asyncio
async def test_permission_write_scope_non_member_denied(
    registry, async_db, other_user_id, seeded_project
):
    """Tính chất bảo mật thật: không ở trong dự án thì không ghi được.

    Không có nhánh này, `project_id` trở thành cách ghi vào dự án người khác
    chỉ bằng cách đoán một UUID.
    """
    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.WRITE)

    other_ctx = ToolContext(user_id=other_user_id, async_db=async_db, project_id=seeded_project)
    command = Command(command_name="dummy.op", args={}, requested_by=other_user_id, project_id=seeded_project)
    result = await registry.execute(command, other_ctx)

    assert result.success is False
    assert "Permission denied" in result.error
    assert command.status == CommandStatus.FAILED


@pytest.mark.asyncio
async def test_admin_scope_is_the_same_check_as_write(
    registry, async_db, other_user_id, seeded_project
):
    """ADMIN không còn khác WRITE, và điều đó được ghi lại chứ không để ngầm.

    Ba mức workspace (owner/editor/viewer) từng làm ADMIN có nghĩa riêng.
    `ProjectMember` cố ý không có `role` (QĐ-1), nên cả hai mức giờ hỏi
    cùng một câu: *có ở trong dự án không?*. Giữ `PermissionScope.ADMIN`
    trong enum là để lệnh nào cần một bậc cao hơn về sau có chỗ khai báo —
    nhưng hôm nay nó không cấp thêm gì, và một test nói thẳng điều đó tốt
    hơn một hàng rào tưởng là có.
    """
    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.ADMIN)

    ctx_member = ToolContext(user_id=TEST_USER_ID, async_db=async_db, project_id=seeded_project)
    allowed = await registry.execute(
        Command(command_name="dummy.op", args={}, requested_by=TEST_USER_ID, project_id=seeded_project),
        ctx_member,
    )
    assert allowed.success is True

    ctx_outsider = ToolContext(user_id=other_user_id, async_db=async_db, project_id=seeded_project)
    denied = await registry.execute(
        Command(command_name="dummy.op", args={}, requested_by=other_user_id, project_id=seeded_project),
        ctx_outsider,
    )
    assert denied.success is False
    assert "not a member" in denied.error


@pytest.mark.asyncio
async def test_permission_no_container_allowed_regardless_of_membership(registry, async_db, other_user_id):
    """Lệnh kiểu schedule: không có container nào. Bất kỳ `requested_by` đã
    xác thực nào cũng qua được tầng này — quyền ở mức tài nguyên do
    handler/service tự kiểm (xem docstring `_check_permission`)."""
    registry.register(name="schedule.create", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.WRITE)

    other_ctx = ToolContext(user_id=other_user_id, async_db=async_db)
    command = Command(command_name="schedule.create", args={}, requested_by=other_user_id)
    result = await registry.execute(command, other_ctx)

    assert result.success is True


# ============================================================================
# Event publishing
# ============================================================================

@pytest.mark.asyncio
async def test_execute_success_publishes_command_event(registry, ctx, event_subscriber, seeded_project):
    registry.register(name="dummy.op", description="", args_schema=_TitleArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ, revertable=True)

    command = Command(command_name="dummy.op", args={"title": "Hello"}, requested_by=ctx.user_id, project_id=seeded_project)
    result = await registry.execute(command, ctx)

    events = _events_of_type(event_subscriber, "command.dummy.op")
    assert len(events) == 1
    event = events[0]
    assert event.user_id == ctx.user_id
    assert event.payload["command_id"] == command.command_id
    assert event.payload["action_id"] == result.action_id
    assert event.payload["title"] == "Hello"  # merged from result_data


@pytest.mark.asyncio
async def test_execute_failure_does_not_publish_event(registry, ctx, event_subscriber):
    registry.register(name="dummy.op", description="", args_schema=_TitleArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ)

    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)  # missing title
    await registry.execute(command, ctx)

    assert _events_of_type(event_subscriber, "command.dummy.op") == []


@pytest.mark.asyncio
async def test_event_publish_failure_does_not_break_execution(registry, ctx, monkeypatch):
    from unittest.mock import AsyncMock

    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ)

    broken_bus = AsyncMock()
    broken_bus.publish.side_effect = Exception("event bus down")
    monkeypatch.setattr(registry, "_get_event_bus", AsyncMock(return_value=broken_bus))

    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    assert result.success is True


# ============================================================================
# Audit logging
# ============================================================================

@pytest.mark.asyncio
async def test_audit_log_on_success(registry, ctx, caplog):
    import logging
    caplog.set_level(logging.INFO)

    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ)
    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)
    await registry.execute(command, ctx)

    assert "Command completed: dummy.op" in caplog.text


@pytest.mark.asyncio
async def test_audit_log_on_failure(registry, ctx, caplog):
    import logging
    caplog.set_level(logging.INFO)

    command = Command(command_name="unregistered.op", args={}, requested_by=ctx.user_id)
    await registry.execute(command, ctx)

    assert "Command failed: unregistered.op" in caplog.text


# ============================================================================
# Snapshot creation
# ============================================================================

@pytest.mark.asyncio
async def test_snapshot_default_empty_prev_state(registry, ctx):
    async def handler_no_prev_state(command, ctx):
        return {"result": "ok"}  # no "prev_state" key

    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=handler_no_prev_state, permission_scope=PermissionScope.READ, revertable=True)
    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    store = get_snapshot_store()
    snapshot = await store.get(str(ctx.user_id), result.action_id)
    assert snapshot.snapshot == {}


@pytest.mark.asyncio
async def test_non_revertable_command_creates_no_snapshot(registry, ctx):
    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ, revertable=False)
    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    assert result.action_id is None
    store = get_snapshot_store()
    snapshot = await store.get(str(ctx.user_id), command.command_id)
    assert snapshot is None


# ============================================================================
# Revert — generic mechanics
# ============================================================================

@pytest.mark.asyncio
async def test_revert_calls_custom_revert_handler(registry, ctx):
    from unittest.mock import AsyncMock

    custom_revert = AsyncMock()
    registry.register(
        name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler,
        permission_scope=PermissionScope.READ, revertable=True, revert_handler=custom_revert,
    )

    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    revert_result = await registry.revert_command(result.action_id, ctx)

    assert revert_result.success is True
    custom_revert.assert_awaited_once()
    called_snapshot = custom_revert.await_args.args[0]
    assert called_snapshot.tool_name == "dummy.op"


@pytest.mark.asyncio
async def test_revert_unknown_action_id(registry, ctx):
    result = await registry.revert_command(str(uuid4()), ctx)
    assert result.success is False
    assert "Snapshot not found" in result.error


@pytest.mark.asyncio
async def test_revert_already_reverted(registry, ctx):
    from unittest.mock import AsyncMock

    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ, revertable=True, revert_handler=AsyncMock())
    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)
    result = await registry.execute(command, ctx)

    first = await registry.revert_command(result.action_id, ctx)
    second = await registry.revert_command(result.action_id, ctx)

    assert first.success is True
    assert second.success is False
    assert "already reverted" in second.error


@pytest.mark.asyncio
async def test_revert_command_not_revertable(registry, ctx):
    """Snapshot exists (crafted directly) for a command registered with revertable=False."""
    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ, revertable=False)

    store = get_snapshot_store()
    action_id = str(uuid4())
    await store.save(ActionSnapshot(tool_name="dummy.op", user_id=str(ctx.user_id), conversation_id=None, snapshot={}, action_id=action_id))

    result = await registry.revert_command(action_id, ctx)
    assert result.success is False
    assert "not revertable" in result.error


@pytest.mark.asyncio
async def test_revert_unregistered_command_name(registry, ctx):
    store = get_snapshot_store()
    action_id = str(uuid4())
    await store.save(ActionSnapshot(tool_name="ghost.command", user_id=str(ctx.user_id), conversation_id=None, snapshot={}, action_id=action_id))

    result = await registry.revert_command(action_id, ctx)
    assert result.success is False
    assert "Unknown command" in result.error


@pytest.mark.asyncio
async def test_revert_cross_user_is_not_found(registry, ctx, other_user_id):
    """A snapshot saved under one user is invisible (not just forbidden) to another."""
    store = get_snapshot_store()
    action_id = str(uuid4())
    await store.save(ActionSnapshot(tool_name="dummy.op", user_id=str(other_user_id), conversation_id=None, snapshot={}, action_id=action_id))

    result = await registry.revert_command(action_id, ctx)  # ctx.user_id == TEST_USER_ID
    assert result.success is False
    assert "Snapshot not found" in result.error


# ============================================================================
# Revert — real _default_revert branches
# ============================================================================

@pytest.mark.asyncio
async def test_default_revert_note_create(registry, ctx, seeded_project):
    registry.register(name="note.create", description="", args_schema=NoteCreateArgs, handler=real_note_create_handler, permission_scope=PermissionScope.WRITE, revertable=True)

    command = Command(
        command_name="note.create",
        args={"project_id": str(seeded_project), "title": "Revert Me", "content": "will be reverted"},
        requested_by=ctx.user_id,
        project_id=seeded_project,
    )
    result = await registry.execute(command, ctx)
    assert result.success is True
    note_id = UUID(result.data["id"])

    try:
        service = NoteService(ctx._async_db)
        assert await service.get_note(note_id, ctx.user_id) is not None

        revert_result = await registry.revert_command(result.action_id, ctx)
        assert revert_result.success is True
        assert await service.get_note(note_id, ctx.user_id) is None  # soft-deleted
    finally:
        # Hard-delete regardless of whether the revert assertions above
        # passed — a soft-delete-only cleanup would leave the row behind if
        # a future regression makes revert fail before reaching it.
        await ctx._async_db.execute(delete(Note).where(Note.id == note_id))
        await ctx._async_db.commit()


@pytest.mark.asyncio
async def test_default_revert_note_create_missing_note_id_in_snapshot(registry, ctx):
    """A malformed snapshot (handler bug) must fail loudly, not silently no-op."""
    registry.register(name="note.create", description="", args_schema=NoteCreateArgs, handler=real_note_create_handler, permission_scope=PermissionScope.WRITE, revertable=True)

    store = get_snapshot_store()
    action_id = str(uuid4())
    await store.save(ActionSnapshot(tool_name="note.create", user_id=str(ctx.user_id), conversation_id=None, snapshot={}, action_id=action_id))

    result = await registry.revert_command(action_id, ctx)
    assert result.success is False
    assert "missing note_id" in result.error


@pytest.mark.asyncio
async def test_default_revert_schedule_create(registry, ctx):
    registry.register(name="schedule.create", description="", args_schema=ScheduleCreateArgs, handler=real_schedule_create_handler, permission_scope=PermissionScope.WRITE, revertable=True)

    now = datetime.now(timezone.utc)
    command = Command(
        command_name="schedule.create",
        args={
            "title": "Revert Me",
            "schedule_type": "PERSONAL",
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(hours=1)).isoformat(),
        },
        requested_by=ctx.user_id,
    )
    result = await registry.execute(command, ctx)
    assert result.success is True
    schedule_id = UUID(result.data["id"])

    sync_db = ctx.get_sync_db()
    service = ScheduleService(sync_db)
    assert service.get_schedule_by_id(schedule_id, ctx.user_id) is not None

    revert_result = await registry.revert_command(result.action_id, ctx)
    assert revert_result.success is True
    assert service.get_schedule_by_id(schedule_id, ctx.user_id) is None


@pytest.mark.asyncio
async def test_default_revert_schedule_update_restores_previous_fields(registry, ctx):
    # Create a schedule directly (not via command) to update+revert.
    sync_db = ctx.get_sync_db()
    base_service = ScheduleService(sync_db)
    now = datetime.now(timezone.utc)
    schedule = base_service.create_schedule_simple(
        user_id=ctx.user_id, title="Original Title", schedule_type=ScheduleType.PERSONAL,
        start_time=now, end_time=now + timedelta(hours=1),
    )

    try:
        registry.register(name="schedule.update", description="", args_schema=ScheduleUpdateArgs, handler=real_schedule_update_handler, permission_scope=PermissionScope.WRITE, revertable=True)

        command = Command(
            command_name="schedule.update",
            args={"schedule_id": str(schedule.id), "title": "Changed Title"},
            requested_by=ctx.user_id,
        )
        result = await registry.execute(command, ctx)
        assert result.success is True

        updated = base_service.get_schedule_by_id(schedule.id, ctx.user_id)
        assert updated.title == "Changed Title"

        revert_result = await registry.revert_command(result.action_id, ctx)
        assert revert_result.success is True

        # _default_revert's schedule.update branch commits through its own
        # SessionLocal(), not `sync_db` — expire sync_db's identity map so
        # this re-query reflects that commit instead of returning the
        # already-loaded (pre-revert) cached object for the same row.
        sync_db.expire_all()
        restored = base_service.get_schedule_by_id(schedule.id, ctx.user_id)
        assert restored.title == "Original Title"
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


@pytest.mark.asyncio
async def test_default_revert_note_update_raises_clear_error(registry, ctx):
    """note.update is registered non-revertable (Proposal flow — nothing to
    restore); if a snapshot for it ever existed anyway, _default_revert must
    still refuse clearly rather than silently doing nothing."""
    store = get_snapshot_store()
    action_id = str(uuid4())
    await store.save(ActionSnapshot(tool_name="note.update", user_id=str(ctx.user_id), conversation_id=None, snapshot={"note_id": "irrelevant"}, action_id=action_id))

    registry.register(name="note.update", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.WRITE, revertable=True)

    result = await registry.revert_command(action_id, ctx)
    assert result.success is False
    assert "Proposal" in result.error or "not revertable" in result.error.lower()


# ============================================================================
# Performance (Milestone 1.5 DoD: < 50ms overhead vs direct handler call)
# ============================================================================

@pytest.mark.asyncio
async def test_command_execution_overhead_under_50ms(registry, ctx):
    registry.register(name="dummy.op", description="", args_schema=_NoArgs, handler=dummy_success_handler, permission_scope=PermissionScope.READ)

    command = Command(command_name="dummy.op", args={}, requested_by=ctx.user_id)

    direct_start = time.perf_counter()
    await dummy_success_handler(command, ctx)
    direct_ms = (time.perf_counter() - direct_start) * 1000

    registry_start = time.perf_counter()
    result = await registry.execute(command, ctx)
    registry_ms = (time.perf_counter() - registry_start) * 1000

    overhead_ms = registry_ms - direct_ms
    print(f"\nDirect: {direct_ms:.2f}ms, Registry: {registry_ms:.2f}ms, Overhead: {overhead_ms:.2f}ms")

    assert result.success is True
    assert overhead_ms < 50, f"CommandRegistry overhead too high: {overhead_ms:.2f}ms"
