"""
Integration tests for Milestone 6.2 — quiet hours API + Gate integration.

The API tests use the same `dependency_overrides` pattern as
test_today.py's api_client fixture — no real JWT needed, just swap the
current-user and DB dependencies for the test session.
"""

from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.database_async import make_async_sessionmaker
from tests.project_helper import personal_project_id, personal_project_id_sync
from app.models import (
    AttentionBundleQueue,
    AttentionItemType,
    AttentionLevel,
    AttentionLog,
    Notification,
    Task,
    TaskPriority,
    TaskStatus,
    UserPreferences,
)
from app.services.attention_gate import request_attention_async
from tests.integration.isolated_user import ensure_isolated_user

TITLE_PREFIX = "[test-6.2] "
YESTERDAY = datetime.combine(date.today() - timedelta(days=1), time(9, 0))


@pytest_asyncio.fixture
async def user_id():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
    await engine.dispose()
    return uid


@pytest_asyncio.fixture
async def async_db(user_id):
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
        await db.execute(delete(AttentionBundleQueue).where(AttentionBundleQueue.user_id == user_id))
        await db.execute(delete(Notification).where(Notification.user_id == user_id))
        await db.execute(delete(AttentionLog).where(AttentionLog.user_id == user_id))
        await db.execute(delete(Task).where(Task.user_id == user_id))
        await db.execute(delete(UserPreferences).where(UserPreferences.user_id == user_id))
        await db.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(async_db, user_id):
    from app import app
    from app.database_async import get_async_db
    from app.dependencies import get_current_user_or_internal

    class _StubUser:
        id = user_id

    async def _override_db():
        yield async_db

    app.dependency_overrides[get_current_user_or_internal] = lambda: _StubUser()
    app.dependency_overrides[get_async_db] = _override_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api") as client:
        yield client

    app.dependency_overrides.pop(get_current_user_or_internal, None)
    app.dependency_overrides.pop(get_async_db, None)


# ============================================================================
# API
# ============================================================================


@pytest.mark.asyncio
async def test_get_with_no_row_returns_nulls_not_404(api_client):
    response = await api_client.get("/preferences")
    assert response.status_code == 200, response.text
    # So khớp theo *trường đang canh*, không so cả dict: thêm một tuỳ chọn
    # mới (`chat_model` là lần gần nhất) không phải là hồi quy của giờ yên
    # tĩnh, nhưng so cả dict thì nó làm đỏ ở đây.
    body = response.json()
    assert body["quiet_hours_start"] is None
    assert body["quiet_hours_end"] is None


@pytest.mark.asyncio
async def test_put_then_get_round_trips(api_client):
    put_response = await api_client.put(
        "/preferences", json={"quiet_hours_start": "22:00:00", "quiet_hours_end": "07:00:00"}
    )
    assert put_response.status_code == 200, put_response.text
    assert put_response.json()["quiet_hours_start"] == "22:00:00"

    body = (await api_client.get("/preferences")).json()
    assert body["quiet_hours_start"] == "22:00:00"
    assert body["quiet_hours_end"] == "07:00:00"


