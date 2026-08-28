"""
Integration tests for Milestone 6.1 M3 — the bundle flush (steps 4-5).

test_attention_gate.py already proves a busy-silenced candidate gets
queued; this file owns the other half — `flush_due_bundles` turning queued
rows into the one bundled Notification once the user is free, which is the
planning doc's own acceptance scenario for 6.1 ("8 candidates during a
meeting -> 0 during, 1 bundled after").
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database_async import make_async_sessionmaker
from app.models import (
    AttentionBundleQueue,
    AttentionItemType,
    Notification,
    Project,
    ProjectMember,
    ProjectOrigin,
    Schedule,
    ScheduleType,
    Task,
    TaskPriority,
    TaskStatus,
)
from app.services.attention_bundle import BUNDLE_REASON_KEY, enqueue_async, flush_due_bundles
from app.services.attention_reason_catalog import ReasonScope, scope_for
from app.services.delivery.base import DeliveryPayload
from tests.integration.isolated_user import ensure_isolated_user

TITLE_PREFIX = "[test-6.1-bundle] "


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
        await db.execute(delete(Schedule).where(Schedule.user_id == user_id))
        # Thứ tự theo FK: task trỏ vào project, thành viên cũng vậy.
        await db.execute(delete(Task).where(Task.user_id == user_id))
        await db.execute(delete(ProjectMember).where(ProjectMember.user_id == user_id))
        await db.execute(delete(Project).where(Project.owner_id == user_id))
        await db.commit()
    await engine.dispose()


async def _enqueue(db, user_id, *, suffix: str) -> AttentionBundleQueue:
    return await enqueue_async(
        db, user_id=user_id, item_type=AttentionItemType.TASK, item_id=uuid4(),
        reason_key="task.overdue", title=f"{TITLE_PREFIX}{suffix}", body=None,
        payload={}, actions=[], attention_log_id=None,
    )


@pytest.mark.asyncio
async def test_still_busy_user_is_not_flushed(async_db, user_id):
    now = datetime.now(timezone.utc)
    schedule = Schedule(
        user_id=user_id, title=f"{TITLE_PREFIX}meeting", type=ScheduleType.PERSONAL,
        start_time=now - timedelta(minutes=5), end_time=now + timedelta(minutes=55),
    )
    async_db.add(schedule)
    await async_db.commit()

    await _enqueue(async_db, user_id, suffix="a")

    flushed = await flush_due_bundles(async_db)

    assert flushed == 0
    rows = (
        await async_db.execute(select(AttentionBundleQueue).where(AttentionBundleQueue.user_id == user_id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].flushed_at is None


@pytest.mark.asyncio
async def test_free_user_gets_one_bundled_notification_for_all_queued_items(async_db, user_id):
    await _enqueue(async_db, user_id, suffix="one")
    await _enqueue(async_db, user_id, suffix="two")
    await _enqueue(async_db, user_id, suffix="three")

    flushed = await flush_due_bundles(async_db)

    assert flushed == 1

    notifications = (
        await async_db.execute(select(Notification).where(Notification.user_id == user_id))
    ).scalars().all()
    assert len(notifications) == 1
    assert "3" in notifications[0].title
    assert notifications[0].reason_key == "attention.bundle"
    assert len(notifications[0].payload["bundled_items"]) == 3
    # One content block per item, not one block holding a "\n"-joined
    # string — the latter renders as a single line in the detail modal
    # (BlockRenderer's text block has no white-space: pre-wrap).
    assert len(notifications[0].content) == 3
    assert all(block["type"] == "text" for block in notifications[0].content)
    assert " • " in notifications[0].body

    rows = (
        await async_db.execute(select(AttentionBundleQueue).where(AttentionBundleQueue.user_id == user_id))
    ).scalars().all()
    assert all(row.flushed_at is not None for row in rows)
    assert all(row.bundle_notification_id == notifications[0].id for row in rows)


@pytest.mark.asyncio
async def test_already_flushed_rows_are_not_flushed_again(async_db, user_id):
    await _enqueue(async_db, user_id, suffix="solo")
    first_flush = await flush_due_bundles(async_db)
    assert first_flush == 1

    second_flush = await flush_due_bundles(async_db)
    assert second_flush == 0

    notifications = (
        await async_db.execute(select(Notification).where(Notification.user_id == user_id))
    ).scalars().all()
    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_no_pending_rows_is_a_no_op(async_db, user_id):
    flushed = await flush_due_bundles(async_db)
    assert flushed == 0


# ---------------------------------------------------------------------------
# Gộp theo dự án — DESIGN 7.2
#
# Điều được khẳng định ở đây không phải "gộp đúng" mà là **gom đúng chỗ và
# vẫn về đúng kênh**. Ba việc của ba dự án trộn vào một tin buộc người đọc
# tự tách ra (P5); còn một cụm việc riêng phát vào channel chung là lỗi
# cấu trúc đã giết hướng "bot nghe channel" (1.4). Test cuối cùng canh
# đúng cái thứ hai, và nó là cái đắt hơn nếu sai.
# ---------------------------------------------------------------------------


async def _project(db, user_id, *, name: str, origin=ProjectOrigin.DERIVED) -> Project:
    project = Project(
        owner_id=user_id,
        name=f"{TITLE_PREFIX}{name}",
        origin=origin,
        # Dự án suy ra từ channel *có* channel — đúng điều kiện để một
        # nhắc cấp dự án được phát vào đó (8.1). Test định tuyến ở cuối
        # file dựa vào chi tiết này.
        source_channel_id=None if origin is ProjectOrigin.PERSONAL else f"chan-{uuid4().hex}",
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user_id, joined_via="derived"))
    await db.flush()
    return project


async def _task_in(db, user_id, project, *, title: str) -> Task:
    task = Task(
        user_id=user_id,
        project_id=project.id,
        title=f"{TITLE_PREFIX}{title}",
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
    )
    db.add(task)
    await db.flush()
    return task


async def _enqueue_task(db, user_id, task: Task) -> AttentionBundleQueue:
    return await enqueue_async(
        db, user_id=user_id, item_type=AttentionItemType.TASK, item_id=task.id,
        reason_key="task.overdue", title=task.title, body=None,
        payload={}, actions=[], attention_log_id=None,
    )


async def _notifications_of(db, user_id) -> list[Notification]:
    rows = (
        await db.execute(select(Notification).where(Notification.user_id == user_id))
    ).scalars().all()
    return list(rows)


@pytest.mark.asyncio
async def test_two_projects_become_two_bundles_each_named(async_db, user_id):
    alpha = await _project(async_db, user_id, name="Alpha")
    beta = await _project(async_db, user_id, name="Beta")
    await _enqueue_task(async_db, user_id, await _task_in(async_db, user_id, alpha, title="a1"))
    await _enqueue_task(async_db, user_id, await _task_in(async_db, user_id, alpha, title="a2"))
    await _enqueue_task(async_db, user_id, await _task_in(async_db, user_id, beta, title="b1"))

    flushed = await flush_due_bundles(async_db)

    # Hai cụm, không phải một tin gộp ba việc của hai dự án.
    assert flushed == 2
    notifications = await _notifications_of(async_db, user_id)
    assert len(notifications) == 2

    titles = sorted(n.title for n in notifications)
    alpha_title = next(t for t in titles if alpha.name in t)
    beta_title = next(t for t in titles if beta.name in t)
    assert "2 việc" in alpha_title
    assert beta.name in beta_title
    # Cụm một việc vẫn nêu tên việc, không đếm "1 việc".
    assert "1 việc" not in beta_title

    by_title = {n.title: n for n in notifications}
    assert len(by_title[alpha_title].payload["bundled_items"]) == 2
    assert by_title[alpha_title].payload["project_id"] == str(alpha.id)
    assert by_title[beta_title].payload["project_name"] == beta.name


@pytest.mark.asyncio
async def test_personal_project_bundle_is_named_not_anonymous(async_db, user_id):
    """7.2: *"nhãn gộp là tên dự án cá nhân, không phải một nhóm vô danh"*."""
    personal = await _project(async_db, user_id, name="Cá nhân", origin=ProjectOrigin.PERSONAL)
    await _enqueue_task(async_db, user_id, await _task_in(async_db, user_id, personal, title="p1"))
    await _enqueue_task(async_db, user_id, await _task_in(async_db, user_id, personal, title="p2"))

    assert await flush_due_bundles(async_db) == 1

    notification = (await _notifications_of(async_db, user_id))[0]
    assert personal.name in notification.title
    assert "2 việc" in notification.title


@pytest.mark.asyncio
async def test_items_with_no_project_keep_the_old_wording(async_db, user_id):
    """Nhắc cấp người dùng (`day.review`) không thuộc dự án nào.

    Khoá lại từng chữ của cách nói cũ: thêm một khoá gộp không được đổi
    hành vi của những hàng không có khoá đó.
    """
    await enqueue_async(
        async_db, user_id=user_id, item_type=AttentionItemType.USER, item_id=user_id,
        reason_key="day.review", title=f"{TITLE_PREFIX}cuối ngày", body=None,
        payload={}, actions=[], attention_log_id=None,
    )
    await _enqueue(async_db, user_id, suffix="task đã bị xoá")

    assert await flush_due_bundles(async_db) == 1

    notification = (await _notifications_of(async_db, user_id))[0]
    assert notification.title == "Trong lúc bạn bận có 2 việc cần chú ý"
    assert notification.payload["project_id"] is None


@pytest.mark.asyncio
async def test_bundle_named_after_a_project_still_goes_to_dm(async_db, user_id):
    """Gộp **theo** dự án không phải phát **vào** dự án (8.1).

    Alpha có `source_channel_id`, nên nếu cụm này mang phạm vi `PROJECT`
    thì nó sẽ rơi vào channel chung của cả nhóm — mang theo tên những việc
    riêng của một người. `scope` là thứ duy nhất đứng giữa.
    """
    alpha = await _project(async_db, user_id, name="Alpha")
    assert alpha.source_channel_id is not None
    await _enqueue_task(async_db, user_id, await _task_in(async_db, user_id, alpha, title="a1"))

    await flush_due_bundles(async_db)

    notification = (await _notifications_of(async_db, user_id))[0]
    assert notification.reason_key == BUNDLE_REASON_KEY
    assert scope_for(BUNDLE_REASON_KEY) is ReasonScope.PERSONAL
    assert DeliveryPayload.from_notification(notification).project_channel_id is None
    # Và khoá mà bộ định tuyến đọc không được lọt vào payload.
    assert "source_channel_id" not in notification.payload


@pytest.mark.asyncio
async def test_occurrence_of_a_series_inherits_the_template_project(async_db, user_id):
    """`schedules.project_id` chỉ nằm trên hàng template (DESIGN 3.2).

    Nếu đường đọc không đi ngược lên template thì mọi lần lặp của một chuỗi
    đều tra ra `NULL` — tức là đúng trường hợp phổ biến nhất của lịch sẽ
    rơi khỏi nhóm dự án, âm thầm, và chỉ lộ ra khi có người hỏi vì sao
    "Alpha" không bao giờ gom được cuộc họp nào.
    """
    alpha = await _project(async_db, user_id, name="Alpha")
    far = datetime.now(timezone.utc) + timedelta(days=7)

    template = Schedule(
        user_id=user_id, title=f"{TITLE_PREFIX}standup", type=ScheduleType.PERSONAL,
        start_time=far, end_time=far + timedelta(minutes=30), project_id=alpha.id,
    )
    async_db.add(template)
    await async_db.flush()

    occurrence = Schedule(
        user_id=user_id, title=f"{TITLE_PREFIX}standup", type=ScheduleType.PERSONAL,
        start_time=far + timedelta(days=1), end_time=far + timedelta(days=1, minutes=30),
        recurrence_id=template.id, project_id=None,
    )
    async_db.add(occurrence)
    await async_db.flush()

    await enqueue_async(
        async_db, user_id=user_id, item_type=AttentionItemType.SCHEDULE, item_id=occurrence.id,
        reason_key="schedule.starts_soon", title=occurrence.title, body=None,
        payload={}, actions=[], attention_log_id=None,
    )

    assert await flush_due_bundles(async_db) == 1
    notification = (await _notifications_of(async_db, user_id))[0]
    assert alpha.name in notification.title
    assert notification.payload["project_id"] == str(alpha.id)
