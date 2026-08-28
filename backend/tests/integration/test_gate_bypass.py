"""
Cờ per-user bỏ qua Gate — `docs/DESIGN.md` mục 12.2.

Đây là hạ tầng của **cổng nghiệm thu duy nhất** của cả sản phẩm. Giả định
đang đặt cược (12.1): *nhắc qua Attention Gate hơn nhắc ngây thơ đủ nhiều
để người dùng cảm nhận được*. Sai thì bot họp thêm chức năng nhắc trong hai
tuần và Cortex không còn sản phẩm — không có phòng thủ nào khác.

Nên hai thứ phải đúng, và cả hai đều dễ sai một cách im lặng:

**Nhóm A phải bỏ qua *cả năm* bước**, kể cả dedup. Cho nhóm A hưởng một
phần Gate làm hai con số ở 12.3 nói dối theo hướng làm Gate trông kém giá
trị hơn thực tế — tức là dẫn tới quyết định bỏ đúng thứ đang có giá trị.

**Cả hai nhóm phải ghi vào cùng một bảng.** Nhóm A không có hàng
`attention_log` thì nhóm A không có số để so, và phép thử không chạy được.
"""

from datetime import date, datetime, time, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.database_async import make_async_sessionmaker
from app.models import (
    AttentionItemType,
    AttentionLevel,
    AttentionLog,
    Notification,
    Project,
    ProjectMember,
    ProjectOrigin,
    Task,
    TaskPriority,
    TaskStatus,
    UserPreferences,
)
from app.services.attention_gate import request_attention_async

PREFIX = "[test-12.2] "
USER_ID = UUID("00000000-0000-4000-a000-000000000061")
YESTERDAY = datetime.combine(date.today() - timedelta(days=1), time(9, 0))


async def _purge(db) -> None:
    await db.execute(delete(Notification).where(Notification.user_id == USER_ID))
    await db.execute(delete(AttentionLog).where(AttentionLog.user_id == USER_ID))
    await db.execute(delete(Task).where(Task.user_id == USER_ID))
    project_ids = list(
        (await db.execute(select(Project.id).where(Project.owner_id == USER_ID)))
        .scalars()
        .all()
    )
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id == USER_ID))
    if project_ids:
        await db.execute(delete(Project).where(Project.id.in_(project_ids)))
    await db.execute(delete(UserPreferences).where(UserPreferences.user_id == USER_ID))
    await db.commit()


@pytest_asyncio.fixture
async def async_db():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await db.execute(
            text(
                "INSERT INTO users (id, email, full_name, hashed_password, is_active, "
                "created_at, updated_at) VALUES (:id, :email, 'pytest 12.2', "
                "'not-a-real-hash', true, NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": USER_ID, "email": "pytest-gate-bypass@cortex.invalid"},
        )
        await db.commit()
        await _purge(db)
        yield db
        await _purge(db)
    await engine.dispose()


