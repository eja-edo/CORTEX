"""
Integration tests for Milestone 1.6 — Tool→Command Migration.

Verifies: migrated AI tool handlers (create_note, update_note,
create_schedule, update_schedule, revert_action) produce the same
response shape as before migration, permission enforcement now happens via
CommandRegistry, and revert works identically through the tool AND the
REST endpoint (both delegate to the same CommandRegistry.revert_command()).

Runs against the real dev Postgres + Redis, reusing the seeded user/
workspace (same convention as test_core_events.py / test_command_registry.py).
"""

import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.ai.agents.tool_context import ToolContext
from app.commands.registry import get_command_registry
from app.events.event_bus import EventBus, reset_event_bus
from app.models import Note, Schedule, User

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

TEST_WORKSPACE_ID = UUID("4a31721d-13d1-4292-b89e-5838848bac8b")


# ============================================================================
# Fixtures (same conventions as test_command_registry.py)
# ============================================================================

@pytest_asyncio.fixture(autouse=True)
async def _reset_event_bus_between_tests():
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


@pytest_asyncio.fixture
async def seeded_project(async_db):
    """Dự án của `TEST_USER_ID`, tạo lười như đường thật làm.

    Không hardcode một id: dự án cá nhân sinh ra lần đầu có người cần nó
    (DESIGN 3.4), nên fixture đi qua đúng cửa đó thay vì cấy sẵn một hàng —
    một fixture đi đường khác với production là một fixture nói dối.
    """
    from app.services.projects import ProjectService

    project = await ProjectService(async_db).get_or_create_personal(TEST_USER_ID)
    await async_db.commit()
    return project.id


@pytest_asyncio.fixture
async def ctx(async_db, seeded_project):
    context = ToolContext(user_id=TEST_USER_ID, async_db=async_db, project_id=seeded_project)
    yield context
    context.close()


@pytest_asyncio.fixture
async def other_user_id(async_db):
    user = User(
        email=f"toolmig-test-{uuid4().hex[:8]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Tool Migration Test User",
    )
    async_db.add(user)
    await async_db.commit()
    yield user.id
    # Dọn theo đúng thứ tự FK. Dự án cá nhân giờ được tạo lười cho bất kỳ
    # ai ghi một ghi chú không kèm ngữ cảnh, nên một tài khoản dùng một lần
    # có thể đã sở hữu một dự án — và `projects.owner_id` chặn việc xoá user.
    from sqlalchemy import text as _sql

    from app.models import Note as NoteModel, Project, ProjectMember

    # `action_history` cũng trỏ vào user: tài khoản này giờ đi qua tầng
    # command (ghi audit + snapshot hoàn tác), thứ mà bản workspace của
    # test không chạm tới.
    await async_db.execute(
        _sql("DELETE FROM action_history WHERE user_id = :uid"), {"uid": user.id}
    )
    await async_db.execute(delete(NoteModel).where(NoteModel.user_id == user.id))
    await async_db.execute(delete(ProjectMember).where(ProjectMember.user_id == user.id))
    await async_db.execute(delete(Project).where(Project.owner_id == user.id))
    await async_db.execute(delete(User).where(User.id == user.id))
    await async_db.commit()


async def _add_member(async_db, workspace_id: UUID, user_id: UUID, role: str) -> None:
    """Raw SQL — see test_command_registry.py's _add_member for why (the
    workspace_members.role column is VARCHAR in this DB, not the Postgres
    enum type the model declares)."""
    from sqlalchemy import text

    await async_db.execute(
        text("INSERT INTO workspace_members (id, workspace_id, user_id, role, joined_at) "
             "VALUES (:id, :workspace_id, :user_id, :role, now())"),
        {"id": str(uuid4()), "workspace_id": str(workspace_id), "user_id": str(user_id), "role": role},
    )
    await async_db.commit()


# ============================================================================
# create_note tool
# ============================================================================

@pytest.mark.asyncio
async def test_create_note_tool_response_shape_unchanged(ctx):
    from app.ai.tools.create_note import create_note_handler

    result = await create_note_handler({"content": "Hello from migrated tool", "style_color": "blue"}, ctx)

    try:
        # Bộ khoá chính xác tool trả về — không bọc "result", không rò
        # "prev_state"/"title". `workspace_id` đã đổi thành `project_id`:
        # container của ghi chú giờ là dự án (DESIGN 11.4), và trả về khoá
        # cũ sẽ nói với agent về một khái niệm không còn ở đâu trong UI.
        assert set(result.keys()) == {"id", "project_id", "created_at", "action_id", "revert_hint", "success"}
        assert result["success"] is True
        assert result["project_id"] == str(ctx.project_id)
        assert result["action_id"] is not None
        assert "hoàn tác" in result["revert_hint"]
    finally:
        await ctx._async_db.execute(delete(Note).where(Note.id == UUID(result["id"])))
        await ctx._async_db.commit()


