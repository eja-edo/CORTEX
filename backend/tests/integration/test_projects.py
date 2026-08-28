"""
Tiêu chí nghiệm thu của Tuần 0 — `docs/DESIGN.md` mục 13.1.

Mỗi test ở đây khoá một câu trong thiết kế, không phải một hàm:

  * thang xác định project lúc ghi (3.5) — thứ tự ba bước, không đổi;
  * project sinh ra từ channel (4.1) — người thứ hai *tìm thấy* project
    đã có và tự vào làm thành viên, không tạo bản thứ hai;
  * `deadline IS NULL` của dự án cá nhân (3.4) — bất biến chịu lực, là
    thứ duy nhất chặn nhắc cấp dự án cho việc lẻ;
  * `uq_schedule_external_maps_provider_event` kèm `user_id` (QĐ-1) —
    hai người sync cùng một cuộc họp không còn đụng ràng buộc.

Chạy trên Postgres dev thật. Mọi hàng tạo ở đây mang tiền tố nhận dạng và
bị xoá trong teardown; tài khoản thì dùng của riêng test, không đụng vào
tài khoản người thật (xem `isolated_user.py`).
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.models import (
    CalendarProvider,
    Project,
    ProjectJoinSource,
    ProjectMember,
    ProjectOrigin,
    Schedule,
    ScheduleExternalMap,
    ScheduleType,
    Task,
)
from app.schemas import TaskCreate
from app.services.projects import ProjectService
from app.services.tasks import TaskService

TITLE_PREFIX = "[test-projects] "
CHANNEL_PREFIX = "test-projects-channel-"

# Hai tài khoản dùng một lần, không phải người thật. `.invalid` là TLD dành
# riêng (RFC 2606) nên không thể trùng địa chỉ của ai.
USER_A = UUID("00000000-0000-4000-a000-000000000011")
USER_B = UUID("00000000-0000-4000-a000-000000000012")


async def _ensure_user(db, user_id: UUID, name: str, email: str) -> None:
    await db.execute(
        text(
            "INSERT INTO users (id, email, full_name, hashed_password, is_active, "
            "created_at, updated_at) "
            "VALUES (:id, :email, :name, 'not-a-real-hash', true, NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": email, "name": name},
    )


async def _purge(db) -> None:
    """Xoá theo đúng thứ tự FK: task → schedule → member → project."""
    await db.execute(delete(Task).where(Task.user_id.in_([USER_A, USER_B])))
    await db.execute(delete(Schedule).where(Schedule.user_id.in_([USER_A, USER_B])))
    project_ids = (
        select(Project.id).where(Project.owner_id.in_([USER_A, USER_B])).scalar_subquery()
    )
    await db.execute(delete(ProjectMember).where(ProjectMember.project_id.in_(project_ids)))
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id.in_([USER_A, USER_B])))
    await db.execute(delete(Project).where(Project.owner_id.in_([USER_A, USER_B])))
    await db.commit()


@pytest_asyncio.fixture
async def async_db():
    """Engine riêng cho mỗi test — cùng lý do đã ghi ở `test_core_events.py`."""
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await _ensure_user(db, USER_A, "pytest project A", "pytest-project-a@cortex.invalid")
        await _ensure_user(db, USER_B, "pytest project B", "pytest-project-b@cortex.invalid")
        await db.commit()
        await _purge(db)
        yield db
        await _purge(db)
    await engine.dispose()


def _schedule(user_id: UUID, title: str, **kwargs) -> Schedule:
    start = datetime.now(timezone.utc) + timedelta(days=1)
    return Schedule(
        user_id=user_id,
        title=TITLE_PREFIX + title,
        type=ScheduleType.CLASS,
        start_time=start,
        end_time=start + timedelta(hours=1),
        **kwargs,
    )


# ============================================================================
# 3.4 — dự án cá nhân
# ============================================================================


@pytest.mark.asyncio
async def test_personal_project_is_created_on_first_need_not_at_registration(async_db):
    """Tạo lười. Tài khoản vừa tồn tại thì chưa có dự án nào.

    Đây là điểm khác `workspaces` (`api/auth.py:136`) — bảng đó đầy hàng
    rỗng vì mỗi lần đăng ký đẻ một cái, kể cả 94 tài khoản test.
    """
    assert await async_db.scalar(
        select(Project).where(Project.owner_id == USER_A)
    ) is None

    project = await ProjectService(async_db).get_or_create_personal(USER_A)
    await async_db.commit()

    assert project.origin == ProjectOrigin.PERSONAL
    assert project.name == "pytest project A"
    # Ba giá trị này là bất biến, không phải mặc định tiện tay.
    assert project.deadline is None
    assert project.deadline_is_manual is False
    assert project.source_channel_id is None


@pytest.mark.asyncio
async def test_personal_project_has_exactly_one_member_and_is_idempotent(async_db):
    service = ProjectService(async_db)
    first = await service.get_or_create_personal(USER_A)
    second = await service.get_or_create_personal(USER_A)
    await async_db.commit()

    assert first.id == second.id

    members = (
        await async_db.scalars(
            select(ProjectMember).where(ProjectMember.project_id == first.id)
        )
    ).all()
    assert [m.user_id for m in members] == [USER_A]


@pytest.mark.asyncio
async def test_second_personal_project_for_one_user_is_refused_by_the_database(async_db):
    """`uq_projects_personal_per_user` — hàng rào ở tầng DB, không chỉ ở code.

    Quan trọng vì dự án cá nhân là nơi mọi task không có ngữ cảnh rơi vào;
    hai cái thì task của cùng một người tách làm đôi một cách im lặng.
    """
    await ProjectService(async_db).get_or_create_personal(USER_A)
    await async_db.commit()

    async_db.add(
        Project(owner_id=USER_A, name="cái thứ hai", origin=ProjectOrigin.PERSONAL)
    )
    with pytest.raises(Exception) as exc:
        await async_db.commit()
    assert "uq_projects_personal_per_user" in str(exc.value)
    await async_db.rollback()


# ============================================================================
# 4.1 — project suy ra từ channel
# ============================================================================


@pytest.mark.asyncio
async def test_channel_becomes_a_project_named_after_the_channel(async_db):
    channel = CHANNEL_PREFIX + uuid4().hex
    project = await ProjectService(async_db).get_or_create_for_channel(
        channel_id=channel, channel_name="Alpha", user_id=USER_A
    )
    await async_db.commit()

    assert project.origin == ProjectOrigin.DERIVED
    assert project.source_channel_id == channel
    assert project.name == "Alpha"
    # Người nhận việc đầu tiên vào luôn, không qua lời mời (P4).
    member = await async_db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == USER_A
        )
    )
    assert member is not None
    assert member.joined_via == ProjectJoinSource.DERIVED


@pytest.mark.asyncio
async def test_second_person_from_the_same_channel_joins_instead_of_forking(async_db):
    """QĐ-1 — đây là lý do danh tính dự án treo vào channel.

    Nếu người thứ hai tạo bản sao thì mọi số liệu cấp dự án gửi vào channel
    chung đều sai, và tính năng duy nhất tạo giá trị tập thể (8.1) hỏng.
    """
    channel = CHANNEL_PREFIX + uuid4().hex
    service = ProjectService(async_db)

    first = await service.get_or_create_for_channel(
        channel_id=channel, channel_name="Alpha", user_id=USER_A
    )
    second = await service.get_or_create_for_channel(
        channel_id=channel, channel_name="Alpha", user_id=USER_B
    )
    await async_db.commit()

    assert first.id == second.id
    rows = (
        await async_db.scalars(
            select(Project).where(Project.source_channel_id == channel)
        )
    ).all()
    assert len(rows) == 1

    members = (
        await async_db.scalars(
            select(ProjectMember).where(ProjectMember.project_id == first.id)
        )
    ).all()
    assert {m.user_id for m in members} == {USER_A, USER_B}


@pytest.mark.asyncio
async def test_channel_id_falls_back_to_the_name_when_the_channel_has_none(async_db):
    channel = CHANNEL_PREFIX + uuid4().hex
    project = await ProjectService(async_db).get_or_create_for_channel(
        channel_id=channel, channel_name="", user_id=USER_A
    )
    await async_db.commit()
    assert project.name == channel


# ============================================================================
# 3.5 — thang xác định lúc ghi
# ============================================================================


@pytest.mark.asyncio
async def test_explicit_project_wins_over_the_event_and_over_personal(async_db):
    """Bước 1 — *"đang mở dự án Alpha rồi tạo một việc"* thuộc Alpha.

    Kể cả khi việc đó gắn một sự kiện đã thuộc dự án khác: người dùng nói
    thẳng thì không có suy luận nào được đè lên.
    """
    service = ProjectService(async_db)
    alpha = await service.get_or_create_for_channel(
        channel_id=CHANNEL_PREFIX + uuid4().hex, channel_name="Alpha", user_id=USER_A
    )
    beta = await service.get_or_create_for_channel(
        channel_id=CHANNEL_PREFIX + uuid4().hex, channel_name="Beta", user_id=USER_A
    )
    event = _schedule(USER_A, "họp Beta", project_id=beta.id)
    async_db.add(event)
    await async_db.flush()

    resolved = await service.resolve_for_task(
        user_id=USER_A, explicit_project_id=alpha.id, related_event_id=event.id
    )
    await async_db.commit()
    assert resolved == alpha.id


@pytest.mark.asyncio
async def test_explicit_project_pulls_the_user_in_as_a_manual_member(async_db):
    """Chỉ định tường minh là hành động của người dùng, nên `joined_via='manual'`.

    Phân biệt này nuôi mục 4.4: tỷ lệ sửa tay trên tổng số gán `derived` là
    chỉ số chất lượng của quy tắc suy ra, và trộn hai loại vào nhau làm con
    số đó vô nghĩa.
    """
    service = ProjectService(async_db)
    alpha = await service.get_or_create_for_channel(
        channel_id=CHANNEL_PREFIX + uuid4().hex, channel_name="Alpha", user_id=USER_A
    )
    await service.resolve_for_task(user_id=USER_B, explicit_project_id=alpha.id)
    await async_db.commit()

    member = await async_db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == alpha.id, ProjectMember.user_id == USER_B
        )
    )
    assert member is not None
    assert member.joined_via == ProjectJoinSource.MANUAL


@pytest.mark.asyncio
async def test_task_takes_the_project_of_its_event_series(async_db):
    """Bước 2 — qua `related_event_id`, đọc trên hàng template."""
    service = ProjectService(async_db)
    alpha = await service.get_or_create_for_channel(
        channel_id=CHANNEL_PREFIX + uuid4().hex, channel_name="Alpha", user_id=USER_A
    )
    template = _schedule(USER_A, "chuỗi Alpha", project_id=alpha.id)
    async_db.add(template)
    await async_db.flush()

    resolved = await service.resolve_for_task(
        user_id=USER_A, related_event_id=template.id
    )
    await async_db.commit()
    assert resolved == alpha.id


@pytest.mark.asyncio
async def test_an_occurrence_reads_the_project_off_its_template(async_db):
    """Một chuỗi 30 lần lặp chỉ có MỘT hàng mang `project_id`.

    Occurrence exception trỏ về template qua `recurrence_id`; đọc project ở
    đó là thứ giữ cho một chuỗi không trôi thành ba mươi dự án khác nhau.
    """
    service = ProjectService(async_db)
    alpha = await service.get_or_create_for_channel(
        channel_id=CHANNEL_PREFIX + uuid4().hex, channel_name="Alpha", user_id=USER_A
    )
    template = _schedule(USER_A, "chuỗi Alpha", project_id=alpha.id)
    async_db.add(template)
    await async_db.flush()

    occurrence = _schedule(
        USER_A, "lần lặp bị sửa", recurrence_id=template.id, is_exception=True
    )
    async_db.add(occurrence)
    await async_db.flush()
    assert occurrence.project_id is None  # cố ý: chỉ template mang project

    resolved = await service.resolve_for_task(
        user_id=USER_A, related_event_id=occurrence.id
    )
    await async_db.commit()
    assert resolved == alpha.id


@pytest.mark.asyncio
async def test_event_without_a_project_falls_through_to_personal(async_db):
    """Phần lớn sự kiện sẽ mãi mãi không có project (4.2) — và không sao.

    Task gắn một cuộc 1:1 chưa gắn dự án vẫn phải có project: rơi xuống dự
    án cá nhân, không phải `NULL`.
    """
    event = _schedule(USER_A, "1:1 không thuộc dự án nào")
    async_db.add(event)
    await async_db.flush()

    resolved = await ProjectService(async_db).resolve_for_task(
        user_id=USER_A, related_event_id=event.id
    )
    await async_db.commit()

    personal = await async_db.scalar(
        select(Project).where(
            Project.owner_id == USER_A, Project.origin == ProjectOrigin.PERSONAL
        )
    )
    assert resolved == personal.id


@pytest.mark.asyncio
async def test_missing_event_does_not_raise_it_falls_through(async_db):
    """`related_event_id` trỏ vào hàng đã bị xoá không được làm hỏng việc tạo task."""
    resolved = await ProjectService(async_db).resolve_for_task(
        user_id=USER_A, related_event_id=uuid4()
    )
    await async_db.commit()
    personal = await async_db.scalar(
        select(Project).where(
            Project.owner_id == USER_A, Project.origin == ProjectOrigin.PERSONAL
        )
    )
    assert resolved == personal.id


# ============================================================================
# 3.3 — mọi task đều có project, qua đường tạo thật
# ============================================================================


@pytest.mark.asyncio
async def test_create_task_through_the_service_always_lands_in_a_project(async_db):
    task = await TaskService(async_db).create_task(
        TaskCreate(title=TITLE_PREFIX + "việc lẻ"), USER_A
    )
    await async_db.commit()

    assert task.project_id is not None
    personal = await async_db.scalar(
        select(Project).where(
            Project.owner_id == USER_A, Project.origin == ProjectOrigin.PERSONAL
        )
    )
    assert task.project_id == personal.id


@pytest.mark.asyncio
async def test_create_task_while_a_project_is_open_lands_in_that_project(async_db):
    """Nghiệm thu 13.1 — *không* gắn sự kiện nào mà vẫn thuộc Alpha.

    Đây chính là trường hợp mô hình "tra project lúc đọc qua sự kiện" không
    diễn đạt được, và là lý do `tasks.project_id` là cột thật (3.3).
    """
    alpha = await ProjectService(async_db).get_or_create_for_channel(
        channel_id=CHANNEL_PREFIX + uuid4().hex, channel_name="Alpha", user_id=USER_A
    )
    task = await TaskService(async_db).create_task(
        TaskCreate(title=TITLE_PREFIX + "nộp spec", project_id=alpha.id), USER_A
    )
    await async_db.commit()
    assert task.project_id == alpha.id


@pytest.mark.asyncio
async def test_a_task_without_a_project_is_refused_by_the_database(async_db):
    """`tasks.project_id` NOT NULL — hàng rào ở tầng DB.

    Không có nó thì một đường ghi mới quên gán project sẽ lặng lẽ tạo task
    mồ côi, và mọi thống kê cấp dự án thiếu đúng những hàng đó.
    """
    async_db.add(Task(user_id=USER_A, title=TITLE_PREFIX + "mồ côi"))
    with pytest.raises(Exception) as exc:
        await async_db.commit()
    assert "project_id" in str(exc.value)
    await async_db.rollback()


# ============================================================================
# QĐ-1 phát hiện #2 — hai người sync cùng một cuộc họp
# ============================================================================


@pytest.mark.asyncio
async def test_two_users_can_map_the_same_provider_event(async_db):
    """`uq_schedule_external_maps_provider_event` phải kèm `user_id`.

    `provider_calendar_id` mặc định `'primary'` cho MỌI người, nên thiếu
    `user_id` thì người thứ hai sync một cuộc họp chung sẽ fail. Lỗi có sẵn,
    chưa lộ ra chỉ vì hệ thống mới có một người dùng thật.
    """
    provider_event_id = "test-projects-event-" + uuid4().hex

    for user_id in (USER_A, USER_B):
        event = _schedule(user_id, "họp chung")
        async_db.add(event)
        await async_db.flush()
        async_db.add(
            ScheduleExternalMap(
                user_id=user_id,
                schedule_id=event.id,
                provider=CalendarProvider.GOOGLE,
                provider_calendar_id="primary",
                provider_event_id=provider_event_id,
            )
        )

    await async_db.commit()  # người thứ hai không được vướng ràng buộc

    rows = (
        await async_db.scalars(
            select(ScheduleExternalMap).where(
                ScheduleExternalMap.provider_event_id == provider_event_id
            )
        )
    ).all()
    assert {r.user_id for r in rows} == {USER_A, USER_B}

    await async_db.execute(
        delete(ScheduleExternalMap).where(
            ScheduleExternalMap.provider_event_id == provider_event_id
        )
    )
    await async_db.commit()


@pytest.mark.asyncio
async def test_a_personal_project_can_never_be_given_a_deadline(async_db):
    """Bất biến 3.4, ở tầng DB — không chỉ ở một câu `if`.

    Câu `if` trong `StateEvaluator._project_metrics` **đã từng thiếu**, và
    trong lúc nó thiếu, một hàng thật nhận `deadline` từ `max(due_date)`
    của các việc lẻ. Test khoá bắt được lỗi code; nó không chặn được đường
    ghi thứ hai — một API, một tool, một script chạy tay. CHECK constraint
    thì chặn tất cả.

    Đây là thứ duy nhất ngăn câu "Cá nhân có 47 việc quá hạn" tồn tại.
    """
    project = await ProjectService(async_db).get_or_create_personal(USER_A)
    await async_db.commit()

    project.deadline = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
    with pytest.raises(Exception) as exc:
        await async_db.commit()
    assert "ck_projects_personal_has_no_deadline" in str(exc.value)
    await async_db.rollback()
