"""
Hai predicate cấp dự án — `docs/DESIGN.md` mục 6, nghiệm thu ở 13.2.

Điều đáng canh ở đây không phải "hàm chạy đúng" mà là **khi nào nó im**.
Cortex thất bại khi nói một câu không đáng nói (1.2), và hai predicate này
là hai đường mới để nói — nên phần lớn test dưới đây khẳng định sự im lặng:
dự án cá nhân, lần đánh giá đầu tiên, hạn còn xa, một lần vượt ngưỡng.

Chạy trên Postgres + Redis dev thật, với tài khoản và dự án của riêng test.
`StateEvaluator._evaluate_projects` quét **mọi** dự án đang hoạt động, nên
mọi khẳng định ở đây đều lọc theo project id của chính nó.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.database_async import make_async_sessionmaker
from app.events.event_bus import EventBus, reset_event_bus
from app.events.schemas import EventEnvelope
from app.models import (
    AttentionItemType,
    Project,
    ProjectMember,
    ProjectOrigin,
    ProjectSnapshot,
    StateEvaluatorFlag,
    Task,
    TaskPriority,
    TaskStatus,
)
from app.services.state_evaluator import (
    PROJECT_SLIPPING_FLAG_KEY,
    PROJECT_WILL_MISS_FLAG_KEY,
    PROJECT_WILL_MISS_PENDING_FLAG_KEY,
    StateEvaluator,
)

TITLE_PREFIX = "[test-6.x] "
TEST_USER_ID = UUID("00000000-0000-4000-a000-000000000021")

PROJECT_EVENT_TYPES = ("project.slipping", "project.will_miss")


def _naive_now() -> datetime:
    """`projects.deadline`, `tasks.due_date` và `tasks.completed_at` đều là
    `DateTime` không timezone; asyncpg từ chối trộn naive với aware."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================================
# Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def async_db():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await db.execute(
            text(
                "INSERT INTO users (id, email, full_name, hashed_password, is_active, "
                "created_at, updated_at) VALUES (:id, :email, 'pytest projects predicate', "
                "'not-a-real-hash', true, NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": TEST_USER_ID, "email": "pytest-project-predicates@cortex.invalid"},
        )
        await db.commit()
        await _purge(db)
        yield db
        await _purge(db)
    await engine.dispose()


async def _purge(db) -> None:
    project_ids = list(
        (await db.execute(select(Project.id).where(Project.owner_id == TEST_USER_ID)))
        .scalars()
        .all()
    )
    if project_ids:
        await db.execute(
            delete(StateEvaluatorFlag).where(
                StateEvaluatorFlag.item_type == AttentionItemType.PROJECT,
                StateEvaluatorFlag.item_id.in_(project_ids),
            )
        )
        await db.execute(
            delete(ProjectSnapshot).where(ProjectSnapshot.project_id.in_(project_ids))
        )
    await db.execute(delete(Task).where(Task.user_id == TEST_USER_ID))
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id == TEST_USER_ID))
    await db.execute(delete(Project).where(Project.owner_id == TEST_USER_ID))
    await db.commit()


@pytest_asyncio.fixture
async def evaluator():
    ev = StateEvaluator()
    ev._db_engine, ev._session_maker = make_async_sessionmaker()
    yield ev
    await ev._db_engine.dispose()


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
async def events():
    reset_event_bus()
    bus = EventBus()
    await bus.connect()
    received: list[EventEnvelope] = []

    async def collector(event: EventEnvelope):
        received.append(event)

    for event_type in PROJECT_EVENT_TYPES:
        bus.subscribe(event_type, collector)

    import app.events.event_bus as event_bus_module

    event_bus_module._event_bus = bus
    yield received

    for event_type in PROJECT_EVENT_TYPES:
        bus.unsubscribe(event_type, collector)
    event_bus_module._event_bus = None
    await bus.disconnect()


def _for_project(received, event_type: str, project_id: UUID):
    # `model_dump()` giữ nguyên `UUID`, không đổi sang `str` — so bằng chuỗi
    # ở cả hai vế để bộ lọc không âm thầm khớp rỗng và biến mọi khẳng định
    # "có phát" thành "không phát".
    return [
        e
        for e in received
        if e.type == event_type and str(e.payload.get("project_id")) == str(project_id)
    ]


# ============================================================================
# Helpers
# ============================================================================