@pytest.mark.asyncio
async def test_create_note_tool_uses_style_color(ctx):
    from app.ai.tools.create_note import create_note_handler

    result = await create_note_handler({"content": "Colored note", "style_color": "purple"}, ctx)
    try:
        note = (await ctx._async_db.execute(select(Note).where(Note.id == UUID(result["id"])))).scalar_one()
        assert note.style == {"color": "purple"}
    finally:
        await ctx._async_db.execute(delete(Note).where(Note.id == UUID(result["id"])))
        await ctx._async_db.commit()


@pytest.mark.asyncio
async def test_create_note_tool_refuses_a_project_you_are_not_in(
    async_db, other_user_id, seeded_project
):
    """Tính chất bảo mật thật, giữ nguyên qua lần đổi container.

    Bản workspace của test này kiểm hai mức (viewer bị chặn, người ngoài bị
    chặn). `ProjectMember` cố ý **không có `role`** (QĐ-1), nên chỉ còn một
    mức — và đó là mức quan trọng: không phải thành viên thì không ghi được.
    Không có nhánh này, `project_id` trở thành cách ghi vào dự án người khác
    chỉ bằng cách đoán một UUID.
    """
    from app.ai.tools.create_note import create_note_handler

    other_ctx = ToolContext(
        user_id=other_user_id, async_db=async_db, project_id=seeded_project
    )

    with pytest.raises(PermissionError):
        await create_note_handler({"content": "Should not be created"}, other_ctx)


@pytest.mark.asyncio
async def test_create_note_tool_falls_back_to_the_personal_project(async_db, other_user_id):
    """Không có ngữ cảnh dự án là trạng thái **bình thường**, không phải lỗi.

    Chat qua DM Mezon không có dự án nào đang mở. Bản trước ném lỗi ở đây,
    nghĩa là agent không ghi được ghi chú nào ở đúng bề mặt hay dùng nhất.
    """
    from app.ai.tools.create_note import create_note_handler
    from app.models import Project, ProjectOrigin

    other_ctx = ToolContext(user_id=other_user_id, async_db=async_db)
    result = await create_note_handler({"content": "Ghi nhanh một ý"}, other_ctx)

    try:
        note = await async_db.get(Note, UUID(result["id"]))
        project = await async_db.get(Project, note.project_id)
        assert project.origin is ProjectOrigin.PERSONAL
        assert project.owner_id == other_user_id
    finally:
        await async_db.execute(delete(Note).where(Note.id == UUID(result["id"])))
        await async_db.commit()


@pytest.mark.asyncio
async def test_create_note_tool_revert_via_tool(ctx):
    from app.ai.tools.create_note import create_note_handler
    from app.ai.tools.revert_action import revert_action_handler
    from app.services.notes import NoteService

    created = await create_note_handler({"content": "To be reverted via tool"}, ctx)
    try:
        service = NoteService(ctx._async_db)
        assert await service.get_note(UUID(created["id"]), ctx.user_id) is not None

        revert_result = await revert_action_handler({"action_id": created["action_id"]}, ctx)
        assert revert_result["success"] is True
        assert await service.get_note(UUID(created["id"]), ctx.user_id) is None
    finally:
        await ctx._async_db.execute(delete(Note).where(Note.id == UUID(created["id"])))
        await ctx._async_db.commit()


@pytest.mark.asyncio
async def test_create_note_tool_revert_via_rest_endpoint(ctx):
    """The REST endpoint and the revert_action tool must go through the
    exact same CommandRegistry.revert_command() — this creates via the tool
    and reverts via the REST handler function directly (no HTTP layer
    needed since it's a plain async function once dependencies are
    supplied)."""
    from app.api.agent import revert_action as revert_action_endpoint
    from app.ai.tools.create_note import create_note_handler
    from app.services.notes import NoteService

    created = await create_note_handler({"content": "To be reverted via REST"}, ctx)
    try:
        current_user = (await ctx._async_db.execute(select(User).where(User.id == TEST_USER_ID))).scalar_one()

        response = await revert_action_endpoint(
            action_id=created["action_id"], current_user=current_user, db=ctx._async_db,
        )

        assert response["success"] is True
        assert response["action_id"] == created["action_id"]

        service = NoteService(ctx._async_db)
        assert await service.get_note(UUID(created["id"]), ctx.user_id) is None
    finally:
        await ctx._async_db.execute(delete(Note).where(Note.id == UUID(created["id"])))
        await ctx._async_db.commit()


