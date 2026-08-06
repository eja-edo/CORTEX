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
from app.models import Note, Schedule, User, WorkspaceMember

TEST_USER_ID = UUID("73552833-a6de-40a1-bb69-6e034ca75460")
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
async def ctx(async_db):
    context = ToolContext(user_id=TEST_USER_ID, async_db=async_db, workspace_id=TEST_WORKSPACE_ID)
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
    await async_db.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
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
        # Exact key set the pre-migration tool returned — no "result"
        # wrapper, no leaked "prev_state"/"title".
        assert set(result.keys()) == {"id", "workspace_id", "created_at", "action_id", "revert_hint", "success"}
        assert result["success"] is True
        assert result["workspace_id"] == str(TEST_WORKSPACE_ID)
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
async def test_create_note_tool_permission_denied_for_viewer(async_db, other_user_id):
    from app.ai.tools.create_note import create_note_handler

    await _add_member(async_db, TEST_WORKSPACE_ID, other_user_id, "viewer")
    other_ctx = ToolContext(user_id=other_user_id, async_db=async_db, workspace_id=TEST_WORKSPACE_ID)

    with pytest.raises(PermissionError):
        await create_note_handler({"content": "Should not be created"}, other_ctx)


@pytest.mark.asyncio
async def test_create_note_tool_permission_denied_for_non_member(async_db, other_user_id):
    from app.ai.tools.create_note import create_note_handler

    other_ctx = ToolContext(user_id=other_user_id, async_db=async_db, workspace_id=TEST_WORKSPACE_ID)

    with pytest.raises(PermissionError):
        await create_note_handler({"content": "Should not be created"}, other_ctx)


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

    assert set(commands.keys()) == {
        "note.create", "note.update", "note.delete",
        "schedule.create", "schedule.update", "schedule.delete",
    }
    assert commands["note.update"]["revertable"] is False
    for name in ("note.create", "note.delete", "schedule.create", "schedule.update", "schedule.delete"):
        assert commands[name]["revertable"] is True


def test_verify_tool_migration_script_passes():
    script = Path(__file__).resolve().parents[2] / "scripts" / "verify_tool_migration.py"
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "All mutating tools use CommandRegistry" in proc.stdout
