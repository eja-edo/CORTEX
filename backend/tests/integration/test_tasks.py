"""
Integration tests for Milestone 2.5 — Task Data Model + API.

Runs against the real dev Postgres + Redis, reusing the seeded user. Every
row created here is titled with `TITLE_PREFIX` and hard-deleted in teardown.

Covers:
  M1  the table and its FKs
  M2  CRUD API + `task.create/update/complete` commands
  M3  the status state machine — enforced in the *service*, so every entry
      point inherits it
  M4  `task.created/updated/completed/deleted`, one event per mutation
  M5  `priority`/`description`, verified against the live OpenAPI schema
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.ai.agents.tool_context import ToolContext
from app.commands.args import TaskCompleteArgs, TaskCreateArgs, TaskUpdateArgs
from app.commands.handlers.task_commands import (
    task_complete_handler,
    task_create_handler,
    task_create_revert_handler,
    task_restore_revert_handler,
    task_update_handler,
)
from app.commands.registry import CommandRegistry, get_command_registry
from app.commands.schemas import Command, PermissionScope
from app.events.event_bus import EventBus, reset_event_bus
from app.events.schemas import EventEnvelope
from app.models import Schedule, ScheduleType, Task, TaskPriority, TaskStatus
from app.schemas import TaskCreate, TaskUpdate
from app.services.tasks import InvalidTaskTransition, TaskService

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

TITLE_PREFIX = "[test-2.5] "


# ============================================================================
# Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def async_db():
    """Dedicated engine per test — see test_core_events.py's `async_db`."""
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        # Tasks first: they FK to schedules.
        await db.execute(delete(Task).where(Task.title.startswith(TITLE_PREFIX)))
        await db.execute(delete(Schedule).where(Schedule.title.startswith(TITLE_PREFIX)))
        await db.commit()
    await engine.dispose()


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
async def ctx(async_db):
    context = ToolContext(user_id=TEST_USER_ID, async_db=async_db)
    yield context
    context.close()


@pytest.fixture
def registry():
    """A fresh, LOCAL CommandRegistry — not the global singleton."""
    reg = CommandRegistry()
    reg.register(
        name="task.create",
        description="Create a task",
        args_schema=TaskCreateArgs,
        handler=task_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_create_revert_handler,
    )
    reg.register(
        name="task.update",
        description="Update a task",
        args_schema=TaskUpdateArgs,
        handler=task_update_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_restore_revert_handler,
    )
    reg.register(
        name="task.complete",
        description="Mark a task as done",
        args_schema=TaskCompleteArgs,
        handler=task_complete_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_restore_revert_handler,
    )
    return reg


async def _wait_for_event(received: list[EventEnvelope], event_type: str, timeout: float = 3.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for event in received:
            if event.type == event_type:
                return event
        await asyncio.sleep(0.05)
    return None


# ============================================================================
# Service CRUD + events (M4)
# ============================================================================

@pytest.mark.asyncio
async def test_create_task_persists_and_publishes(async_db, event_subscriber):
    service = TaskService(async_db)
    due = date.today() + timedelta(days=4)

    task = await service.create_task(
        payload=TaskCreate(
            title=f"{TITLE_PREFIX}Write API spec",
            due_date=due,
            priority=TaskPriority.HIGH,
        ),
        user_id=TEST_USER_ID,
    )

    assert task.status is TaskStatus.TODO  # default
    # due_date is a DateTime now (optional time-of-day) — a bare `date` in
    # lands at midnight of that day, so compare the day, not exact equality.
    assert task.due_date.date() == due
    assert task.priority is TaskPriority.HIGH
    assert task.related_event_id is None and task.source_conversation_id is None

    event = await _wait_for_event(event_subscriber, "task.created")
    assert event is not None, "task.created was never published"
    assert event.payload["task_id"] == str(task.id)
    assert event.payload["priority"] == "high"
    assert event.payload["due_date"].startswith(due.isoformat())


@pytest.mark.asyncio
async def test_completion_publishes_task_completed_and_not_task_updated(
    async_db, event_subscriber
):
    """One event per mutation — a subscriber must not have to deduplicate a
    completion that also arrived as an update."""
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Finish me"), user_id=TEST_USER_ID
    )
    event_subscriber.clear()

    completed = await service.complete_task(task.id, TEST_USER_ID)
    assert completed.status is TaskStatus.DONE

    event = await _wait_for_event(event_subscriber, "task.completed")
    assert event is not None, "task.completed was never published"
    assert [e.type for e in event_subscriber if e.type == "task.updated"] == []