async def _make_project(db, *, name, deadline, origin=ProjectOrigin.MANUAL, manual=False):
    project = Project(
        owner_id=TEST_USER_ID,
        name=f"{TITLE_PREFIX}{name}",
        origin=origin,
        deadline=deadline,
        deadline_is_manual=manual,
        source_channel_id=None if origin != ProjectOrigin.DERIVED else f"chan-{uuid4().hex}",
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=TEST_USER_ID, joined_via="derived"))
    await db.flush()
    return project


async def _make_task(db, project, *, title, status=TaskStatus.TODO, due_date=None, completed_at=None):
    task = Task(
        user_id=TEST_USER_ID,
        project_id=project.id,
        title=f"{TITLE_PREFIX}{title}",
        status=status,
        due_date=due_date,
        completed_at=completed_at,
        priority=TaskPriority.MEDIUM,
    )
    db.add(task)
    await db.flush()
    return task


async def _snapshot_yesterday(db, project, *, open_count, completed_last_14d=0):
    """Một bản ghi của 'lần đánh giá trước'.

    Đặt vào hôm qua, không phải hôm nay: `_evaluate_projects` bỏ qua dự án
    đã có snapshot trong ngày, nên một bản hôm nay sẽ làm cả lượt đánh giá
    thành no-op và test đo nhầm sự im lặng.
    """
    db.add(
        ProjectSnapshot(
            project_id=project.id,
            open_count=open_count,
            completed_last_14d=completed_last_14d,
            evaluated_at=_naive_now() - timedelta(days=1),
        )
    )
    await db.commit()


async def _flags(db, project_id, flag_key):
    return list(
        (
            await db.execute(
                select(StateEvaluatorFlag).where(
                    StateEvaluatorFlag.item_type == AttentionItemType.PROJECT,
                    StateEvaluatorFlag.item_id == project_id,
                    StateEvaluatorFlag.flag_key == flag_key,
                )
            )
        )
        .scalars()
        .all()
    )


# ============================================================================
# Bất biến chịu lực: dự án cá nhân không bao giờ nói cấp dự án
# ============================================================================


