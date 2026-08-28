"""
`POST /api/internal/tasks` — `docs/DESIGN.md` mục 9.1, tầng 1 của 1.1.

Đây là chỗ **cửa chính để một dự án ra đời** cuối cùng có người đi qua:
4.1 nói *"channel nào có việc thì thành dự án"*, và cho tới endpoint này
`get_or_create_for_channel` chưa từng được gọi từ đâu.

Ba nhóm khẳng định, theo thứ tự quan trọng:

1. **Im lặng đúng chỗ** — người nhận chưa liên kết thì bỏ qua và *báo lại*,
   không đoán (P7). Một việc gán nhầm người là một lời nhắc sai gửi tới
   người không liên quan.
2. **Không đẻ bản sao** — webhook luôn được gửi lại, và bản sao không bị
   dedup của Attention Gate gộp (dedup khoá theo `item_id`).
3. **Người thứ hai vào chung dự án** — QĐ-1, và là điều làm số liệu cấp dự
   án gửi vào channel chung đúng.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.config import settings
from app.database_async import make_async_sessionmaker
from app.models import (
    AttentionChannel,
    AttentionLevel,
    CalendarProvider,
    Project,
    ProjectMember,
    ProjectOrigin,
    Schedule,
    ScheduleExternalMap,
    ScheduleType,
    Task,
    TaskStatus,
    UserChannel,
)

PREFIX = "[test-ingest] "
USER_A = UUID("00000000-0000-4000-a000-000000000051")
USER_B = UUID("00000000-0000-4000-a000-000000000052")
MEZON_A = "mezon-ingest-a"
MEZON_B = "mezon-ingest-b"


def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _purge(db) -> None:
    project_ids = list(
        (await db.execute(select(Project.id).where(Project.owner_id.in_([USER_A, USER_B]))))
        .scalars()
        .all()
    )
    await db.execute(delete(Task).where(Task.user_id.in_([USER_A, USER_B])))
    await db.execute(
        delete(ScheduleExternalMap).where(ScheduleExternalMap.user_id.in_([USER_A, USER_B]))
    )
    await db.execute(delete(Schedule).where(Schedule.user_id.in_([USER_A, USER_B])))
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id.in_([USER_A, USER_B])))
    if project_ids:
        await db.execute(delete(ProjectMember).where(ProjectMember.project_id.in_(project_ids)))
        await db.execute(delete(Project).where(Project.id.in_(project_ids)))
    await db.commit()


@pytest_asyncio.fixture
async def async_db():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        for user_id, email, address in (
            (USER_A, "pytest-ingest-a@cortex.invalid", MEZON_A),
            (USER_B, "pytest-ingest-b@cortex.invalid", MEZON_B),
        ):
            await db.execute(
                text(
                    "INSERT INTO users (id, email, full_name, hashed_password, is_active, "
                    "created_at, updated_at) VALUES (:id, :email, 'pytest ingest', "
                    "'not-a-real-hash', true, NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
                ),
                {"id": user_id, "email": email},
            )
        await db.commit()

        # Liên kết Mezon **đã xác minh** cho cả hai. Chưa xác minh thì
        # `resolve_channel_async` cố ý không khớp — một Mezon id là con số
        # ai trong clan cũng đọc được, nên sở hữu nó không chứng minh gì.
        await db.execute(
            delete(UserChannel).where(UserChannel.address.in_([MEZON_A, MEZON_B]))
        )
        for user_id, address in ((USER_A, MEZON_A), (USER_B, MEZON_B)):
            db.add(
                UserChannel(
                    user_id=user_id,
                    channel=AttentionChannel.MEZON,
                    address=address,
                    verified_at=_naive_now(),
                    enabled=True,
                    # NOT NULL — bình thường do adapter đặt lúc đăng ký
                    # (`DeliveryChannelAdapter.default_min_level`); dựng
                    # hàng tay thì phải tự truyền.
                    min_level=AttentionLevel.RECOMMEND,
                )
            )
        await db.commit()

        await _purge(db)
        yield db
        await _purge(db)
        await db.execute(
            delete(UserChannel).where(UserChannel.address.in_([MEZON_A, MEZON_B]))
        )
        await db.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(async_db):
    from app import app
    from app.database_async import get_async_db

    async def _override_async_db():
        yield async_db

    app.dependency_overrides[get_async_db] = _override_async_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test/internal",
        headers={"X-Internal-API-Key": settings.INTERNAL_API_KEY},
    ) as c:
        yield c
    app.dependency_overrides.clear()


def _item(title, **kwargs):
    return {"title": f"{PREFIX}{title}", "assignee_mezon_user_id": MEZON_A, **kwargs}


# ============================================================================
# Xác thực
# ============================================================================


@pytest.mark.asyncio
async def test_a_wrong_internal_key_is_refused(async_db):
    from app import app
    from app.database_async import get_async_db

    async def _override_async_db():
        yield async_db

    app.dependency_overrides[get_async_db] = _override_async_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test/internal",
        headers={"X-Internal-API-Key": "sai-be-bet"},
    ) as c:
        response = await c.post("/tasks", json={"items": [_item("việc")]})
    app.dependency_overrides.clear()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_no_key_at_all_is_refused(async_db):
    from app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/internal") as c:
        response = await c.post("/tasks", json={"items": [_item("việc")]})
    assert response.status_code == 422


# ============================================================================
# P7 — không đoán người nhận
# ============================================================================


@pytest.mark.asyncio
async def test_an_unlinked_assignee_is_skipped_and_reported(async_db, client):
    """Không có "gán tạm cho ai đó".

    Một action item gán nhầm người là một lời nhắc sai gửi tới người không
    liên quan — nó phá niềm tin nhanh hơn bất kỳ việc bị sót nào. Bỏ qua và
    **báo lại** để bot nói ở channel, thay vì im lặng đánh rơi.
    """
    response = await client.post(
        "/tasks",
        json={"items": [_item("việc", assignee_mezon_user_id="chua-lien-ket")]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_count"] == 0
    assert body["skipped_count"] == 1
    assert body["items"][0]["skipped_reason"] == "assignee_not_linked"

    assert (
        await async_db.scalar(select(Task).where(Task.title.startswith(PREFIX)))
    ) is None


@pytest.mark.asyncio
async def test_an_unverified_link_does_not_count_as_an_identity(async_db, client):
    """Liên kết chưa xác minh bị coi như không có.

    Nếu không, bước liên kết thành đồ trang trí: ai cũng gõ được Mezon id
    của người lạ vào API cài đặt rồi nhận việc thay họ.
    """
    await async_db.execute(
        delete(UserChannel).where(UserChannel.address == MEZON_A)
    )
    async_db.add(
        UserChannel(
            user_id=USER_A,
            channel=AttentionChannel.MEZON,
            address=MEZON_A,
            verified_at=None,
            enabled=True,
            min_level=AttentionLevel.RECOMMEND,
        )
    )
    await async_db.commit()

    response = await client.post("/tasks", json={"items": [_item("việc")]})
    assert response.json()["items"][0]["skipped_reason"] == "assignee_not_linked"


@pytest.mark.asyncio
async def test_one_bad_item_does_not_sink_the_whole_meeting(async_db, client):
    """Bot chốt biên bản rồi đẩy cả cuộc họp một lần. Fail toàn lô vì một
    người chưa liên kết sẽ đánh rơi mọi việc của cuộc họp đó."""
    response = await client.post(
        "/tasks",
        json={
            "items": [
                _item("việc tốt", external_id="ok-1"),
                _item("việc hỏng", assignee_mezon_user_id="chua-lien-ket"),
            ]
        },
    )
    body = response.json()
    assert body["created_count"] == 1
    assert body["skipped_count"] == 1


# ============================================================================
# 4.1 — channel thành dự án
# ============================================================================


@pytest.mark.asyncio
async def test_a_channel_with_work_becomes_a_project(async_db, client):
    """Cửa chính để một dự án ra đời — không ai bấm gì."""
    channel = f"chan-{uuid4().hex}"
    response = await client.post(
        "/tasks",
        json={
            "items": [
                _item(
                    "nộp spec",
                    external_id="e-1",
                    source_channel_id=channel,
                    source_channel_name="Alpha",
                )
            ]
        },
    )
    assert response.json()["created_count"] == 1

    project = await async_db.scalar(
        select(Project).where(Project.source_channel_id == channel)
    )
    assert project is not None
    assert project.name == "Alpha"
    assert project.origin is ProjectOrigin.DERIVED

    task = await async_db.scalar(select(Task).where(Task.source_external_id == "e-1"))
    assert task.project_id == project.id
    # Đã qua mắt người trong cuộc họp rồi — bắt xác nhận lại là bắt làm hai
    # lần một việc. `pending_confirm` dành cho thứ Cortex tự đoán.
    assert task.status is TaskStatus.TODO


@pytest.mark.asyncio
async def test_the_second_person_joins_the_same_project(async_db, client):
    """QĐ-1 — và là điều làm số liệu cấp dự án gửi vào channel chung đúng.

    Nếu người thứ hai tạo bản sao thì mọi thống kê dự án đều tính trên một
    nửa dữ liệu, và tính năng duy nhất tạo giá trị tập thể (8.1) hỏng.
    """
    channel = f"chan-{uuid4().hex}"
    await client.post(
        "/tasks",
        json={
            "items": [
                _item("việc của A", external_id="a-1", source_channel_id=channel,
                      source_channel_name="Alpha"),
                {
                    "title": f"{PREFIX}việc của B",
                    "external_id": "b-1",
                    "assignee_mezon_user_id": MEZON_B,
                    "source_channel_id": channel,
                    "source_channel_name": "Alpha",
                },
            ]
        },
    )

    projects = list(
        (await async_db.scalars(select(Project).where(Project.source_channel_id == channel))).all()
    )
    assert len(projects) == 1

    members = list(
        (
            await async_db.scalars(
                select(ProjectMember).where(ProjectMember.project_id == projects[0].id)
            )
        ).all()
    )
    assert {m.user_id for m in members} == {USER_A, USER_B}


@pytest.mark.asyncio
async def test_no_channel_falls_through_to_the_personal_project(async_db, client):
    """Không channel thì rơi về thang 3.5 — task vẫn có project, không NULL."""
    await client.post("/tasks", json={"items": [_item("việc lẻ", external_id="lone-1")]})

    task = await async_db.scalar(select(Task).where(Task.source_external_id == "lone-1"))
    project = await async_db.get(Project, task.project_id)
    assert project.origin is ProjectOrigin.PERSONAL


# ============================================================================
# Chống trùng — webhook luôn được gửi lại
# ============================================================================


@pytest.mark.asyncio
async def test_the_same_external_id_twice_creates_one_task(async_db, client):
    """Không có nó, mỗi lần gửi lại đẻ một bản sao — và bản sao **không** bị
    dedup của Attention Gate gộp, vì dedup khoá theo `item_id`. Người dùng
    bị nhắc hai lần về một việc: đúng thất bại DESIGN 1.2 định nghĩa."""
    payload = {"items": [_item("nộp spec", external_id="dup-1")]}

    first = await client.post("/tasks", json=payload)
    second = await client.post("/tasks", json=payload)

    assert first.json()["items"][0]["created"] is True
    assert second.json()["items"][0]["created"] is False
    # Lần hai vẫn 200 và vẫn trả task_id, để bot ngừng thử lại.
    assert second.json()["items"][0]["task_id"] == first.json()["items"][0]["task_id"]

    rows = list(
        (await async_db.scalars(select(Task).where(Task.source_external_id == "dup-1"))).all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_the_same_action_item_for_two_people_is_two_tasks(async_db, client):
    """Cùng `external_id`, hai người nhận → hai việc thật, không phải bản sao.

    Đây là lý do unique index có `user_id`.
    """
    await client.post(
        "/tasks",
        json={
            "items": [
                _item("cùng việc", external_id="shared-1"),
                {
                    "title": f"{PREFIX}cùng việc",
                    "external_id": "shared-1",
                    "assignee_mezon_user_id": MEZON_B,
                },
            ]
        },
    )
    rows = list(
        (await async_db.scalars(select(Task).where(Task.source_external_id == "shared-1"))).all()
    )
    assert {r.user_id for r in rows} == {USER_A, USER_B}


# ============================================================================
# 4.2 mức 1 — provider_event_id ghi nguồn gốc
# ============================================================================


@pytest.mark.asyncio
async def test_a_matched_event_is_recorded_as_the_origin(async_db, client):
    provider_event_id = f"evt-{uuid4().hex}"
    start = datetime.now(timezone.utc) + timedelta(days=1)
    event = Schedule(
        user_id=USER_A,
        title=f"{PREFIX}họp Alpha",
        type=ScheduleType.CLASS,
        start_time=start,
        end_time=start + timedelta(hours=1),
    )
    async_db.add(event)
    await async_db.flush()
    async_db.add(
        ScheduleExternalMap(
            user_id=USER_A,
            schedule_id=event.id,
            provider=CalendarProvider.GOOGLE,
            provider_calendar_id="primary",
            provider_event_id=provider_event_id,
        )
    )
    await async_db.commit()

    await client.post(
        "/tasks",
        json={
            "items": [
                _item("từ cuộc họp", external_id="evt-1", provider_event_id=provider_event_id)
            ]
        },
    )

    task = await async_db.scalar(select(Task).where(Task.source_external_id == "evt-1"))
    assert task.related_event_id == event.id


@pytest.mark.asyncio
async def test_another_persons_calendar_row_is_never_matched(async_db, client):
    """Lịch không sync chéo: mỗi người dự có hàng `Schedule` riêng cho cùng
    một sự kiện Google. Thiếu bộ lọc `user_id` thì task của A trỏ vào hàng
    lịch của B, và mọi thứ đọc `related_event_id` sau đó đều sai."""
    provider_event_id = f"evt-{uuid4().hex}"
    start = datetime.now(timezone.utc) + timedelta(days=1)
    theirs = Schedule(
        user_id=USER_B,
        title=f"{PREFIX}họp của B",
        type=ScheduleType.CLASS,
        start_time=start,
        end_time=start + timedelta(hours=1),
    )
    async_db.add(theirs)
    await async_db.flush()
    async_db.add(
        ScheduleExternalMap(
            user_id=USER_B,
            schedule_id=theirs.id,
            provider=CalendarProvider.GOOGLE,
            provider_calendar_id="primary",
            provider_event_id=provider_event_id,
        )
    )
    await async_db.commit()

    await client.post(
        "/tasks",
        json={
            "items": [
                _item("của A", external_id="cross-1", provider_event_id=provider_event_id)
            ]
        },
    )

    task = await async_db.scalar(select(Task).where(Task.source_external_id == "cross-1"))
    assert task.user_id == USER_A
    assert task.related_event_id is None


@pytest.mark.asyncio
async def test_an_unknown_event_id_does_not_break_the_item(async_db, client):
    """Phần lớn action item sẽ không khớp sự kiện nào, và đó là bình thường."""
    response = await client.post(
        "/tasks",
        json={"items": [_item("việc", external_id="miss-1", provider_event_id="khong-co")]},
    )
    assert response.json()["created_count"] == 1
    task = await async_db.scalar(select(Task).where(Task.source_external_id == "miss-1"))
    assert task.related_event_id is None