@pytest.mark.asyncio
async def test_update_publishes_fields_changed(async_db, event_subscriber):
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Rename me"), user_id=TEST_USER_ID
    )
    event_subscriber.clear()

    await service.update_task(
        task.id, TEST_USER_ID, TaskUpdate(title=f"{TITLE_PREFIX}Renamed", status=TaskStatus.IN_PROGRESS)
    )

    event = await _wait_for_event(event_subscriber, "task.updated")
    assert event is not None
    assert event.payload["fields_changed"] == ["status", "title"]
    assert event.payload["status"] == "in_progress"


@pytest.mark.asyncio
async def test_delete_publishes_task_deleted(async_db, event_subscriber):
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Delete me"), user_id=TEST_USER_ID
    )
    event_subscriber.clear()

    assert await service.delete_task(task.id, TEST_USER_ID) is True

    event = await _wait_for_event(event_subscriber, "task.deleted")
    assert event is not None, "task.deleted was never published"
    assert event.payload["task_id"] == str(task.id)
    assert (await async_db.execute(select(Task).where(Task.id == task.id))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_tasks_are_scoped_to_their_owner(async_db):
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Private"), user_id=TEST_USER_ID
    )
    stranger = uuid4()

    assert await service.get_task(task.id, stranger) is None
    assert await service.update_task(task.id, stranger, TaskUpdate(title="hijacked")) is None
    assert await service.complete_task(task.id, stranger) is None
    assert await service.delete_task(task.id, stranger) is False


@pytest.mark.asyncio
async def test_filters(async_db):
    schedule = Schedule(
        user_id=TEST_USER_ID,
        title=f"{TITLE_PREFIX}Filter event",
        type=ScheduleType.PERSONAL,
        start_time=datetime.now(timezone.utc) + timedelta(days=1),
        end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
    )
    async_db.add(schedule)
    await async_db.commit()
    await async_db.refresh(schedule)

    service = TaskService(async_db)
    attached = await service.create_task(
        payload=TaskCreate(
            title=f"{TITLE_PREFIX}Attached",
            related_event_id=schedule.id,
            due_date=date.today() + timedelta(days=1),
        ),
        user_id=TEST_USER_ID,
    )
    loose = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Loose", due_date=date.today() + timedelta(days=90)),
        user_id=TEST_USER_ID,
    )

    by_event = {t.id for t in await service.get_tasks(TEST_USER_ID, related_event_id=schedule.id)}
    assert by_event == {attached.id}

    soon = {t.id for t in await service.get_tasks(
        TEST_USER_ID, due_before=date.today() + timedelta(days=7)
    )}
    assert attached.id in soon and loose.id not in soon


# ============================================================================
# State machine (M3) — enforced in the service
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,requested",
    [
        (TaskStatus.DONE, TaskStatus.IN_PROGRESS),
        (TaskStatus.CANCELLED, TaskStatus.IN_PROGRESS),
        (TaskStatus.CANCELLED, TaskStatus.DONE),
    ],
)
async def test_service_rejects_illegal_transitions(async_db, start, requested):
    """Rejected at the service, not just the route — the AI's command path
    and 2.3/3.2's internal callers never touch a FastAPI route."""
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Machine", status=start), user_id=TEST_USER_ID
    )

    with pytest.raises(InvalidTaskTransition):
        await service.update_task(task.id, TEST_USER_ID, TaskUpdate(status=requested))

    await async_db.refresh(task)
    assert task.status is start  # nothing was written


@pytest.mark.asyncio
async def test_full_legal_lifecycle(async_db):
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Lifecycle"), user_id=TEST_USER_ID
    )

    for status in (
        TaskStatus.IN_PROGRESS,   # todo → in_progress
        TaskStatus.DONE,          # in_progress → done
        TaskStatus.TODO,          # done → todo (reopen)
        TaskStatus.DONE,          # todo → done (skip in_progress)
        TaskStatus.CANCELLED,     # done → cancelled
        TaskStatus.TODO,          # cancelled → todo (restore)
    ):
        updated = await service.update_task(task.id, TEST_USER_ID, TaskUpdate(status=status))
        assert updated.status is status


@pytest.mark.asyncio
async def test_completing_twice_is_idempotent(async_db, event_subscriber):
    """2.6's checklist will send this — a double tick is not an error."""
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Double tick"), user_id=TEST_USER_ID
    )

    first = await service.complete_task(task.id, TEST_USER_ID)
    assert first.status is TaskStatus.DONE
    event_subscriber.clear()

    second = await service.complete_task(task.id, TEST_USER_ID)
    assert second.status is TaskStatus.DONE

    # ...but it doesn't re-announce a completion that already happened.
    assert await _wait_for_event(event_subscriber, "task.completed", timeout=0.6) is None