@pytest.mark.asyncio
async def test_revert_rest_endpoint_404_for_unknown_action(ctx):
    from fastapi import HTTPException

    from app.api.agent import revert_action as revert_action_endpoint

    current_user = (await ctx._async_db.execute(select(User).where(User.id == TEST_USER_ID))).scalar_one()

    with pytest.raises(HTTPException) as exc_info:
        await revert_action_endpoint(action_id=str(uuid4()), current_user=current_user, db=ctx._async_db)

    assert exc_info.value.status_code == 404


# ============================================================================
# update_note tool
# ============================================================================

@pytest.mark.asyncio
async def test_update_note_tool_creates_proposal(ctx):
    from app.ai.tools.create_note import create_note_handler
    from app.ai.tools.update_note import update_note_handler

    created = await create_note_handler({"content": "Original content"}, ctx)
    try:
        result = await update_note_handler({"note_id": created["id"], "content": "Changed content"}, ctx)

        # Exact key set the pre-migration tool returned — proposal-based
        # updates have no action_id/revert_hint (not revertable).
        assert set(result.keys()) == {"id", "version", "proposal_id", "updated", "success"}
        assert result["success"] is True
        assert result["updated"] is False
        assert result["proposal_id"] is not None
    finally:
        await ctx._async_db.execute(delete(Note).where(Note.id == UUID(created["id"])))
        await ctx._async_db.commit()


@pytest.mark.asyncio
async def test_update_note_tool_noop_same_content(ctx):
    from app.ai.tools.create_note import create_note_handler
    from app.ai.tools.update_note import update_note_handler

    created = await create_note_handler({"content": "Same content throughout"}, ctx)
    try:
        result = await update_note_handler({"note_id": created["id"], "content": "Same content throughout"}, ctx)
        assert result["proposal_id"] is None
        assert result["updated"] is False
    finally:
        await ctx._async_db.execute(delete(Note).where(Note.id == UUID(created["id"])))
        await ctx._async_db.commit()


@pytest.mark.asyncio
async def test_update_note_tool_not_found(ctx):
    from app.ai.tools.update_note import update_note_handler

    with pytest.raises(ValueError, match="not found"):
        await update_note_handler({"note_id": str(uuid4()), "content": "x"}, ctx)


# ============================================================================
# create_schedule tool
# ============================================================================

@pytest.mark.asyncio
async def test_create_schedule_tool_response_shape_unchanged(ctx, sync_db):
    from app.ai.tools.create_schedule import create_schedule_handler

    now = datetime.now(timezone.utc)
    result = await create_schedule_handler(
        {
            "title": "Migrated Tool Meeting",
            "type": "PERSONAL",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
        },
        ctx,
    )
    try:
        assert set(result.keys()) == {
            "id", "title", "start_time", "end_time", "recurrence", "created_at", "action_id", "revert_hint", "success",
        }
        assert result["success"] is True
        assert result["title"] == "Migrated Tool Meeting"
        assert result["action_id"] is not None
        assert "Google Calendar" in result["revert_hint"]
    finally:
        sync_db.query(Schedule).filter(Schedule.id == UUID(result["id"])).delete()
        sync_db.commit()