async def _overdue_task(db) -> Task:
    from app.services.projects import ProjectService

    project = await ProjectService(db).get_or_create_personal(USER_ID)
    task = Task(
        user_id=USER_ID,
        project_id=project.id,
        title=f"{PREFIX}quá hạn",
        status=TaskStatus.TODO,
        due_date=YESTERDAY,
        priority=TaskPriority.URGENT,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _set_bypass(db, enabled: bool) -> None:
    prefs = await db.get(UserPreferences, USER_ID)
    if prefs is None:
        prefs = UserPreferences(user_id=USER_ID)
        db.add(prefs)
    prefs.gate_bypass = enabled
    await db.commit()


async def _nudge(db, task, reason_key="task.overdue"):
    return await request_attention_async(
        db,
        user_id=USER_ID,
        title=f"{PREFIX}nhắc",
        item_type=AttentionItemType.TASK,
        item_id=task.id,
        reason_key=reason_key,
    )


# ============================================================================
# Mặc định
# ============================================================================


@pytest.mark.asyncio
async def test_no_preferences_row_means_the_gate_is_on(async_db):
    """Cờ đặt theo hướng **"bỏ qua"**, không phải "bật Gate".

    Hàng thiếu, tài khoản mới, hay một lỗi đọc preferences đều rơi về hành
    vi *có Gate* — im hơn. Đặt ngược lại thì mọi trường hợp biên rơi về
    nhắc nhiều hơn, và đó là hướng sai để sai (P5).
    """
    assert (await async_db.get(UserPreferences, USER_ID)) is None

    task = await _overdue_task(async_db)
    await _nudge(async_db, task)
    await async_db.commit()

    log = await async_db.scalar(
        select(AttentionLog).where(AttentionLog.item_id == task.id)
    )
    assert log is not None
    # Gate bật thì `task.overdue` cho một task URGENT quá hạn được escalate
    # — mức phải cao hơn INFORM, tức là nó thực sự đi qua bước tính mức.
    assert log.level is not AttentionLevel.INFORM


# ============================================================================
# Nhóm A — bỏ qua Gate
# ============================================================================


@pytest.mark.asyncio
async def test_group_a_skips_dedup_which_is_the_whole_point(async_db):
    """Dedup **là** một trong năm bước (12.2 liệt kê: dedup · im khi bận ·
    quiet hours · gộp · chọn thời điểm).

    Đây là bẫy dễ sập nhất của cả phép thử: đi qua `record_surface` cho
    tiện thì nhóm A vẫn được dedup, tức là vẫn hưởng một phần năm giá trị
    đang đo — và kết luận sẽ nghiêng về "Gate không đáng".
    """
    await _set_bypass(async_db, True)
    task = await _overdue_task(async_db)

    first = await _nudge(async_db, task)
    second = await _nudge(async_db, task)
    await async_db.commit()

    assert first is not None
    assert second is not None, "nhóm A phải ping lại, không được dedup"

    logs = list(
        (await async_db.scalars(select(AttentionLog).where(AttentionLog.item_id == task.id))).all()
    )
    assert len(logs) == 2


@pytest.mark.asyncio
async def test_group_b_dedups_the_same_two_calls(async_db):
    """Cùng đầu vào, nhóm B im lần thứ hai. Đây là nửa còn lại của so sánh —
    nếu test này hỏng thì test trên không chứng minh được gì."""
    await _set_bypass(async_db, False)
    task = await _overdue_task(async_db)

    first = await _nudge(async_db, task)
    second = await _nudge(async_db, task)
    await async_db.commit()

    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_group_a_still_writes_to_attention_log(async_db):
    """Cả hai nhóm đọc số từ **cùng một bảng** (12.3: tỷ lệ dismiss, tỷ lệ
    làm trong 24h). Nhóm A không có hàng thì nhóm A không có gì để so, và
    phép thử không chạy được."""
    await _set_bypass(async_db, True)
    task = await _overdue_task(async_db)

    notification = await _nudge(async_db, task)
    await async_db.commit()

    log = await async_db.scalar(
        select(AttentionLog).where(AttentionLog.item_id == task.id)
    )
    assert log is not None
    assert log.reason_key == "task.overdue"
    # Nối được từ notification sang log là thứ 12.3 cần: phản hồi trên card
    # ghi vào `attention_log.response`.
    assert notification.attention_log_id == log.id


@pytest.mark.asyncio
async def test_group_a_records_a_flat_level_not_a_computed_one(async_db):
    """Nhắc ngây thơ không có khái niệm mức độ — mọi thứ đến hạn đều ping
    như nhau. Ghi `inform` phẳng làm số liệu nhóm A đọc được đúng như thế."""
    await _set_bypass(async_db, True)
    task = await _overdue_task(async_db)

    await _nudge(async_db, task)
    await async_db.commit()

    log = await async_db.scalar(
        select(AttentionLog).where(AttentionLog.item_id == task.id)
    )
    assert log.level is AttentionLevel.INFORM


@pytest.mark.asyncio
async def test_turning_the_flag_off_restores_the_gate_for_the_same_user(async_db):
    """Cờ per-user, đổi được giữa chừng — chia đôi 20–30 action item thật
    trên **cùng một người dùng** là cách chạy phép thử ở 12.2."""
    task = await _overdue_task(async_db)

    await _set_bypass(async_db, True)
    assert await _nudge(async_db, task) is not None
    assert await _nudge(async_db, task) is not None
    await async_db.commit()

    await _set_bypass(async_db, False)
    # Gate bật lại: lần nhắc thứ ba về cùng task rơi vào dedup.
    assert await _nudge(async_db, task) is None


@pytest.mark.asyncio
async def test_a_pass_through_notification_is_unaffected_by_the_flag(async_db):
    """Thông báo không qua Gate (`reason_key IS NULL`) — ví dụ Google
    Calendar bị thu hồi quyền — không nằm trong phạm vi phép thử và không
    được đổi hành vi theo cờ."""
    await _set_bypass(async_db, True)

    notification = await request_attention_async(
        async_db, user_id=USER_ID, title=f"{PREFIX}hệ thống", type="system"
    )
    await async_db.commit()

    assert notification is not None
    assert notification.reason_key is None
    assert notification.attention_log_id is None
