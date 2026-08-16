"""
Confirms `reason_key`/`attention_level`/`attention_log_id` actually reach
`GET /api/notifications`, not just the ORM object — this is the field the
frontend's dismiss/click handlers need to call
`POST /attention-log/{id}/response` (Feedback Loop, 6.9's raw material).
Uses the same `api_client` dependency-override pattern as test_today.py.
"""

from datetime import date, datetime, time, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.database_async import make_async_sessionmaker
from app.models import AttentionItemType, AttentionLog, Notification, Task, TaskPriority, TaskStatus
from app.services.attention_gate import request_attention_async
from app.services.notifications import create_notification_async
from tests.integration.isolated_user import ensure_isolated_user

TITLE_PREFIX = "[test-notif-fields] "
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
        await db.execute(delete(Notification).where(Notification.user_id == user_id))
        await db.execute(delete(AttentionLog).where(AttentionLog.user_id == user_id))
        await db.execute(delete(Task).where(Task.user_id == user_id))
        await db.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(async_db, user_id):
    from app import app
    from app.database import SessionLocal, get_db
    from app.dependencies import get_current_active_user

    class _StubUser:
        id = user_id

    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_active_user] = lambda: _StubUser()
    app.dependency_overrides[get_db] = _override_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api") as client:
        yield client

    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_gated_notification_exposes_attention_fields_over_the_api(async_db, user_id, api_client):
    task = Task(
        user_id=user_id, title=f"{TITLE_PREFIX}task", status=TaskStatus.TODO,
        due_date=YESTERDAY, priority=TaskPriority.URGENT,
    )
    async_db.add(task)
    await async_db.commit()
    await async_db.refresh(task)

    created = await request_attention_async(
        async_db, user_id=user_id, title=f"{TITLE_PREFIX}quá hạn",
        item_type=AttentionItemType.TASK, item_id=task.id, reason_key="task.overdue",
    )
    assert created is not None

    response = await api_client.get("/notifications")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    match = next(n for n in items if n["id"] == str(created.id))

    assert match["reason_key"] == "task.overdue"
    assert match["attention_level"] == "ask"
    assert match["attention_log_id"] == str(created.attention_log_id)


@pytest.mark.asyncio
async def test_pass_through_notification_has_null_attention_fields_over_the_api(async_db, user_id, api_client):
    created = await create_notification_async(
        async_db, user_id=user_id, type="system", title=f"{TITLE_PREFIX}system alert",
    )

    response = await api_client.get("/notifications")
    items = response.json()["items"]
    match = next(n for n in items if n["id"] == str(created.id))

    assert match["reason_key"] is None
    assert match["attention_level"] is None
    assert match["attention_log_id"] is None