class TestPersonalProjectStaysSilent:
    @pytest.mark.asyncio
    async def test_fifty_overdue_tasks_in_a_personal_project_emit_nothing(
        self, async_db, evaluator, events
    ):
        """Test khoá của DESIGN 3.4, và là tiêu chí nghiệm thu ở 13.2.

        Nếu test này biến mất, sớm muộn xuất hiện câu *"Cá nhân có 47 việc
        quá hạn"* — đúng loại nhiễu P5 cấm, và người dùng tắt bot. Thứ chặn
        nó không phải một điều kiện `if origin == personal` (dễ quên ở
        predicate thứ ba) mà bất biến `deadline IS NULL`.
        """
        personal = await _make_project(
            async_db, name="Cá nhân", deadline=None, origin=ProjectOrigin.PERSONAL
        )
        for i in range(50):
            await _make_task(
                async_db,
                personal,
                title=f"quá hạn {i}",
                due_date=_naive_now() - timedelta(days=10 + i),
            )
        await _snapshot_yesterday(async_db, personal, open_count=1)

        await evaluator._evaluate_projects()

        assert _for_project(events, "project.slipping", personal.id) == []
        assert _for_project(events, "project.will_miss", personal.id) == []
        assert await _flags(async_db, personal.id, PROJECT_SLIPPING_FLAG_KEY) == []
        assert await _flags(async_db, personal.id, PROJECT_WILL_MISS_FLAG_KEY) == []

    @pytest.mark.asyncio
    async def test_it_still_gets_a_snapshot_so_the_rule_is_the_deadline_not_the_skip(
        self, async_db, evaluator, events
    ):
        """Dự án cá nhân vẫn được đo, chỉ không được *nói*.

        Phân biệt này quan trọng: nếu bỏ qua hẳn thì ngày nó có deadline —
        người dùng đặt tay — nó sẽ không có lịch sử để so, và predicate đầu
        tiên phát ra sẽ dựa trên một con số không nền.
        """
        personal = await _make_project(
            async_db, name="Cá nhân", deadline=None, origin=ProjectOrigin.PERSONAL
        )
        await _make_task(async_db, personal, title="một việc")
        await async_db.commit()

        await evaluator._evaluate_projects()

        snapshots = list(
            (
                await async_db.execute(
                    select(ProjectSnapshot).where(ProjectSnapshot.project_id == personal.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(snapshots) == 1
        assert snapshots[0].open_count == 1


# ============================================================================
# project.slipping — DESIGN 6.1
# ============================================================================


class TestProjectSlipping:
    @pytest.mark.asyncio
    async def test_the_first_evaluation_never_fires(self, async_db, evaluator, events):
        """Không có lần trước thì không có khái niệm "tăng".

        Nếu thiếu nhánh này, mọi dự án mới đều phát `slipping` ngay lần đầu —
        lời chào đầu tiên của Cortex với một dự án là một cảnh báo sai.
        """
        project = await _make_project(
            async_db, name="Alpha", deadline=_naive_now() + timedelta(days=5)
        )
        for i in range(5):
            await _make_task(async_db, project, title=f"việc {i}")
        await async_db.commit()

        await evaluator._evaluate_projects()

        assert _for_project(events, "project.slipping", project.id) == []

    @pytest.mark.asyncio
    async def test_open_work_growing_inside_the_horizon_fires(
        self, async_db, evaluator, events
    ):
        project = await _make_project(
            async_db, name="Alpha", deadline=_naive_now() + timedelta(days=5)
        )
        # Task phải có hạn: `deadline` của dự án được suy ra từ
        # `max(due_date)` (DESIGN 4.3), nên một dự án toàn việc không hạn
        # có `deadline IS NULL` và im — đúng thiết kế, nhưng không phải thứ
        # test này đo.
        for i in range(5):
            await _make_task(
                async_db, project, title=f"việc {i}", due_date=_naive_now() + timedelta(days=5)
            )
        await _snapshot_yesterday(async_db, project, open_count=2)

        await evaluator._evaluate_projects()

        published = _for_project(events, "project.slipping", project.id)
        assert len(published) == 1
        payload = published[0].payload
        # Hai con số đi cùng nhau: "5 việc mở" một mình không đọc được.
        assert payload["open_count"] == 5
        assert payload["previous_open_count"] == 2
        assert payload["days_to_deadline"] == 5

    @pytest.mark.asyncio
    async def test_a_distant_deadline_stays_silent(self, async_db, evaluator, events):
        """Ngoài chân trời 14 ngày, việc mở tăng là chuyện bình thường của
        một dự án đang chạy — không phải tín hiệu trượt."""
        project = await _make_project(
            async_db, name="Alpha", deadline=_naive_now() + timedelta(days=60)
        )
        for i in range(5):
            await _make_task(async_db, project, title=f"việc {i}")
        await _snapshot_yesterday(async_db, project, open_count=2)

        await evaluator._evaluate_projects()

        assert _for_project(events, "project.slipping", project.id) == []

    @pytest.mark.asyncio
    async def test_open_work_shrinking_stays_silent(self, async_db, evaluator, events):
        project = await _make_project(
            async_db, name="Alpha", deadline=_naive_now() + timedelta(days=5)
        )
        await _make_task(async_db, project, title="việc còn lại")
        await _snapshot_yesterday(async_db, project, open_count=9)

        await evaluator._evaluate_projects()

        assert _for_project(events, "project.slipping", project.id) == []


# ============================================================================
# project.will_miss — DESIGN 6.2
# ============================================================================


class TestProjectWillMiss:
    @pytest.mark.asyncio
    async def test_one_crossing_only_arms_it_two_publishes(
        self, async_db, evaluator, events
    ):
        """Chống rung (DESIGN 4.3): `deadline` suy ra từ `max(due_date)` nên
        nó nhảy mỗi lần thêm hoặc xong một việc. Phát ngay lần vượt đầu tiên
        nghĩa là bật/tắt theo từng lần ghi — lời nhắc sẽ tự mâu thuẫn với
        chính nó trong cùng một tuần.
        """
        project = await _make_project(
            async_db, name="Alpha", deadline=_naive_now() + timedelta(days=2)
        )
        for i in range(20):
            await _make_task(
                async_db, project, title=f"việc {i}", due_date=_naive_now() + timedelta(days=2)
            )
        await _snapshot_yesterday(async_db, project, open_count=20)

        await evaluator._evaluate_projects()
        assert _for_project(events, "project.will_miss", project.id) == []
        assert len(await _flags(async_db, project.id, PROJECT_WILL_MISS_PENDING_FLAG_KEY)) == 1

        # Lượt sau: xoá snapshot của hôm nay để dự án đủ điều kiện đánh giá
        # lại, đúng như ngày hôm sau sẽ xảy ra.
        await async_db.execute(
            delete(ProjectSnapshot).where(ProjectSnapshot.project_id == project.id)
        )
        await _snapshot_yesterday(async_db, project, open_count=20)

        await evaluator._evaluate_projects()
        published = _for_project(events, "project.will_miss", project.id)
        assert len(published) == 1
        assert published[0].payload["open_count"] == 20
        assert published[0].payload["completed_last_14d"] == 0

    @pytest.mark.asyncio
    async def test_a_finished_project_is_not_going_to_miss_anything(
        self, async_db, evaluator, events
    ):
        """Không còn việc mở thì không có gì để trễ. Tốc độ 0 **cộng với**
        việc mở còn lại mới là tín hiệu; tốc độ 0 một mình thì không."""
        project = await _make_project(
            async_db, name="Alpha", deadline=_naive_now() - timedelta(days=1)
        )
        await _make_task(
            async_db,
            project,
            title="đã xong",
            status=TaskStatus.DONE,
            completed_at=_naive_now() - timedelta(days=30),
        )
        await _snapshot_yesterday(async_db, project, open_count=0)
        await evaluator._evaluate_projects()
        await async_db.execute(
            delete(ProjectSnapshot).where(ProjectSnapshot.project_id == project.id)
        )
        await _snapshot_yesterday(async_db, project, open_count=0)
        await evaluator._evaluate_projects()

        assert _for_project(events, "project.will_miss", project.id) == []

    @pytest.mark.asyncio
    async def test_a_fast_enough_pace_stays_silent(self, async_db, evaluator, events):
        """Cảnh báo *trước* khi trễ chỉ có giá trị nếu nó im khi không trễ."""
        project = await _make_project(
            async_db, name="Alpha", deadline=_naive_now() + timedelta(days=30), manual=True
        )
        for i in range(2):
            await _make_task(async_db, project, title=f"còn lại {i}")
        for i in range(14):
            await _make_task(
                async_db,
                project,
                title=f"đã xong {i}",
                status=TaskStatus.DONE,
                completed_at=_naive_now() - timedelta(days=1),
            )
        await _snapshot_yesterday(async_db, project, open_count=2)

        await evaluator._evaluate_projects()
        assert await _flags(async_db, project.id, PROJECT_WILL_MISS_PENDING_FLAG_KEY) == []
        assert _for_project(events, "project.will_miss", project.id) == []


# ============================================================================
# Nhịp đánh giá và suy ra deadline — DESIGN 4.3
# ============================================================================


class TestCadenceAndDerivedDeadline:
    @pytest.mark.asyncio
    async def test_a_project_is_evaluated_once_a_day_not_once_a_tick(
        self, async_db, evaluator, events
    ):
        """`StateEvaluator` tick mỗi 5 phút. Đánh giá dự án theo tick sẽ
        biến "số việc mở tăng so với lần trước" thành nhiễu giữa hai lần ghi
        cách nhau vài phút."""
        project = await _make_project(
            async_db, name="Alpha", deadline=_naive_now() + timedelta(days=5)
        )
        await _make_task(async_db, project, title="việc")
        await async_db.commit()

        await evaluator._evaluate_projects()
        await evaluator._evaluate_projects()
        await evaluator._evaluate_projects()

        snapshots = list(
            (
                await async_db.execute(
                    select(ProjectSnapshot).where(ProjectSnapshot.project_id == project.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(snapshots) == 1

    @pytest.mark.asyncio
    async def test_deadline_is_derived_from_the_last_due_date(
        self, async_db, evaluator, events
    ):
        project = await _make_project(async_db, name="Alpha", deadline=None)
        await _make_task(
            async_db, project, title="sớm", due_date=_naive_now() + timedelta(days=3)
        )
        last = _naive_now() + timedelta(days=9)
        await _make_task(async_db, project, title="muộn nhất", due_date=last)
        await async_db.commit()

        await evaluator._evaluate_projects()
        await async_db.refresh(project)

        assert project.deadline is not None
        assert project.deadline.date() == last.date()

    @pytest.mark.asyncio
    async def test_a_hand_set_deadline_is_never_overwritten(
        self, async_db, evaluator, events
    ):
        """`deadline_is_manual` — suy ra là mặc định, không phải phán quyết.

        Người dùng sửa tay một lần rồi thấy nó bị ghi đè vào sáng hôm sau là
        cách nhanh nhất để họ ngừng sửa bất cứ thứ gì.
        """
        chosen = _naive_now() + timedelta(days=2)
        project = await _make_project(
            async_db, name="Alpha", deadline=chosen, manual=True
        )
        await _make_task(
            async_db, project, title="hạn xa", due_date=_naive_now() + timedelta(days=90)
        )
        await async_db.commit()

        await evaluator._evaluate_projects()
        await async_db.refresh(project)

        assert project.deadline.date() == chosen.date()
