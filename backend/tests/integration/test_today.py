"""
Integration tests for Milestone 2.7 — the "Hôm nay" screen.

Runs against the real dev Postgres, against a **throwaway account** rather
than the seeded one: this screen reads everything a user owns, so the fixture
has to start from an empty account — and emptying a real developer's account
to get a clean test is not an acceptable trade.

This is the product's main surface, so most of these tests are about what it
must *not* do: no raw percentage the user has to interpret, no card without a
reason, no invented urgency, no unconfirmed suggestion presented as validated
work, and no default empty table.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete

from tests.integration.isolated_user import (
    ISOLATED_TEST_USER_ID,
    ensure_isolated_user,
)
from app.models import (
    Task,
    TaskPriority,
    TaskStatus,
)
from app.schemas import TaskCreate, TodayResponse
from app.services.tasks import TaskService
from app.services.today import MAX_NOW_ACTIONS, MAX_SUGGESTIONS, TodayService

# NOT the seeded dev account: these tests clear the whole account to get
# a clean fixture, and that account belongs to a real person. See
# tests/integration/isolated_user.py.
TEST_USER_ID = ISOLATED_TEST_USER_ID
MARKER = "[test-2.7]"
TODAY = datetime.now(timezone.utc).date()


# ============================================================================
# Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await ensure_isolated_user(db)
        # Clean slate. Safe to wipe wholesale because the account is this
        # suite's own (see isolated_user.py) — every row in it was created
        # by these tests.
        await db.execute(delete(Task).where(Task.user_id == TEST_USER_ID))
        await db.commit()
        yield db
        await db.execute(delete(Task).where(Task.user_id == TEST_USER_ID))
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
def service(async_db):
    return TodayService(async_db)


async def _task(
    db, title: str, due_in_days: int | None = None, priority: TaskPriority | None = None
) -> Task:
    return await TaskService(db).create_task(
        payload=TaskCreate(
            title=f"{MARKER} {title}",
            due_date=TODAY + timedelta(days=due_in_days) if due_in_days is not None else None,
            priority=priority,
        ),
        user_id=TEST_USER_ID,
    )


async def _pending_task(db, action: str, due_in_days: int | None = 2) -> Task:
    """A task the extraction pipeline would have suggested — created
    straight into `pending_confirm`, same as `task_extraction.py` does."""
    return await TaskService(db).create_task(
        payload=TaskCreate(
            title=f"{MARKER} {action}",
            status=TaskStatus.PENDING_CONFIRM,
            due_date=TODAY + timedelta(days=due_in_days) if due_in_days is not None else None,
        ),
        user_id=TEST_USER_ID,
    )


# ============================================================================
# Every card carries a reason, and the reason states impact
# ============================================================================

@pytest.mark.asyncio
async def test_every_action_has_a_reason(async_db, service):
    await _task(async_db, "viết API spec", due_in_days=-3)
    await _task(async_db, "gửi bản nháp", due_in_days=0)

    today = await service.get_today(TEST_USER_ID)

    assert today.now_actions
    for action in today.now_actions:
        assert action.reason is not None
        assert action.reason.impact.strip()
        assert action.reason.key


@pytest.mark.asyncio
async def test_reason_states_a_consequence_not_a_label(async_db, service):
    """"priority: high" is a label the user has to interpret. The reason has
    to name what skipping the task costs."""
    await _task(async_db, "viết API spec", due_in_days=-3)

    today = await service.get_today(TEST_USER_ID)
    impact = today.now_actions[0].reason.impact

    assert "Quá hạn 3 ngày" in impact

    # And it is never a bare priority label.
    for banned in ("priority", "P1"):
        assert banned.lower() not in impact.lower()


@pytest.mark.asyncio
async def test_high_priority_undated_task_still_surfaces(async_db, service):
    """A task with no deadline still needs a way to surface if it matters —
    that's what `priority` replaces the old goal-deadline signal with."""
    await _task(async_db, "việc khẩn cấp", priority=TaskPriority.URGENT)

    today = await service.get_today(TEST_USER_ID)

    assert today.now_actions
    assert "khẩn cấp" in today.now_actions[0].reason.impact.lower()