@pytest.mark.asyncio
async def test_cancelled_task_cannot_be_completed(async_db):
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Abandoned", status=TaskStatus.CANCELLED),
        user_id=TEST_USER_ID,
    )
    with pytest.raises(InvalidTaskTransition):
        await service.complete_task(task.id, TEST_USER_ID)


# ============================================================================
# Table / FK behavior (M1)
# ============================================================================

@pytest.mark.asyncio
async def test_deleting_an_event_detaches_its_checklist(async_db):
    """The 2.6 checklist case: deleting a meeting must not delete the work
    items it spawned."""
    schedule = Schedule(
        user_id=TEST_USER_ID,
        title=f"{TITLE_PREFIX}Team sync",
        type=ScheduleType.PERSONAL,
        start_time=datetime.now(timezone.utc) + timedelta(days=1),
        end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
    )
    async_db.add(schedule)
    await async_db.commit()
    await async_db.refresh(schedule)

    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Checklist item", related_event_id=schedule.id),
        user_id=TEST_USER_ID,
    )

    await async_db.delete(schedule)
    await async_db.commit()

    await async_db.refresh(task)
    assert task.related_event_id is None


@pytest.mark.asyncio
async def test_no_task_is_ever_written_into_schedules(async_db):
    """The whole point of the separate table: `schedules` keeps meaning
    "time that is actually occupied", which 3.3 and 6.2 depend on."""
    before = (await async_db.execute(
        text("SELECT COUNT(*) FROM schedules WHERE user_id = :uid"), {"uid": TEST_USER_ID}
    )).scalar_one()

    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(
            title=f"{TITLE_PREFIX}Not a meeting",
            due_date=date.today(),
        ),
        user_id=TEST_USER_ID,
    )
    await service.complete_task(task.id, TEST_USER_ID)

    after = (await async_db.execute(
        text("SELECT COUNT(*) FROM schedules WHERE user_id = :uid"), {"uid": TEST_USER_ID}
    )).scalar_one()
    assert after == before


# ============================================================================
# Commands (M2)
# ============================================================================

def test_task_commands_are_registered_globally():
    import app.commands.handlers  # noqa: F401 — triggers registration

    names = {c["name"] for c in get_command_registry().list_commands()}
    assert {"task.create", "task.update", "task.complete"} <= names


@pytest.mark.asyncio
async def test_task_create_command(registry, ctx, async_db, event_subscriber):
    result = await registry.execute(
        Command(
            command_name="task.create",
            args={
                "title": f"{TITLE_PREFIX}Via command",
                "due_date": "2026-11-30",
                "priority": "high",
            },
            requested_by=TEST_USER_ID,
        ),
        ctx,
    )

    assert result.success is True, result.error
    assert result.data["status"] == "todo"
    assert result.action_id is not None

    stored = (await async_db.execute(
        select(Task).where(Task.id == UUID(result.data["id"]))
    )).scalar_one()
    assert stored.due_date.date() == date(2026, 11, 30)
    assert stored.priority is TaskPriority.HIGH

    assert await _wait_for_event(event_subscriber, "task.created") is not None


@pytest.mark.asyncio
async def test_task_complete_command(registry, ctx, async_db, event_subscriber):
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Tick me"), user_id=TEST_USER_ID
    )
    event_subscriber.clear()

    result = await registry.execute(
        Command(
            command_name="task.complete",
            args={"task_id": str(task.id)},
            requested_by=TEST_USER_ID,
        ),
        ctx,
    )

    assert result.success is True, result.error
    assert result.data["status"] == "done"
    assert result.data["completed"] is True

    await async_db.refresh(task)
    assert task.status is TaskStatus.DONE
    assert await _wait_for_event(event_subscriber, "task.completed") is not None