@pytest.mark.asyncio
async def test_setting_only_one_field_is_rejected(api_client):
    response = await api_client.put(
        "/preferences", json={"quiet_hours_start": "22:00:00", "quiet_hours_end": None}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_both_null_clears_quiet_hours(api_client):
    await api_client.put("/preferences", json={"quiet_hours_start": "22:00:00", "quiet_hours_end": "07:00:00"})
    response = await api_client.put("/preferences", json={"quiet_hours_start": None, "quiet_hours_end": None})
    assert response.status_code == 200
    body = response.json()
    assert body["quiet_hours_start"] is None
    assert body["quiet_hours_end"] is None


# ============================================================================
# Gate integration — quiet hours silence even without a busy schedule
# ============================================================================


async def _make_task(db, user_id, *, suffix: str, priority, due_date) -> Task:
    task = Task(
        project_id=await personal_project_id(db, user_id),
        user_id=user_id, title=f"{TITLE_PREFIX}{suffix}", status=TaskStatus.TODO,
        due_date=due_date, priority=priority,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_quiet_hours_alone_silences_a_non_critical_candidate(async_db, user_id):
    now_utc_time = datetime.now(timezone.utc).time()
    start = time((now_utc_time.hour - 1) % 24, 0)
    end = time((now_utc_time.hour + 1) % 24, 0)
    async_db.add(UserPreferences(user_id=user_id, quiet_hours_start=start, quiet_hours_end=end))
    await async_db.commit()

    task = await _make_task(async_db, user_id, suffix="quiet", priority=TaskPriority.LOW, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is None
    queued = (
        await async_db.execute(
            AttentionBundleQueue.__table__.select().where(AttentionBundleQueue.item_id == task.id)
        )
    ).fetchall()
    assert len(queued) == 1


@pytest.mark.asyncio
async def test_quiet_hours_does_not_silence_a_critical_candidate(async_db, user_id):
    now_utc_time = datetime.now(timezone.utc).time()
    start = time((now_utc_time.hour - 1) % 24, 0)
    end = time((now_utc_time.hour + 1) % 24, 0)
    async_db.add(UserPreferences(user_id=user_id, quiet_hours_start=start, quiet_hours_end=end))
    await async_db.commit()

    task = await _make_task(async_db, user_id, suffix="quiet-urgent", priority=TaskPriority.URGENT, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
    assert notification.attention_level is AttentionLevel.ASK


# ============================================================================
# Reason preferences (redesigned 4.5 / A2 follow-up) — API
# ============================================================================


@pytest.mark.asyncio
async def test_list_reasons_defaults_everything_enabled(api_client):
    response = await api_client.get("/preferences/reasons")
    assert response.status_code == 200, response.text
    reasons = response.json()
    assert len(reasons) > 0
    assert all(r["enabled"] for r in reasons)
    keys = {r["reason_key"] for r in reasons}
    assert "task.overdue" in keys
    assert "day.review" in keys


@pytest.mark.asyncio
async def test_disabling_a_reason_persists_and_only_affects_that_one(api_client):
    put_response = await api_client.put("/preferences/reasons/task.stale", json={"enabled": False})
    assert put_response.status_code == 200, put_response.text
    body = put_response.json()
    assert body["reason_key"] == "task.stale"
    assert body["base_level"] == "inform"
    assert body["enabled"] is False

    reasons = {r["reason_key"]: r["enabled"] for r in (await api_client.get("/preferences/reasons")).json()}
    assert reasons["task.stale"] is False
    assert reasons["task.overdue"] is True


@pytest.mark.asyncio
async def test_re_enabling_a_reason_clears_it(api_client):
    await api_client.put("/preferences/reasons/task.stale", json={"enabled": False})
    put_response = await api_client.put("/preferences/reasons/task.stale", json={"enabled": True})
    assert put_response.json()["enabled"] is True

    reasons = {r["reason_key"]: r["enabled"] for r in (await api_client.get("/preferences/reasons")).json()}
    assert reasons["task.stale"] is True


@pytest.mark.asyncio
async def test_unknown_reason_key_is_404(api_client):
    response = await api_client.put("/preferences/reasons/not.a.real.reason", json={"enabled": False})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_reasons_reports_dismiss_count_and_effective_level(api_client, async_db, user_id):
    from app.config import settings
    from app.models import AttentionItemType, AttentionLevel, AttentionResponse

    for _ in range(settings.FEEDBACK_LOOP_DISMISS_THRESHOLD):
        async_db.add(AttentionLog(
            user_id=user_id, item_type=AttentionItemType.TASK, item_id=user_id,
            reason_key="task.overdue", level=AttentionLevel.RECOMMEND, response=AttentionResponse.DISMISSED,
        ))
    await async_db.commit()

    reasons = {r["reason_key"]: r for r in (await api_client.get("/preferences/reasons")).json()}
    overdue = reasons["task.overdue"]
    assert overdue["dismiss_count"] == settings.FEEDBACK_LOOP_DISMISS_THRESHOLD
    assert overdue["effective_level"] == "inform"
    assert reasons["task.stale"]["dismiss_count"] == 0


# ============================================================================
# Reason preferences — Gate integration
# ============================================================================


@pytest.mark.asyncio
async def test_disabled_reason_silences_unconditionally_and_is_not_queued(async_db, user_id):
    """Unlike quiet-hours silencing, an explicit reason opt-out must not be
    queued for later delivery — there is no "later" for a category the
    user turned off (see attention_gate.py's `_decide_level_async` docstring)."""
    async_db.add(UserPreferences(user_id=user_id, disabled_reason_keys=["task.overdue"]))
    await async_db.commit()

    task = await _make_task(async_db, user_id, suffix="disabled", priority=TaskPriority.URGENT, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is None
    queued = (
        await async_db.execute(
            AttentionBundleQueue.__table__.select().where(AttentionBundleQueue.item_id == task.id)
        )
    ).fetchall()
    assert queued == [], "a user-disabled reason must not be bundled for later, unlike a busy-silenced one"

    log_rows = (
        await async_db.execute(AttentionLog.__table__.select().where(AttentionLog.item_id == task.id))
    ).fetchall()
    assert len(log_rows) == 1
    assert log_rows[0].level == AttentionLevel.SILENT


@pytest.mark.asyncio
async def test_disabled_reason_overrides_urgent_priority(async_db, user_id):
    """A category-level off switch beats even the escalation that would
    otherwise push an urgent overdue task past the busy check."""
    async_db.add(UserPreferences(user_id=user_id, disabled_reason_keys=["task.overdue"]))
    await async_db.commit()

    task = await _make_task(async_db, user_id, suffix="disabled-urgent", priority=TaskPriority.URGENT, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is None


@pytest.mark.asyncio
async def test_disabling_one_reason_does_not_silence_a_different_reason(async_db, user_id):
    async_db.add(UserPreferences(user_id=user_id, disabled_reason_keys=["task.stale"]))
    await async_db.commit()

    task = await _make_task(async_db, user_id, suffix="other-reason", priority=TaskPriority.URGENT, due_date=YESTERDAY)

    notification = await request_attention_async(
        async_db, user_id=user_id, title="x",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )

    assert notification is not None