@pytest.mark.asyncio
async def test_a_task_with_nothing_true_to_say_is_not_surfaced(async_db, service):
    """Silence is a valid answer. A task with no deadline and no priority
    produces no card rather than a padded one."""
    await _task(async_db, "việc mơ hồ", due_in_days=None)

    today = await service.get_today(TEST_USER_ID)
    assert today.now_actions == []
    assert today.state == "nothing_urgent"


@pytest.mark.asyncio
async def test_actions_are_capped_and_ordered_by_cost_of_delay(async_db, service):
    """One attention surface forces ranking — that's P1 at the UI layer. A
    list of twenty cards would be a backlog, not a decision."""
    await _task(async_db, "trễ 1 ngày", due_in_days=-1)
    await _task(async_db, "trễ 5 ngày", due_in_days=-5)
    await _task(async_db, "hạn hôm nay", due_in_days=0)
    await _task(async_db, "hạn mai", due_in_days=1)
    await _task(async_db, "hạn kia", due_in_days=2)

    today = await service.get_today(TEST_USER_ID)

    assert len(today.now_actions) == MAX_NOW_ACTIONS
    assert "trễ 5 ngày" in today.now_actions[0].title
    assert "trễ 1 ngày" in today.now_actions[1].title


@pytest.mark.asyncio
async def test_higher_priority_breaks_ties_before_due_date(async_db, service):
    """Two equally-overdue tasks: the more important one goes first."""
    await _task(async_db, "trễ, ưu tiên thấp", due_in_days=-1, priority=TaskPriority.LOW)
    await _task(async_db, "trễ, khẩn cấp", due_in_days=-1, priority=TaskPriority.URGENT)

    today = await service.get_today(TEST_USER_ID)
    assert "khẩn cấp" in today.now_actions[0].title


# ============================================================================
# No raw numbers the user has to interpret
# ============================================================================

def test_today_payload_exposes_no_progress_percentage():
    """No raw ratio ever reaches this screen — everything is a judgement in
    the reason sentence, never a number the user has to interpret."""
    assert "progress" not in TodayResponse.model_fields


# ============================================================================
# The status line (Phase 2 scope)
# ============================================================================

@pytest.mark.asyncio
async def test_status_line_has_no_data_source_in_phase_2(async_db, service):
    """Goal was the only status-line data source Phase 2 had; without it
    (and without 3.3's free-slot half), the line is omitted rather than a
    made-up sentence taking its place."""
    await _task(async_db, "việc lẻ", due_in_days=0)
    today = await service.get_today(TEST_USER_ID)
    assert today.status_line is None


# ============================================================================
# "Cần xác nhận" — task suggestions awaiting a yes/no
# ============================================================================

@pytest.mark.asyncio
async def test_needs_confirmation_lists_pending_suggestions(async_db, service):
    suggestion = await _pending_task(async_db, "gửi proposal cho John")

    today = await service.get_today(TEST_USER_ID)

    assert [i.task_id for i in today.needs_confirmation] == [suggestion.id]


@pytest.mark.asyncio
async def test_needs_confirmation_only_shows_pending_confirm(async_db, service):
    """A task the user already confirmed (or that was created directly as
    `todo`) isn't a suggestion anymore — it belongs on the ranked list, not
    here."""
    suggestion = await _pending_task(async_db, "chưa xác nhận")
    await _task(async_db, "việc bình thường", due_in_days=1)

    today = await service.get_today(TEST_USER_ID)
    ids = {i.task_id for i in today.needs_confirmation}
    assert ids == {suggestion.id}


@pytest.mark.asyncio
async def test_needs_confirmation_shows_even_when_task_list_is_quiet(async_db, service):
    """A suggestion doesn't stop mattering because today's ranked work is
    done."""
    await _pending_task(async_db, "gửi báo cáo", due_in_days=-3)

    today = await service.get_today(TEST_USER_ID)
    assert today.state in ("nothing_urgent", "all_clear", "onboarding")
    assert len(today.needs_confirmation) == 1