@pytest.mark.asyncio
async def test_command_path_enforces_the_state_machine(registry, ctx, async_db):
    """The AI can't sidestep the rules by going through a command."""
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}Cancelled", status=TaskStatus.CANCELLED),
        user_id=TEST_USER_ID,
    )

    result = await registry.execute(
        Command(
            command_name="task.complete",
            args={"task_id": str(task.id)},
            requested_by=TEST_USER_ID,
        ),
        ctx,
    )

    assert result.success is False
    assert "invalid task status transition" in result.error.lower()

    await async_db.refresh(task)
    assert task.status is TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_task_update_command_leaves_omitted_fields_alone(registry, ctx, async_db):
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(
            title=f"{TITLE_PREFIX}Keep my fields",
            due_date=date(2026, 9, 1),
            priority=TaskPriority.MEDIUM,
        ),
        user_id=TEST_USER_ID,
    )

    result = await registry.execute(
        Command(
            command_name="task.update",
            args={"task_id": str(task.id), "status": "in_progress"},
            requested_by=TEST_USER_ID,
        ),
        ctx,
    )

    assert result.success is True, result.error
    assert result.data["fields_changed"] == ["status"]

    await async_db.refresh(task)
    assert task.status is TaskStatus.IN_PROGRESS
    assert task.title == f"{TITLE_PREFIX}Keep my fields"
    assert task.due_date.date() == date(2026, 9, 1)
    assert task.priority is TaskPriority.MEDIUM


@pytest.mark.asyncio
async def test_task_create_command_is_revertable(registry, ctx, async_db):
    create = await registry.execute(
        Command(
            command_name="task.create",
            args={"title": f"{TITLE_PREFIX}Oops"},
            requested_by=TEST_USER_ID,
        ),
        ctx,
    )
    assert create.success is True, create.error
    task_id = UUID(create.data["id"])

    revert = await registry.revert_command(create.action_id, ctx)
    assert revert.success is True, revert.error
    assert (await async_db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_task_complete_command_revert_reopens_the_task(registry, ctx, async_db):
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(
            title=f"{TITLE_PREFIX}Undo me", due_date=date(2026, 5, 5), priority=TaskPriority.LOW
        ),
        user_id=TEST_USER_ID,
    )

    complete = await registry.execute(
        Command(
            command_name="task.complete",
            args={"task_id": str(task.id)},
            requested_by=TEST_USER_ID,
        ),
        ctx,
    )
    assert complete.success is True, complete.error

    revert = await registry.revert_command(complete.action_id, ctx)
    assert revert.success is True, revert.error

    await async_db.refresh(task)
    assert task.status is TaskStatus.TODO  # done → todo is a legal transition
    assert task.due_date.date() == date(2026, 5, 5)
    assert task.priority is TaskPriority.LOW


# ============================================================================
# REST API (M2) + M5
# ============================================================================

@pytest_asyncio.fixture
async def api_client(async_db):
    from app import app
    from app.database_async import get_async_db
    from app.dependencies import get_current_user_or_internal

    class _StubUser:
        id = TEST_USER_ID

    async def _override_db():
        yield async_db

    app.dependency_overrides[get_current_user_or_internal] = lambda: _StubUser()
    app.dependency_overrides[get_async_db] = _override_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api") as client:
        yield client

    app.dependency_overrides.pop(get_current_user_or_internal, None)
    app.dependency_overrides.pop(get_async_db, None)


