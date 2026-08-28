"""
API dự án — `docs/DESIGN.md` mục 9.1.

Hai thứ đáng canh nhất ở đây không phải CRUD:

**Quyền đi qua `project_members`, không qua `owner_id`** (QĐ-1). Project là
thực thể dùng chung; lọc theo owner sẽ làm người thứ hai nhận việc từ một
channel không thấy dự án mà họ vừa được thêm vào — hỏng đúng tính năng mà
QĐ-1 tồn tại để bật.

**Gán chuỗi sự kiện không ghi đè task cũ** (3.5). Đây là chỗ dễ "sửa cho
tiện" nhất trong cả mục 9, và làm thế là hành vi phá hoại dữ liệu.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.database_async import make_async_sessionmaker
from app.models import (
    Project,
    ProjectMember,
    ProjectOrigin,
    ProjectStatus,
    Schedule,
    ScheduleType,
    Task,
    TaskStatus,
)
from app.services.projects import ProjectService

PREFIX = "[test-9.1] "
USER_A = UUID("00000000-0000-4000-a000-000000000031")
USER_B = UUID("00000000-0000-4000-a000-000000000032")


def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _ensure_user(db, user_id, email) -> None:
    await db.execute(
        text(
            "INSERT INTO users (id, email, full_name, hashed_password, is_active, "
            "created_at, updated_at) VALUES (:id, :email, 'pytest 9.1', "
            "'not-a-real-hash', true, NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": email},
    )


async def _purge(db) -> None:
    project_ids = list(
        (await db.execute(select(Project.id).where(Project.owner_id.in_([USER_A, USER_B]))))
        .scalars()
        .all()
    )
    await db.execute(delete(Task).where(Task.user_id.in_([USER_A, USER_B])))
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
        await _ensure_user(db, USER_A, "pytest-9-1-a@cortex.invalid")
        await _ensure_user(db, USER_B, "pytest-9-1-b@cortex.invalid")
        await db.commit()
        await _purge(db)
        yield db
        await _purge(db)
    await engine.dispose()


def _client_for(user_id: UUID):
    """`api_client` gắn với một tài khoản cụ thể.

    Hai tài khoản là bắt buộc chứ không phải cho đủ bộ: mọi khẳng định về
    quyền ở đây đều là "B thấy/không thấy dự án của A", và một client thì
    không kiểm được điều đó.
    """

    @pytest_asyncio.fixture
    async def _fixture(async_db):
        from app import app
        from app.database import SessionLocal, get_db
        from app.database_async import get_async_db
        from app.dependencies import get_current_active_user, get_current_user_or_internal

        class _StubUser:
            id = user_id

        def _override_sync_db():
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()

        async def _override_async_db():
            yield async_db

        app.dependency_overrides[get_current_active_user] = lambda: _StubUser()
        app.dependency_overrides[get_current_user_or_internal] = lambda: _StubUser()
        app.dependency_overrides[get_db] = _override_sync_db
        app.dependency_overrides[get_async_db] = _override_async_db

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test/api") as client:
            yield client

        app.dependency_overrides.clear()

    return _fixture


client_a = _client_for(USER_A)
client_b = _client_for(USER_B)


async def _make_project(db, *, owner, name, origin=ProjectOrigin.MANUAL, deadline=None, channel=None):
    project = Project(
        owner_id=owner,
        name=f"{PREFIX}{name}",
        origin=origin,
        deadline=deadline,
        source_channel_id=channel,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=owner, joined_via="derived"))
    await db.commit()
    return project


# ============================================================================
# GET /projects
# ============================================================================


@pytest.mark.asyncio
async def test_listing_returns_projects_you_are_a_member_of_not_ones_you_own(
    async_db, client_b
):
    """QĐ-1 nói thẳng: *"dự án của tôi" tra qua `project_members`, không qua
    `owner_id`*. Đây là test khoá câu đó.

    A tạo dự án, B được thêm vào — B phải thấy nó. Nếu endpoint lọc theo
    owner, người thứ hai nhận việc từ một channel sẽ không bao giờ thấy dự
    án mà quy tắc 4.1 vừa đưa họ vào.
    """
    project = await _make_project(async_db, owner=USER_A, name="Alpha")
    await ProjectService(async_db).ensure_member(project.id, USER_B)
    await async_db.commit()

    response = await client_b.get("/projects")
    assert response.status_code == 200, response.text
    names = [p["name"] for p in response.json()]
    assert f"{PREFIX}Alpha" in names


@pytest.mark.asyncio
async def test_a_stranger_does_not_see_the_project(async_db, client_b):
    await _make_project(async_db, owner=USER_A, name="Alpha")

    response = await client_b.get("/projects")
    assert response.status_code == 200
    assert [p["name"] for p in response.json()] == []


@pytest.mark.asyncio
async def test_closed_projects_are_out_of_the_default_list(async_db, client_a):
    """Danh sách mặc định là *dự án đang mở*, không phải kho lưu trữ — bộ
    chuyển dự án trên topbar đọc thẳng endpoint này."""
    project = await _make_project(async_db, owner=USER_A, name="Đã xong")
    project.status = ProjectStatus.CLOSED
    await async_db.commit()

    assert (await client_a.get("/projects")).json() == []
    everything = await client_a.get("/projects", params={"status": "closed"})
    assert [p["name"] for p in everything.json()] == [f"{PREFIX}Đã xong"]


@pytest.mark.asyncio
async def test_the_summary_counts_come_back_with_the_project(async_db, client_a):
    """Số liệu đi kèm chứ không ở endpoint riêng: mọi bề mặt hiển thị một
    dự án đều cần chúng cùng lúc, và tách ra chỉ tạo N+1 ở phía client."""
    project = await _make_project(async_db, owner=USER_A, name="Alpha")
    for i in range(3):
        async_db.add(
            Task(
                user_id=USER_A,
                project_id=project.id,
                title=f"{PREFIX}mở {i}",
                status=TaskStatus.TODO,
            )
        )
    async_db.add(
        Task(
            user_id=USER_A,
            project_id=project.id,
            title=f"{PREFIX}xong",
            status=TaskStatus.DONE,
        )
    )
    await async_db.commit()

    body = (await client_a.get("/projects")).json()[0]
    assert body["open_task_count"] == 3
    assert body["completed_task_count"] == 1
    assert body["member_count"] == 1
    assert body["risk"] == 0.0  # không hạn, không việc nào quá hạn


# ============================================================================
# POST / PATCH /projects
# ============================================================================


@pytest.mark.asyncio
async def test_manual_creation_is_marked_manual_not_derived(async_db, client_a):
    """Phân biệt này nuôi 4.4: trộn dự án tạo tay vào mẫu số làm tỷ lệ sửa
    quy gán — chỉ số chất lượng của quy tắc suy ra — mất nghĩa."""
    response = await client_a.post("/projects", json={"name": f"{PREFIX}Tay"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["origin"] == "manual"
    assert body["source_channel_id"] is None
    assert body["member_count"] == 1


@pytest.mark.asyncio
async def test_setting_a_deadline_locks_it_against_the_daily_derivation(
    async_db, client_a
):
    """`deadline_is_manual` — người dùng sửa tay một lần rồi thấy nó bị ghi
    đè vào sáng hôm sau là cách nhanh nhất để họ ngừng sửa bất cứ thứ gì."""
    project = await _make_project(async_db, owner=USER_A, name="Alpha")
    assert project.deadline_is_manual is False

    chosen = (_naive_now() + timedelta(days=7)).isoformat()
    response = await client_a.patch(f"/projects/{project.id}", json={"deadline": chosen})
    assert response.status_code == 200, response.text
    assert response.json()["deadline_is_manual"] is True


@pytest.mark.asyncio
async def test_clearing_the_deadline_is_a_real_intention_not_a_missing_field(
    async_db, client_a
):
    """`null` là "bỏ hạn", khác hẳn "không nhắc tới hạn".

    Kiểm bằng `is not None` — cách viết tự nhiên hơn — sẽ làm thao tác này
    trở nên không thể thực hiện, và không ai phát hiện ra cho tới khi có
    người thật muốn gỡ hạn khỏi một dự án.
    """
    project = await _make_project(
        async_db, owner=USER_A, name="Alpha", deadline=_naive_now() + timedelta(days=3)
    )

    response = await client_a.patch(f"/projects/{project.id}", json={"deadline": None})
    assert response.status_code == 200, response.text
    assert response.json()["deadline"] is None
    assert response.json()["deadline_is_manual"] is True


@pytest.mark.asyncio
async def test_renaming_does_not_touch_the_deadline_lock(async_db, client_a):
    """Chỉ *chạm vào* `deadline` mới khoá nó. Một body chỉ đổi tên không
    được biến dự án thành "hạn do người dùng đặt"."""
    project = await _make_project(async_db, owner=USER_A, name="Alpha")
    response = await client_a.patch(f"/projects/{project.id}", json={"name": f"{PREFIX}Beta"})
    assert response.status_code == 200
    assert response.json()["name"] == f"{PREFIX}Beta"
    assert response.json()["deadline_is_manual"] is False


@pytest.mark.asyncio
async def test_a_non_member_gets_404_not_403(async_db, client_b):
    """404, không phải 403: 403 xác nhận có một dự án id như vậy tồn tại."""
    project = await _make_project(async_db, owner=USER_A, name="Alpha")
    assert (await client_b.get(f"/projects/{project.id}")).status_code == 404
    assert (
        await client_b.patch(f"/projects/{project.id}", json={"name": "x"})
    ).status_code == 404


@pytest.mark.asyncio
async def test_there_is_no_delete_endpoint(async_db, client_a):
    """Cố ý thiếu (DESIGN 9.1): `status='closed'` là đủ, và xoá sẽ mồ côi
    lịch sử `attention_log`."""
    project = await _make_project(async_db, owner=USER_A, name="Alpha")
    assert (await client_a.delete(f"/projects/{project.id}")).status_code == 405


# ============================================================================
# PATCH /tasks/{id}/project — lối sửa của 10.1, nhãn của 4.4
# ============================================================================


@pytest.mark.asyncio
async def test_moving_a_task_records_the_correction_label(async_db, client_a):
    alpha = await _make_project(async_db, owner=USER_A, name="Alpha")
    beta = await _make_project(async_db, owner=USER_A, name="Beta")
    task = Task(
        user_id=USER_A, project_id=alpha.id, title=f"{PREFIX}nộp spec", status=TaskStatus.TODO
    )
    async_db.add(task)
    await async_db.commit()

    response = await client_a.patch(
        f"/tasks/{task.id}/project", json={"project_id": str(beta.id)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["project_id"] == str(beta.id)

    await async_db.refresh(task)
    assert task.project_id_corrected is True


@pytest.mark.asyncio
async def test_moving_a_task_leaves_its_origin_alone(async_db, client_a):
    """**Không đụng `related_event_id`** (9.1/9.2).

    Task này sinh ra từ cuộc họp nào là một sự thật lịch sử; nó không đổi
    vì task được xếp lại vào dự án khác. Gộp hai quan hệ sẽ làm mất câu trả
    lời cho "Cortex lấy việc này ở đâu ra".
    """
    alpha = await _make_project(async_db, owner=USER_A, name="Alpha")
    beta = await _make_project(async_db, owner=USER_A, name="Beta")
    start = datetime.now(timezone.utc) + timedelta(days=1)
    event = Schedule(
        user_id=USER_A,
        title=f"{PREFIX}họp",
        type=ScheduleType.CLASS,
        start_time=start,
        end_time=start + timedelta(hours=1),
    )
    async_db.add(event)
    await async_db.flush()
    task = Task(
        user_id=USER_A,
        project_id=alpha.id,
        title=f"{PREFIX}từ cuộc họp",
        status=TaskStatus.TODO,
        related_event_id=event.id,
    )
    async_db.add(task)
    await async_db.commit()

    await client_a.patch(f"/tasks/{task.id}/project", json={"project_id": str(beta.id)})
    await async_db.refresh(task)

    assert task.project_id == beta.id
    assert task.related_event_id == event.id


@pytest.mark.asyncio
async def test_re_setting_the_same_project_is_not_counted_as_a_correction(
    async_db, client_a
):
    """Một lần bấm thừa không phải là quy tắc suy ra sai. Đếm nó vào sẽ làm
    tỷ lệ ở 4.4 phồng lên và đẩy quyết định "sửa quy tắc" đi sai hướng."""
    alpha = await _make_project(async_db, owner=USER_A, name="Alpha")
    task = Task(
        user_id=USER_A, project_id=alpha.id, title=f"{PREFIX}việc", status=TaskStatus.TODO
    )
    async_db.add(task)
    await async_db.commit()

    await client_a.patch(f"/tasks/{task.id}/project", json={"project_id": str(alpha.id)})
    await async_db.refresh(task)
    assert task.project_id_corrected is False


@pytest.mark.asyncio
async def test_moving_into_a_project_you_cannot_see_is_refused(async_db, client_a):
    theirs = await _make_project(async_db, owner=USER_B, name="Của B")
    mine = await _make_project(async_db, owner=USER_A, name="Của A")
    task = Task(
        user_id=USER_A, project_id=mine.id, title=f"{PREFIX}việc", status=TaskStatus.TODO
    )
    async_db.add(task)
    await async_db.commit()

    response = await client_a.patch(
        f"/tasks/{task.id}/project", json={"project_id": str(theirs.id)}
    )
    assert response.status_code == 404


# ============================================================================
# PATCH /schedules/{id}/project — DESIGN 3.2, 3.5
# ============================================================================


async def _series(db, *, title="chuỗi"):
    start = datetime.now(timezone.utc) + timedelta(days=1)
    template = Schedule(
        user_id=USER_A,
        title=f"{PREFIX}{title}",
        type=ScheduleType.CLASS,
        start_time=start,
        end_time=start + timedelta(hours=1),
    )
    db.add(template)
    await db.flush()
    return template


@pytest.mark.asyncio
async def test_assigning_a_series_reports_how_many_old_tasks_it_did_not_touch(
    async_db, client_a
):
    """Nghiệm thu của 3.5: gán chuỗi **không** ghi đè project của task cũ,
    và API trả về số task bị ảnh hưởng để UI *hỏi* thay vì làm im lặng.

    Ghi đè hàng loạt ở đây là hành vi phá hoại: task đã có project riêng,
    có thể do chính người dùng sửa tay ở 10.1.
    """
    alpha = await _make_project(async_db, owner=USER_A, name="Alpha")
    personal = await _make_project(
        async_db, owner=USER_A, name="Cá nhân", origin=ProjectOrigin.PERSONAL
    )
    template = await _series(async_db)
    for i in range(2):
        async_db.add(
            Task(
                user_id=USER_A,
                project_id=personal.id,
                title=f"{PREFIX}việc cũ {i}",
                status=TaskStatus.TODO,
                related_event_id=template.id,
            )
        )
    await async_db.commit()

    response = await client_a.patch(
        f"/schedules/{template.id}/project", json={"project_id": str(alpha.id)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["affected_task_count"] == 2

    # Và chúng thật sự không bị đụng tới.
    still_personal = list(
        (
            await async_db.scalars(
                select(Task).where(Task.related_event_id == template.id)
            )
        ).all()
    )
    assert {t.project_id for t in still_personal} == {personal.id}


@pytest.mark.asyncio
async def test_an_occurrence_exception_is_refused(async_db, client_a):
    """Chỉ hàng template (DESIGN 3.2). Đặt lên occurrence thì một chuỗi 30
    lần lặp sinh 30 hàng cùng project và quy tắc suy ra sẽ trôi."""
    alpha = await _make_project(async_db, owner=USER_A, name="Alpha")
    template = await _series(async_db)
    start = datetime.now(timezone.utc) + timedelta(days=2)
    occurrence = Schedule(
        user_id=USER_A,
        title=f"{PREFIX}lần lặp",
        type=ScheduleType.CLASS,
        start_time=start,
        end_time=start + timedelta(hours=1),
        recurrence_id=template.id,
        is_exception=True,
    )
    async_db.add(occurrence)
    await async_db.commit()

    response = await client_a.patch(
        f"/schedules/{occurrence.id}/project", json={"project_id": str(alpha.id)}
    )
    assert response.status_code == 400
    assert "template" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unlinking_a_series_is_allowed(async_db, client_a):
    alpha = await _make_project(async_db, owner=USER_A, name="Alpha")
    template = await _series(async_db)
    template.project_id = alpha.id
    await async_db.commit()

    response = await client_a.patch(
        f"/schedules/{template.id}/project", json={"project_id": None}
    )
    assert response.status_code == 200
    assert response.json()["project_id"] is None
    await async_db.refresh(template)
    assert template.project_id is None