@pytest.mark.asyncio
async def test_a_pending_suggestion_is_not_ranked_as_now_action(async_db, service):
    """`pending_confirm` hasn't earned a place among validated, ranked work
    — even one overdue by a week must not appear in `now_actions`."""
    await _pending_task(async_db, "quá hạn rồi", due_in_days=-7)

    today = await service.get_today(TEST_USER_ID)
    assert today.now_actions == []


# ============================================================================
# The three empty states
# ============================================================================

@pytest.mark.asyncio
async def test_onboarding_state_for_a_brand_new_user(async_db, service):
    today = await service.get_today(TEST_USER_ID)

    assert today.state == "onboarding"
    assert today.now_actions == []
    assert today.suggestions == []
    assert today.status_line is None


@pytest.mark.asyncio
async def test_nothing_urgent_state_offers_without_inventing_urgency(async_db, service):
    """The most important of the three: "hôm nay không có gì gấp" is a real
    answer. It may offer things the user *could* do — it must never dress
    them up as urgent to fill the screen."""
    await _task(async_db, "việc thong thả 1", due_in_days=90)
    await _task(async_db, "việc thong thả 2", due_in_days=120)
    await _task(async_db, "việc thong thả 3", due_in_days=150)

    today = await service.get_today(TEST_USER_ID)

    assert today.state == "nothing_urgent"
    assert today.now_actions == []          # nothing presented as "do this now"
    assert 0 < len(today.suggestions) <= MAX_SUGGESTIONS

    for suggestion in today.suggestions:
        assert suggestion.reason.key == "task.could_start"
        assert "Chưa gấp" in suggestion.reason.impact
        # No borrowed urgency vocabulary.
        for banned in ("quá hạn", "hết hôm nay", "trễ"):
            assert banned not in suggestion.reason.impact.lower()


@pytest.mark.asyncio
async def test_all_clear_state_when_nothing_is_open(async_db, service):
    task = await _task(async_db, "xong rồi", due_in_days=-1)
    await TaskService(async_db).complete_task(task.id, TEST_USER_ID)

    today = await service.get_today(TEST_USER_ID)

    assert today.state == "all_clear"
    assert today.now_actions == []
    assert today.suggestions == []


@pytest.mark.asyncio
async def test_has_actions_state_when_something_is_pressing(async_db, service):
    await _task(async_db, "gấp", due_in_days=0)

    today = await service.get_today(TEST_USER_ID)
    assert today.state == "has_actions"
    assert today.now_actions


@pytest.mark.asyncio
async def test_state_is_always_one_of_the_three_designs(async_db, service):
    """Served by the server so the client can never fall through to a
    default empty table."""
    today = await service.get_today(TEST_USER_ID)
    assert today.state in ("onboarding", "nothing_urgent", "all_clear", "has_actions")


@pytest.mark.asyncio
async def test_all_clear_requires_work_to_have_existed(async_db, service):
    """`all_clear` is earned: there has to have been a task, and it has to be
    finished."""
    task = await _task(async_db, "làm xong rồi", due_in_days=-1)
    await TaskService(async_db).complete_task(task.id, TEST_USER_ID)

    today = await service.get_today(TEST_USER_ID)
    assert today.state == "all_clear"


# ============================================================================
# API
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
async def test_api_today_shape(api_client, async_db):
    await _task(async_db, "viết API spec", due_in_days=-3, priority=TaskPriority.HIGH)
    await _pending_task(async_db, "John gửi spec")

    response = await api_client.get("/today")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body.keys()) == {
        "state", "status_line", "now_actions", "suggestions", "needs_confirmation"
    }
    assert body["state"] == "has_actions"
    assert len(body["needs_confirmation"]) == 1

    card = body["now_actions"][0]
    assert card["reason"]["impact"]
    assert card["priority"] == "high"
    # No percentage anywhere in the main payload.
    assert "progress" not in card