@pytest.mark.asyncio
async def test_api_task_crud_roundtrip(api_client):
    created = await api_client.post(
        "/tasks",
        json={
            "title": f"{TITLE_PREFIX}API task",
            "due_date": "2026-12-31",
            "priority": "high",
            "description": "Some extra detail",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    task_id = body["id"]
    assert body["status"] == "todo"
    assert body["priority"] == "high"
    assert body["description"] == "Some extra detail"

    assert (await api_client.get(f"/tasks/{task_id}")).json()["title"] == f"{TITLE_PREFIX}API task"

    patched = await api_client.patch(f"/tasks/{task_id}", json={"status": "in_progress"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"

    completed = await api_client.post(f"/tasks/{task_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"

    deleted = await api_client.delete(f"/tasks/{task_id}")
    assert deleted.status_code == 204
    assert (await api_client.get(f"/tasks/{task_id}")).status_code == 404


@pytest.mark.asyncio
async def test_api_illegal_transition_is_409(api_client):
    created = await api_client.post(
        "/tasks", json={"title": f"{TITLE_PREFIX}Cancelled API", "status": "cancelled"}
    )
    task_id = created.json()["id"]

    conflict = await api_client.patch(f"/tasks/{task_id}", json={"status": "done"})
    # 409, not 422: the body is valid, the task's state is what forbids it.
    assert conflict.status_code == 409
    assert "transition" in conflict.json()["detail"].lower()

    assert (await api_client.post(f"/tasks/{task_id}/complete")).status_code == 409


@pytest.mark.asyncio
async def test_api_rejects_unknown_status_and_blank_title(api_client):
    assert (await api_client.post(
        "/tasks", json={"title": f"{TITLE_PREFIX}bad", "status": "blocked"}
    )).status_code == 422
    assert (await api_client.post("/tasks", json={"title": "   "})).status_code == 422


@pytest.mark.asyncio
async def test_api_unknown_task_returns_404(api_client):
    missing = uuid4()
    assert (await api_client.get(f"/tasks/{missing}")).status_code == 404
    assert (await api_client.patch(f"/tasks/{missing}", json={"title": "x"})).status_code == 404
    assert (await api_client.post(f"/tasks/{missing}/complete")).status_code == 404
    assert (await api_client.delete(f"/tasks/{missing}")).status_code == 404


@pytest.mark.asyncio
async def test_openapi_task_schemas_expose_priority(api_client):
    """M5 against the contract the UI actually consumes: `priority` is a
    real, user-set field now and must reach the client through /tasks."""
    # Absolute URL: the client's base_url is /api, the schema document isn't.
    spec = (await api_client.get("http://test/openapi.json")).json()

    task_schemas = {
        name: schema
        for name, schema in spec["components"]["schemas"].items()
        if name.startswith("Task")
    }
    assert task_schemas, "no Task schemas in the OpenAPI document"
    assert any("priority" in schema.get("properties", {}) for schema in task_schemas.values())


# ============================================================================
# completed_at + cascade-complete (Home widget "still shows next day" fix +
# "complete this and all its sub-tasks" confirm-dialog flow)
# ============================================================================

@pytest.mark.asyncio
async def test_completed_at_set_on_completion_and_cleared_on_reopen(async_db):
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}completed_at"), user_id=TEST_USER_ID,
    )
    assert task.completed_at is None

    done = await service.complete_task(task.id, TEST_USER_ID)
    assert done.completed_at is not None

    reopened = await service.update_task(task.id, TEST_USER_ID, TaskUpdate(status=TaskStatus.TODO))
    assert reopened.completed_at is None


@pytest.mark.asyncio
async def test_create_task_already_done_gets_a_completed_at(async_db):
    """Logging already-finished work (`create_task` with `status=done`)
    still needs a real `completed_at`, or it would never age out of a "done
    today" list on the day it's actually logged."""
    service = TaskService(async_db)
    task = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}logged done", status=TaskStatus.DONE), user_id=TEST_USER_ID,
    )
    assert task.status is TaskStatus.DONE
    assert task.completed_at is not None


@pytest.mark.asyncio
async def test_complete_task_cascade_completes_nested_subtasks(async_db):
    """Ticking a parent with its own checklist, after the user confirms
    "yes, all of it's done" — completes the parent and every descendant,
    however deeply nested, but leaves a cancelled descendant alone."""
    service = TaskService(async_db)

    root = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}root"), user_id=TEST_USER_ID,
    )
    child = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}child", parent_task_id=root.id), user_id=TEST_USER_ID,
    )
    grandchild = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}grandchild", parent_task_id=child.id), user_id=TEST_USER_ID,
    )
    cancelled_child = await service.create_task(
        payload=TaskCreate(title=f"{TITLE_PREFIX}cancelled child", parent_task_id=root.id), user_id=TEST_USER_ID,
    )
    cancelled_child = await service.update_task(
        cancelled_child.id, TEST_USER_ID, TaskUpdate(status=TaskStatus.CANCELLED),
    )

    updated = await service.complete_task_cascade(root.id, TEST_USER_ID)
    updated_by_id = {t.id: t for t in updated}

    assert updated_by_id[root.id].status is TaskStatus.DONE
    assert updated_by_id[root.id].completed_at is not None
    assert updated_by_id[child.id].status is TaskStatus.DONE
    assert updated_by_id[grandchild.id].status is TaskStatus.DONE
    # The cancelled sibling can't legally reach `done` — left untouched,
    # not failing the whole cascade.
    assert cancelled_child.id not in updated_by_id

    still_cancelled = await service.get_task(cancelled_child.id, TEST_USER_ID)
    assert still_cancelled.status is TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_api_complete_with_subtasks_cascades(api_client):
    root = (await api_client.post("/tasks", json={"title": f"{TITLE_PREFIX}api root"})).json()
    child = (await api_client.post(
        "/tasks", json={"title": f"{TITLE_PREFIX}api child", "parent_task_id": root["id"]},
    )).json()

    resp = await api_client.post(f"/tasks/{root['id']}/complete_with_subtasks")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)

    by_id = {t["id"]: t for t in body}
    assert by_id[root["id"]]["status"] == "done"
    assert by_id[child["id"]]["status"] == "done"

    refetched_child = (await api_client.get(f"/tasks/{child['id']}")).json()
    assert refetched_child["status"] == "done"