@pytest.mark.asyncio
async def test_create_schedule_tool_rejects_z_suffix(ctx):
    from app.ai.tools.create_schedule import create_schedule_handler

    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="timezone offset"):
        await create_schedule_handler(
            {
                "title": "Bad TZ",
                "type": "PERSONAL",
                "start_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_time": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            ctx,
        )


@pytest.mark.asyncio
async def test_create_schedule_tool_revert_via_tool(ctx, sync_db):
    from app.ai.tools.create_schedule import create_schedule_handler
    from app.ai.tools.revert_action import revert_action_handler
    from app.services.schedule_service import ScheduleService

    now = datetime.now(timezone.utc)
    created = await create_schedule_handler(
        {
            "title": "Revert Me Via Tool",
            "type": "PERSONAL",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
        },
        ctx,
    )

    service = ScheduleService(sync_db)
    assert service.get_schedule_by_id(UUID(created["id"]), ctx.user_id) is not None

    revert_result = await revert_action_handler({"action_id": created["action_id"]}, ctx)
    assert revert_result["success"] is True
    assert service.get_schedule_by_id(UUID(created["id"]), ctx.user_id) is None


# ============================================================================
# update_schedule tool
# ============================================================================

@pytest.mark.asyncio
async def test_update_schedule_tool_response_shape_unchanged(ctx, sync_db):
    from app.services.schedule_service import ScheduleService
    from app.models import ScheduleType
    from app.ai.tools.update_schedule import update_schedule_handler

    now = datetime.now(timezone.utc)
    schedule = ScheduleService(sync_db).create_schedule_simple(
        user_id=ctx.user_id, title="Before Update", schedule_type=ScheduleType.PERSONAL,
        start_time=now + timedelta(hours=1), end_time=now + timedelta(hours=2),
    )
    try:
        result = await update_schedule_handler(
            {"schedule_id": str(schedule.id), "title": "After Update"}, ctx,
        )

        # Exact key set the pre-migration tool returned, including
        # "prev_fields" (kept for backward-compat) but NOT "prev_state"
        # (CommandRegistry-internal, stripped by the tool wrapper).
        assert set(result.keys()) == {
            "id", "title", "start_time", "end_time", "is_completed", "updated_at",
            "prev_fields", "action_id", "revert_hint", "success",
        }
        assert result["success"] is True
        assert result["title"] == "After Update"
        assert result["prev_fields"]["title"] == "Before Update"
        assert result["action_id"] is not None
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


@pytest.mark.asyncio
async def test_update_schedule_tool_revert_restores_fields(ctx, sync_db):
    from app.services.schedule_service import ScheduleService
    from app.models import ScheduleType
    from app.ai.tools.update_schedule import update_schedule_handler
    from app.ai.tools.revert_action import revert_action_handler

    now = datetime.now(timezone.utc)
    service = ScheduleService(sync_db)
    schedule = service.create_schedule_simple(
        user_id=ctx.user_id, title="Original", schedule_type=ScheduleType.PERSONAL,
        start_time=now + timedelta(hours=1), end_time=now + timedelta(hours=2),
    )
    try:
        result = await update_schedule_handler({"schedule_id": str(schedule.id), "title": "Modified"}, ctx)

        revert_result = await revert_action_handler({"action_id": result["action_id"]}, ctx)
        assert revert_result["success"] is True

        sync_db.expire_all()
        restored = service.get_schedule_by_id(schedule.id, ctx.user_id)
        assert restored.title == "Original"
    finally:
        sync_db.query(Schedule).filter(Schedule.id == schedule.id).delete()
        sync_db.commit()


# ============================================================================
# Cross-cutting
# ============================================================================

@pytest.mark.asyncio
async def test_all_six_commands_registered():
    """app/ai/agents/__init__.py auto-registers commands on import — this
    test module already triggered that import chain via app.ai.tools.*."""
    commands = {c["name"]: c for c in get_command_registry().list_commands()}

    # Subset, not equality: the registry is global and grows with each new
    # domain. What this test owns is the six commands the tool migration
    # produced, and their revertable flags.
    assert {
        "note.create", "note.update", "note.delete",
        "schedule.create", "schedule.update", "schedule.delete",
    } <= set(commands.keys())
    assert commands["note.update"]["revertable"] is False
    for name in ("note.create", "note.delete", "schedule.create", "schedule.update", "schedule.delete"):
        assert commands[name]["revertable"] is True


def test_verify_tool_migration_script_passes():
    script = Path(__file__).resolve().parents[2] / "scripts" / "verify_tool_migration.py"
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "All mutating tools use CommandRegistry" in proc.stdout


@pytest.mark.asyncio
async def test_a_failing_audit_write_cannot_break_the_caller(async_db):
    """A best-effort write must not be able to break the request it rode in on.

    `action_history` doesn't exist in this database, so every revertable
    command's snapshot INSERT fails. That failure used to be "handled" by
    rolling back the **caller's** session — which expires every ORM object it
    holds. The agent's session holds the live conversation, so the next
    `conv.id` raised MissingGreenlet and the chat turn returned 500 *after*
    the user's task had already been created: an error message for work that
    succeeded.

    The audit write now uses its own session, so the caller's objects survive
    whatever happens to it.
    """
    from app.ai.agents.action_snapshot_store import ActionSnapshot, get_snapshot_store
    from app.models import AgentConversation

    conversation = AgentConversation(user_id=TEST_USER_ID, title="[audit-isolation] conv")
    async_db.add(conversation)
    await async_db.commit()
    await async_db.refresh(conversation)
    conversation_id = conversation.id

    # Snapshot save runs its (failing) INSERT while the caller holds `conversation`.
    await get_snapshot_store().save(
        ActionSnapshot(
            tool_name="task.create",
            user_id=str(TEST_USER_ID),
            conversation_id=str(conversation_id),
            snapshot={"task_id": str(uuid4())},
            action_id=str(uuid4()),
        ),
        db_session=async_db,
    )

    # The caller's object is still usable — this is the access that used to blow up.
    assert conversation.id == conversation_id
    assert conversation.title == "[audit-isolation] conv"

    await async_db.execute(
        delete(AgentConversation).where(AgentConversation.id == conversation_id)
    )
    await async_db.commit()
