"""
Integration tests for Milestone 2.9 — Attention Log.

Runs against the real dev Postgres, reusing the seeded user (same convention
as test_tasks.py). Rows are identified by a per-run `REASON_PREFIX` and
deleted in teardown.

The two milestones this exists to prove:

  M4  the same task surfaced twice for the same reason → the second is
      blocked; surfaced for a *different* reason → not blocked.
  M5  a decision to stay silent leaves exactly one `level = silent` row, and
      its reason is queryable afterwards.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from tests.project_helper import personal_project_id, personal_project_id_sync
from app.models import (
    AttentionChannel,
    AttentionItemType,
    AttentionLevel,
    AttentionLog,
    AttentionResponse,
)
from app.schemas import AttentionSurfaceCreate
from app.services.attention_log import AttentionLogService

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

REASON_PREFIX = "test-2.9."


def _surface(
    item_id: UUID,
    reason_key: str,
    level: AttentionLevel = AttentionLevel.INFORM,
    item_type: AttentionItemType = AttentionItemType.TASK,
    channel: AttentionChannel = AttentionChannel.IN_APP,
) -> AttentionSurfaceCreate:
    return AttentionSurfaceCreate(
        item_type=item_type,
        item_id=item_id,
        reason_key=f"{REASON_PREFIX}{reason_key}",
        level=level,
        channel=channel,
    )


# ============================================================================
# Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        await db.execute(
            delete(AttentionLog).where(AttentionLog.reason_key.startswith(REASON_PREFIX))
        )
        await db.commit()
    await engine.dispose()


@pytest.fixture
def service(async_db):
    return AttentionLogService(async_db)


@pytest.fixture
def item_id():
    """A task id that need not exist — `item_id` has no FK on purpose, and
    the log outlives whatever it points at."""
    return uuid4()


# ============================================================================
# M4 — dedup is per (item_id, reason_key), not per item_id
# ============================================================================

@pytest.mark.asyncio
async def test_same_item_same_reason_is_suppressed(service, item_id):
    first = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    assert first.suppressed is False
    assert first.log is not None

    second = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    assert second.suppressed is True
    assert second.log is None
    assert "task.overdue" in second.reason
    assert second.dedup_window_hours == 24


@pytest.mark.asyncio
async def test_same_item_different_reason_is_not_suppressed(service, item_id, async_db):
    """The heart of M4: one task can legitimately surface for two different
    reasons. Deduplicating on item_id alone would hide the second."""
    overdue = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    blocks_goal = await service.record_surface(
        _surface(item_id, "task.blocks_goal_near_deadline"), TEST_USER_ID
    )

    assert overdue.suppressed is False
    assert blocks_goal.suppressed is False, "a different reason must not be deduped"

    rows = (await async_db.execute(
        select(AttentionLog).where(AttentionLog.item_id == item_id)
    )).scalars().all()
    assert len(rows) == 2
    assert {r.reason_key for r in rows} == {
        f"{REASON_PREFIX}task.overdue",
        f"{REASON_PREFIX}task.blocks_goal_near_deadline",
    }


@pytest.mark.asyncio
async def test_different_items_same_reason_are_independent(service):
    """Dedup keys on the pair, so two different tasks both being overdue is
    two surfacings, not one."""
    first = await service.record_surface(_surface(uuid4(), "task.overdue"), TEST_USER_ID)
    second = await service.record_surface(_surface(uuid4(), "task.overdue"), TEST_USER_ID)
    assert first.suppressed is False and second.suppressed is False


@pytest.mark.asyncio
async def test_dedup_is_scoped_per_user(service, item_id):
    """Telling one user about a shared item must not silence Cortex for
    everyone else."""
    first = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    assert first.suppressed is False

    # This user is now inside the window...
    assert (await service.record_surface(
        _surface(item_id, "task.overdue"), TEST_USER_ID
    )).suppressed is True

    # ...but the lookup is scoped by user_id, so nobody else is.
    stranger = uuid4()
    assert await service.was_recently_surfaced(
        stranger, item_id, f"{REASON_PREFIX}task.overdue"
    ) is None


@pytest.mark.asyncio
async def test_surfacing_outside_the_window_is_not_suppressed(service, item_id, async_db):
    """The window is a window, not a permanent block — an overdue task must
    become sayable again tomorrow."""
    stale = AttentionLog(
        user_id=TEST_USER_ID,
        item_type=AttentionItemType.TASK,
        item_id=item_id,
        reason_key=f"{REASON_PREFIX}task.overdue",
        level=AttentionLevel.INFORM,
        surfaced_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25),
    )
    async_db.add(stale)
    await async_db.commit()

    result = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    assert result.suppressed is False, "25h old surfacing is outside the 24h window"


@pytest.mark.asyncio
async def test_window_length_comes_from_config_not_code(async_db, item_id):
    """Same history, two window settings, two different answers."""
    wide = AttentionLogService(async_db, dedup_window_hours=24)
    narrow = AttentionLogService(async_db, dedup_window_hours=0)

    first = await wide.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    assert first.suppressed is False

    assert (await wide.record_surface(
        _surface(item_id, "task.overdue"), TEST_USER_ID
    )).suppressed is True
    # A zero-length window dedups nothing.
    assert (await narrow.record_surface(
        _surface(item_id, "task.overdue"), TEST_USER_ID
    )).suppressed is False


@pytest.mark.asyncio
async def test_should_surface_check_writes_nothing(service, item_id, async_db):
    """The Attention Gate asks before composing a message; asking must not
    itself count as a surfacing."""
    assert await service.was_recently_surfaced(
        TEST_USER_ID, item_id, f"{REASON_PREFIX}task.overdue"
    ) is None

    rows = (await async_db.execute(
        select(AttentionLog).where(AttentionLog.item_id == item_id)
    )).scalars().all()
    assert rows == []


# ============================================================================
# M5 — a silent decision is still a row
# ============================================================================

@pytest.mark.asyncio
async def test_silent_decision_leaves_exactly_one_queryable_row(service, item_id, async_db):
    """M5 verbatim: one silent decision → one `level = silent` row, and the
    reason is recoverable afterwards. Without it, "why did Cortex say
    nothing?" has no answer."""
    result = await service.record_surface(
        _surface(item_id, "task.blocks_goal_near_deadline", level=AttentionLevel.SILENT),
        TEST_USER_ID,
    )
    assert result.suppressed is False
    assert result.log is not None
    assert result.log.level is AttentionLevel.SILENT

    rows = (await async_db.execute(
        select(AttentionLog).where(AttentionLog.item_id == item_id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].level is AttentionLevel.SILENT
    assert rows[0].reason_key == f"{REASON_PREFIX}task.blocks_goal_near_deadline"
    assert rows[0].response is AttentionResponse.NO_RESPONSE
    assert rows[0].responded_at is None

    history = await service.get_item_history(TEST_USER_ID, item_id)
    assert history.surfaced is True
    assert history.reasons[0].silent_count == 1
    assert history.reasons[0].last_level is AttentionLevel.SILENT


@pytest.mark.asyncio
async def test_silent_rows_are_never_suppressed(service, item_id, async_db):
    """Two silent evaluations leave two rows. Deduplicating them would
    destroy the timeline of what Cortex considered and passed on."""
    first = await service.record_surface(
        _surface(item_id, "task.overdue", level=AttentionLevel.SILENT), TEST_USER_ID
    )
    second = await service.record_surface(
        _surface(item_id, "task.overdue", level=AttentionLevel.SILENT), TEST_USER_ID
    )
    assert first.suppressed is False and second.suppressed is False

    rows = (await async_db.execute(
        select(AttentionLog).where(AttentionLog.item_id == item_id)
    )).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_a_silent_row_does_not_gag_a_later_real_surfacing(service, item_id):
    """The interaction the doc leaves open, decided here: a silent row means
    the user was *not* told, so it must not count as a prior surfacing.
    Otherwise one quiet evaluation would silence Cortex for the whole
    window — the exact opposite of what this table is for."""
    silent = await service.record_surface(
        _surface(item_id, "task.overdue", level=AttentionLevel.SILENT), TEST_USER_ID
    )
    assert silent.suppressed is False

    spoken = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    assert spoken.suppressed is False, "a silent decision must not suppress a real one"

    # ...and now that the user has actually been told, dedup applies.
    repeat = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    assert repeat.suppressed is True


# ============================================================================
# M2 — read side
# ============================================================================

@pytest.mark.asyncio
async def test_item_history_answers_all_four_questions(service, item_id):
    """"Surfaced? why? how many times? what response?" — 2.9 M2."""
    overdue = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    await service.record_surface(
        _surface(item_id, "task.overdue", level=AttentionLevel.SILENT), TEST_USER_ID
    )
    await service.record_surface(_surface(item_id, "task.blocks_goal_near_deadline"), TEST_USER_ID)
    await service.record_response(overdue.log.id, TEST_USER_ID, AttentionResponse.ACCEPTED)

    history = await service.get_item_history(TEST_USER_ID, item_id)

    assert history.surfaced is True
    assert history.total_surfacings == 3
    by_reason = {r.reason_key: r for r in history.reasons}
    assert set(by_reason) == {
        f"{REASON_PREFIX}task.overdue",
        f"{REASON_PREFIX}task.blocks_goal_near_deadline",
    }

    overdue_summary = by_reason[f"{REASON_PREFIX}task.overdue"]
    assert overdue_summary.surface_count == 2      # counted per reason, not per item
    assert overdue_summary.silent_count == 1
    assert overdue_summary.responses["accepted"] == 1
    assert overdue_summary.responses["no_response"] == 1


@pytest.mark.asyncio
async def test_history_of_a_never_surfaced_item_is_empty_not_an_error(service):
    history = await service.get_item_history(TEST_USER_ID, uuid4())
    assert history.surfaced is False
    assert history.total_surfacings == 0
    assert history.reasons == []


@pytest.mark.asyncio
async def test_record_response_stamps_responded_at(service, item_id):
    result = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    assert result.log.response is AttentionResponse.NO_RESPONSE
    assert result.log.responded_at is None

    updated = await service.record_response(
        result.log.id, TEST_USER_ID, AttentionResponse.DISMISSED
    )
    assert updated.response is AttentionResponse.DISMISSED
    assert updated.responded_at is not None


@pytest.mark.asyncio
async def test_logs_are_scoped_to_their_owner(service, item_id):
    result = await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    stranger = uuid4()

    assert await service.get_log(result.log.id, stranger) is None
    assert await service.record_response(
        result.log.id, stranger, AttentionResponse.ACCEPTED
    ) is None


@pytest.mark.asyncio
async def test_list_logs_can_isolate_the_silent_ones(service, item_id):
    """The debugging query: "what did Cortex decide not to tell me?"."""
    await service.record_surface(_surface(item_id, "task.overdue"), TEST_USER_ID)
    await service.record_surface(
        _surface(uuid4(), "schedule.conflict", level=AttentionLevel.SILENT,
                 item_type=AttentionItemType.SCHEDULE),
        TEST_USER_ID,
    )

    silent = await service.list_logs(TEST_USER_ID, level=AttentionLevel.SILENT)
    ours = [r for r in silent if r.reason_key.startswith(REASON_PREFIX)]
    assert len(ours) == 1
    assert ours[0].reason_key == f"{REASON_PREFIX}schedule.conflict"
    assert ours[0].item_type is AttentionItemType.SCHEDULE


@pytest.mark.asyncio
async def test_log_survives_the_item_it_points_at(service, async_db):
    """`item_id` has no FK by design: the record that Cortex nagged about
    something must outlive that something, or 6.9 loses the history it's
    meant to learn from."""
    from app.models import Task, TaskStatus

    task = Task(
        project_id=await personal_project_id(async_db, TEST_USER_ID),
        user_id=TEST_USER_ID, title="[test-2.9] doomed task", status=TaskStatus.TODO,
    )
    async_db.add(task)
    await async_db.commit()
    await async_db.refresh(task)
    task_id = task.id

    result = await service.record_surface(
        _surface(task_id, "task.overdue", item_type=AttentionItemType.TASK), TEST_USER_ID
    )
    assert result.suppressed is False

    await async_db.delete(task)
    await async_db.commit()

    surviving = (await async_db.execute(
        select(AttentionLog).where(AttentionLog.item_id == task_id)
    )).scalars().all()
    assert len(surviving) == 1
    assert surviving[0].reason_key == f"{REASON_PREFIX}task.overdue"


# ============================================================================
# REST API (M2)
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
async def test_api_surface_dedup_and_read_back(api_client, item_id):
    body = {
        "item_type": "task",
        "item_id": str(item_id),
        "reason_key": f"{REASON_PREFIX}task.overdue",
        "level": "inform",
    }

    first = await api_client.post("/attention-log", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["suppressed"] is False
    log_id = first.json()["log"]["id"]

    # Suppression is a normal answer, not an error status.
    second = await api_client.post("/attention-log", json=body)
    assert second.status_code == 200
    assert second.json()["suppressed"] is True
    assert second.json()["log"] is None
    assert second.json()["dedup_window_hours"] == 24

    other_reason = {**body, "reason_key": f"{REASON_PREFIX}task.blocks_goal_near_deadline"}
    assert (await api_client.post("/attention-log", json=other_reason)).json()["suppressed"] is False

    history = await api_client.get(f"/attention-log/items/{item_id}")
    assert history.status_code == 200
    assert history.json()["total_surfacings"] == 2
    assert len(history.json()["reasons"]) == 2

    responded = await api_client.post(
        f"/attention-log/{log_id}/response", json={"response": "accepted"}
    )
    assert responded.status_code == 200
    assert responded.json()["response"] == "accepted"
    assert responded.json()["responded_at"] is not None


@pytest.mark.asyncio
async def test_api_records_a_silent_decision(api_client, item_id):
    created = await api_client.post(
        "/attention-log",
        json={
            "item_type": "task",
            "item_id": str(item_id),
            "reason_key": f"{REASON_PREFIX}task.overdue",
            "level": "silent",
        },
    )
    assert created.status_code == 200
    assert created.json()["suppressed"] is False
    assert created.json()["log"]["level"] == "silent"

    listed = await api_client.get("/attention-log", params={"level": "silent"})
    assert str(item_id) in {row["item_id"] for row in listed.json()}


@pytest.mark.asyncio
async def test_api_should_surface_dry_run(api_client, item_id):
    reason = f"{REASON_PREFIX}task.overdue"

    before = await api_client.get(
        f"/attention-log/items/{item_id}/should-surface", params={"reason_key": reason}
    )
    assert before.status_code == 200
    assert before.json()["suppressed"] is False

    # The dry run wrote nothing, so the first real surfacing still goes through.
    assert (await api_client.post("/attention-log", json={
        "item_type": "task", "item_id": str(item_id), "reason_key": reason, "level": "inform",
    })).json()["suppressed"] is False

    after = await api_client.get(
        f"/attention-log/items/{item_id}/should-surface", params={"reason_key": reason}
    )
    assert after.json()["suppressed"] is True
    assert after.json()["log"] is not None


@pytest.mark.asyncio
async def test_api_rejects_no_response_as_a_response(api_client, item_id):
    created = await api_client.post("/attention-log", json={
        "item_type": "task",
        "item_id": str(item_id),
        "reason_key": f"{REASON_PREFIX}task.overdue",
        "level": "inform",
    })
    log_id = created.json()["log"]["id"]

    rejected = await api_client.post(
        f"/attention-log/{log_id}/response", json={"response": "no_response"}
    )
    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_api_rejects_unknown_enum_values(api_client, item_id):
    base = {
        "item_type": "task",
        "item_id": str(item_id),
        "reason_key": f"{REASON_PREFIX}task.overdue",
        "level": "inform",
    }
    assert (await api_client.post("/attention-log", json={**base, "level": "shout"})).status_code == 422
    assert (await api_client.post("/attention-log", json={**base, "item_type": "note"})).status_code == 422
    assert (await api_client.post("/attention-log", json={**base, "channel": "sms"})).status_code == 422
    assert (await api_client.post("/attention-log", json={**base, "reason_key": "  "})).status_code == 422


@pytest.mark.asyncio
async def test_api_unknown_log_returns_404(api_client):
    missing = uuid4()
    assert (await api_client.get(f"/attention-log/{missing}")).status_code == 404
    assert (await api_client.post(
        f"/attention-log/{missing}/response", json={"response": "accepted"}
    )).status_code == 404


@pytest.mark.asyncio
async def test_api_telegram_and_email_channels_are_accepted_now(api_client, item_id):
    """No delivery path until Phase 5, but the enum accepts them today so
    wiring one up later needs no migration."""
    for channel in ("telegram", "email"):
        created = await api_client.post("/attention-log", json={
            "item_type": "task",
            "item_id": str(uuid4()),
            "reason_key": f"{REASON_PREFIX}task.overdue",
            "level": "inform",
            "channel": channel,
        })
        assert created.status_code == 200, created.text
        assert created.json()["log"]["channel"] == channel
