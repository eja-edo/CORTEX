"""
Bốn tool dự án và quy tắc giải `project_ref` — `docs/DESIGN.md` mục 9.2.

Tiêu chí nghiệm thu của Tuần 1 (13.2) là *"agent thao tác được hai dự án
khác nhau trong cùng một hội thoại mà không nhầm"*, và điều làm nó đúng
không phải bốn handler mà là **một quyết định**: không có "dự án hiện tại"
ở mức phiên. Mọi lời gọi mang `project_ref` tường minh.

Nên phần lớn test ở đây đo ba nhánh của bộ giải tên, và đặc biệt là nhánh
thứ ba: **không khớp thì liệt kê, không đoán, không tự tạo** (P7). Agent tự
tạo dự án `"Alpah"` vì người dùng gõ sai chính tả là kiểu hỏng im lặng tệ
nhất — nó tạo dữ liệu rác mà không ai nhận ra cho tới khi một báo cáo cấp
dự án nói sai.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.ai.agents.tool_context import ToolContext
from app.ai.tools.create_project import create_project_handler
from app.ai.tools.create_task import create_task_handler
from app.ai.tools.get_project_tasks import get_project_tasks_handler
from app.ai.tools.list_projects import list_projects_handler
from app.ai.tools.move_task import move_task_handler
from app.database_async import make_async_sessionmaker
from app.models import (
    Project,
    ProjectMember,
    ProjectOrigin,
    ProjectStatus,
    Task,
    TaskStatus,
)

PREFIX = "[test-9.2] "
TEST_USER_ID = UUID("00000000-0000-4000-a000-000000000041")


def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _purge(db) -> None:
    ids = list(
        (await db.execute(select(Project.id).where(Project.owner_id == TEST_USER_ID)))
        .scalars()
        .all()
    )
    await db.execute(delete(Task).where(Task.user_id == TEST_USER_ID))
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id == TEST_USER_ID))
    if ids:
        await db.execute(delete(ProjectMember).where(ProjectMember.project_id.in_(ids)))
        await db.execute(delete(Project).where(Project.id.in_(ids)))
    await db.commit()


@pytest_asyncio.fixture
async def async_db():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        await db.execute(
            text(
                "INSERT INTO users (id, email, full_name, hashed_password, is_active, "
                "created_at, updated_at) VALUES (:id, :email, 'pytest 9.2', "
                "'not-a-real-hash', true, NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": TEST_USER_ID, "email": "pytest-9-2@cortex.invalid"},
        )
        await db.commit()
        await _purge(db)
        yield db
        await _purge(db)
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


@pytest_asyncio.fixture
def ctx(async_db):
    return ToolContext(user_id=TEST_USER_ID, async_db=async_db)


async def _project(db, name, *, origin=ProjectOrigin.MANUAL, deadline=None, status=ProjectStatus.ACTIVE):
    project = Project(
        owner_id=TEST_USER_ID,
        name=name,
        origin=origin,
        deadline=deadline,
        status=status,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=TEST_USER_ID, joined_via="derived"))
    await db.commit()
    return project


async def _task(db, project, title, *, status=TaskStatus.TODO, due_date=None):
    task = Task(
        user_id=TEST_USER_ID,
        project_id=project.id,
        title=f"{PREFIX}{title}",
        status=status,
        due_date=due_date,
    )
    db.add(task)
    await db.commit()
    return task


# ============================================================================
# Giải `project_ref` — ba nhánh
# ============================================================================


class TestProjectRefResolution:
    @pytest.mark.asyncio
    async def test_an_unknown_name_lists_projects_and_refuses_to_guess(
        self, async_db, ctx
    ):
        """P7, và là lý do cả module `project_ref.py` tồn tại.

        Người dùng gõ "Alpah". Tool phải trả về danh sách và một chỉ dẫn
        **không đoán, không tự tạo** — chứ không âm thầm chọn "Alpha" vì
        nó gần giống.
        """
        await _project(async_db, f"{PREFIX}Alpha")
        await _project(async_db, f"{PREFIX}Beta")

        result = await get_project_tasks_handler({"project_ref": "Alpah"}, ctx)

        assert result["success"] is False
        assert result["error"] == "project_not_found"
        assert len(result["projects"]) == 2
        assert "KHÔNG đoán" in result["next_step"]
        assert "KHÔNG tự tạo" in result["next_step"]

    @pytest.mark.asyncio
    async def test_an_ambiguous_name_asks_instead_of_picking(self, async_db, ctx):
        """Khớp nhiều tên → `ask_user_choice`, không phải "lấy cái đầu tiên".

        Lấy cái đầu tiên là hành vi *trông như* hoạt động: nó đúng khoảng
        một nửa số lần, và nửa còn lại không ai phát hiện ra.
        """
        await _project(async_db, f"{PREFIX}Alpha web")
        await _project(async_db, f"{PREFIX}Alpha mobile")

        result = await get_project_tasks_handler({"project_ref": "Alpha"}, ctx)

        assert result["success"] is False
        assert result["error"] == "ambiguous_project_ref"
        assert len(result["matches"]) == 2
        assert "ask_user_choice" in result["next_step"]

    @pytest.mark.asyncio
    async def test_an_exact_name_beats_a_partial_one(self, async_db, ctx):
        """`Alpha` và `Alpha v2` là hai dự án khác nhau.

        Không có nhánh "khớp chính xác thắng", một dự án tên `Alpha` sẽ
        vĩnh viễn không gọi tên được khi tồn tại `Alpha v2`.
        """
        alpha = await _project(async_db, f"{PREFIX}Alpha")
        await _project(async_db, f"{PREFIX}Alpha v2")
        await _task(async_db, alpha, "việc của Alpha")

        result = await get_project_tasks_handler({"project_ref": f"{PREFIX}Alpha"}, ctx)

        assert result["success"] is True
        assert result["project"]["id"] == str(alpha.id)

    @pytest.mark.asyncio
    async def test_an_id_resolves_too_so_a_follow_up_call_is_unambiguous(
        self, async_db, ctx
    ):
        """Sau `ask_user_choice`, agent gọi lại bằng id — đường đó phải chạy,
        nếu không nhánh nhập nhằng không có lối thoát."""
        alpha = await _project(async_db, f"{PREFIX}Alpha web")
        await _project(async_db, f"{PREFIX}Alpha mobile")

        result = await get_project_tasks_handler({"project_ref": str(alpha.id)}, ctx)
        assert result["success"] is True
        assert result["project"]["id"] == str(alpha.id)


# ============================================================================
# list_projects
# ============================================================================


class TestListProjects:
    @pytest.mark.asyncio
    async def test_the_personal_project_is_hidden_by_default(self, async_db, ctx):
        """DESIGN 9.2 — nó là nơi mọi việc lẻ rơi vào, nên nó xuất hiện ở
        *mọi* lần liệt kê và chiếm chỗ trong ngữ cảnh mỗi lượt."""
        await _project(async_db, f"{PREFIX}Alpha")
        await _project(async_db, f"{PREFIX}Cá nhân", origin=ProjectOrigin.PERSONAL)

        default = await list_projects_handler({}, ctx)
        assert [p["name"] for p in default["projects"]] == [f"{PREFIX}Alpha"]

        asked = await list_projects_handler({"include_personal": True}, ctx)
        assert len(asked["projects"]) == 2

    @pytest.mark.asyncio
    async def test_closed_projects_are_out_by_default(self, async_db, ctx):
        await _project(async_db, f"{PREFIX}Alpha")
        await _project(async_db, f"{PREFIX}Xong", status=ProjectStatus.CLOSED)

        result = await list_projects_handler({}, ctx)
        assert [p["name"] for p in result["projects"]] == [f"{PREFIX}Alpha"]

    @pytest.mark.asyncio
    async def test_it_carries_the_numbers_the_agent_needs_to_answer_with(
        self, async_db, ctx
    ):
        """Số liệu đi kèm để agent không phải gọi thêm một vòng tool nữa chỉ
        để trả lời *"Alpha còn bao nhiêu việc"*."""
        alpha = await _project(async_db, f"{PREFIX}Alpha")
        await _task(async_db, alpha, "mở")
        await _task(async_db, alpha, "xong", status=TaskStatus.DONE)

        result = await list_projects_handler({}, ctx)
        entry = result["projects"][0]
        assert entry["open_task_count"] == 1
        assert entry["completed_task_count"] == 1
        assert "risk" in entry


# ============================================================================
# move_task
# ============================================================================


class TestMoveTask:
    @pytest.mark.asyncio
    async def test_it_moves_and_records_the_correction_label(self, async_db, ctx):
        alpha = await _project(async_db, f"{PREFIX}Alpha")
        beta = await _project(async_db, f"{PREFIX}Beta")
        task = await _task(async_db, alpha, "nộp spec")

        result = await move_task_handler(
            {"task_id": str(task.id), "project_ref": f"{PREFIX}Beta"}, ctx
        )

        assert result["success"] is True
        assert result["moved"] is True
        await async_db.refresh(task)
        assert task.project_id == beta.id
        assert task.project_id_corrected is True

    @pytest.mark.asyncio
    async def test_it_refuses_rather_than_creating_the_destination(
        self, async_db, ctx
    ):
        """Nhánh hỏng tệ nhất mà 9.2 gọi tên: tạo dự án để cho lời gọi
        thành công. Không dự án nào được sinh ra ở đây."""
        alpha = await _project(async_db, f"{PREFIX}Alpha")
        task = await _task(async_db, alpha, "việc")

        result = await move_task_handler(
            {"task_id": str(task.id), "project_ref": "Không có thật"}, ctx
        )

        assert result["success"] is False
        count = await async_db.scalar(
            select(Project.id).where(Project.name == "Không có thật")
        )
        assert count is None
        await async_db.refresh(task)
        assert task.project_id == alpha.id

    @pytest.mark.asyncio
    async def test_a_task_that_is_not_yours_is_not_found(self, async_db, ctx):
        await _project(async_db, f"{PREFIX}Alpha")
        result = await move_task_handler(
            {"task_id": str(uuid4()), "project_ref": f"{PREFIX}Alpha"}, ctx
        )
        assert result["success"] is False
        assert result["error"] == "task_not_found"


# ============================================================================
# create_project — tool bị hạn chế nhất
# ============================================================================


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_it_reuses_an_existing_project_with_the_same_name(
        self, async_db, ctx
    ):
        """Hai dự án cùng tên là trạng thái người dùng không sửa được: mọi
        `project_ref` về sau đều nhập nhằng, mãi mãi."""
        existing = await _project(async_db, f"{PREFIX}Alpha")

        result = await create_project_handler({"name": f"{PREFIX}Alpha"}, ctx)

        assert result["success"] is True
        assert result["created"] is False
        assert result["project"]["id"] == str(existing.id)

    @pytest.mark.asyncio
    async def test_a_new_name_creates_a_manual_project(self, async_db, ctx):
        result = await create_project_handler({"name": f"{PREFIX}Gamma"}, ctx)

        assert result["created"] is True
        project = await async_db.get(Project, UUID(result["project"]["id"]))
        # `manual`, không phải `derived` — trộn hai loại làm tỷ lệ ở 4.4
        # mất nghĩa.
        assert project.origin is ProjectOrigin.MANUAL
        assert project.source_channel_id is None

    @pytest.mark.asyncio
    async def test_an_empty_name_is_refused(self, async_db, ctx):
        result = await create_project_handler({"name": "   "}, ctx)
        assert result["success"] is False


# ============================================================================
# create_task với project_ref — nghiệm thu 13.2
# ============================================================================


class TestCreateTaskWithProjectRef:
    @pytest.mark.asyncio
    async def test_two_projects_in_one_conversation_do_not_get_mixed_up(
        self, async_db, ctx
    ):
        """Tiêu chí nghiệm thu của Tuần 1, viết ra thành test.

        Điều làm nó đúng không phải handler mà là quyết định nền tảng ở 9.2:
        **không có "dự án hiện tại"**. Mỗi lời gọi tự mang tên dự án của nó,
        nên lượt thứ hai không thể thừa hưởng ngữ cảnh của lượt thứ nhất.
        """
        alpha = await _project(async_db, f"{PREFIX}Alpha")
        beta = await _project(async_db, f"{PREFIX}Beta")

        first = await create_task_handler(
            {"title": f"{PREFIX}việc Alpha", "project_ref": f"{PREFIX}Alpha"}, ctx
        )
        second = await create_task_handler(
            {"title": f"{PREFIX}việc Beta", "project_ref": f"{PREFIX}Beta"}, ctx
        )
        assert first["success"] and second["success"]

        rows = {
            t.title: t.project_id
            for t in (
                await async_db.scalars(select(Task).where(Task.user_id == TEST_USER_ID))
            ).all()
        }
        assert rows[f"{PREFIX}việc Alpha"] == alpha.id
        assert rows[f"{PREFIX}việc Beta"] == beta.id

    @pytest.mark.asyncio
    async def test_no_project_ref_means_no_opinion_not_no_project(
        self, async_db, ctx
    ):
        """Thiếu `project_ref` là *"người dùng không nói"*, và thang 3.5 xử
        lý trường hợp đó — task vẫn có project, là dự án cá nhân."""
        result = await create_task_handler({"title": f"{PREFIX}việc lẻ"}, ctx)
        assert result["success"] is True

        task = await async_db.scalar(
            select(Task).where(Task.title == f"{PREFIX}việc lẻ")
        )
        assert task.project_id is not None
        project = await async_db.get(Project, task.project_id)
        assert project.origin is ProjectOrigin.PERSONAL

    @pytest.mark.asyncio
    async def test_an_unresolvable_project_ref_creates_nothing_at_all(
        self, async_db, ctx
    ):
        """Tạo việc vào nhầm dự án rồi báo "đã tạo" là kiểu hỏng im lặng mà
        9.2 tồn tại để chặn. Dừng hẳn, không tạo task nào."""
        await _project(async_db, f"{PREFIX}Alpha")

        result = await create_task_handler(
            {"title": f"{PREFIX}không nên tồn tại", "project_ref": "Không có thật"}, ctx
        )

        assert result["success"] is False
        assert result["error"] == "project_not_found"
        assert (
            await async_db.scalar(
                select(Task).where(Task.title == f"{PREFIX}không nên tồn tại")
            )
        ) is None


# ============================================================================
# Quyền, audit và hoàn tác — phần một mutation không được thiếu
# ============================================================================
#
# Hai tool ghi (`move_task`, `create_project`) đi qua `CommandRegistry`, không
# gọi thẳng service. `ProjectService` đã kiểm quyền ở mức tài nguyên, nên gọi
# thẳng không mở lỗ hổng truy cập — nhưng nó bỏ mất bốn thứ mọi mutation khác
# trong hệ thống đều có: `permission_scope` khai báo được, audit trail,
# snapshot để hoàn tác, và event `command.{name}`.
#
# Với `move_task`, cái thứ ba là quan trọng nhất về mặt sản phẩm: nó là lối
# sửa của DESIGN 10.1 — thứ người dùng bấm *vì họ vừa thấy một cái sai* — và
# một thao tác sửa sai không hoàn tác được là thao tác người ta ngần ngại
# dùng. Tỷ lệ dùng nó chính là chỉ số ở 4.4.


class TestCommandLayerContract:
    @pytest.mark.asyncio
    async def test_both_mutating_commands_declare_write_permission(self):
        """Khai báo được ở registry, không phải chôn trong thân handler.

        Một `permission_scope` đọc được là thứ trả lời "lệnh này cần quyền
        gì" mà không phải đọc code — và là chỗ duy nhất câu trả lời đó
        không thể trôi khỏi thực tế.
        """
        from app.commands.registry import get_command_registry
        from app.commands.schemas import PermissionScope

        registry = get_command_registry()
        for name in ("project.create", "task.move_project"):
            handler = registry._handlers.get(name)
            assert handler is not None, f"{name} chưa đăng ký"
            assert handler.permission_scope is PermissionScope.WRITE
            assert handler.revertable is True
            assert handler.revert_handler is not None

    @pytest.mark.asyncio
    async def test_moving_a_task_can_be_undone(self, async_db, ctx):
        """Hoàn tác đưa việc về **đúng dự án cũ**, và xoá luôn nhãn 4.4.

        Không khôi phục nhãn thì một lượt chuyển rồi rút lại vẫn để lại một
        nhãn âm vĩnh viễn, và quy tắc suy ra bị tính là sai cho một thao tác
        người dùng đã hoàn tác.
        """
        from app.commands.registry import get_command_registry

        alpha = await _project(async_db, f"{PREFIX}Alpha")
        beta = await _project(async_db, f"{PREFIX}Beta")
        task = await _task(async_db, alpha, "nộp spec")

        moved = await move_task_handler(
            {"task_id": str(task.id), "project_ref": f"{PREFIX}Beta"}, ctx
        )
        assert moved["success"] is True
        assert moved["action_id"]
        await async_db.refresh(task)
        assert task.project_id == beta.id
        assert task.project_id_corrected is True

        reverted = await get_command_registry().revert_command(moved["action_id"], ctx)
        assert reverted.success is True, reverted.error

        await async_db.refresh(task)
        assert task.project_id == alpha.id
        assert task.project_id_corrected is False

    @pytest.mark.asyncio
    async def test_undoing_a_created_project_closes_it_instead_of_deleting(
        self, async_db, ctx
    ):
        """DESIGN 9.1 cố ý không có đường xoá dự án — xoá sẽ mồ côi lịch sử
        `attention_log`. Undo phải tôn trọng ràng buộc đó thay vì mở một cửa
        sau vòng qua nó: nếu không thì "xoá dự án" vẫn tồn tại, chỉ là được
        gọi bằng tên khác.
        """
        from app.commands.registry import get_command_registry

        created = await create_project_handler({"name": f"{PREFIX}Gamma"}, ctx)
        assert created["created"] is True
        project_id = UUID(created["project"]["id"])

        reverted = await get_command_registry().revert_command(created["action_id"], ctx)
        assert reverted.success is True, reverted.error

        project = await async_db.get(Project, project_id)
        assert project is not None, "hoàn tác không được xoá hàng"
        await async_db.refresh(project)
        assert project.status is ProjectStatus.CLOSED

    @pytest.mark.asyncio
    async def test_the_command_re_checks_ownership_and_does_not_trust_the_caller(
        self, async_db, ctx
    ):
        """Handler kiểm lại quyền dù tầng tool đã kiểm.

        "Tầng trên đã kiểm rồi" là một giả định hết đúng vào lúc xuất hiện
        đường vào thứ hai — và không ai nhớ quay lại đây khi điều đó xảy ra.
        """
        from app.commands.registry import get_command_registry
        from app.commands.schemas import Command

        alpha = await _project(async_db, f"{PREFIX}Alpha")

        # Một task không thuộc về người đang gọi: command phải từ chối, kể
        # cả khi nó được dựng thủ công quanh tầng tool.
        command = Command(
            command_name="task.move_project",
            args={"task_id": str(uuid4()), "project_id": str(alpha.id)},
            requested_by=TEST_USER_ID,
            source="AI",
        )
        result = await get_command_registry().execute(command, ctx)
        assert result.success is False
        assert "Task not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_a_project_the_user_is_not_in_is_refused_at_the_command_layer(
        self, async_db, ctx
    ):
        """Dự án của người khác không phải "không có quyền" mà là "không tồn
        tại" — cùng lối với API (404 thay vì 403): nói khác đi là xác nhận
        có một dự án id như vậy.
        """
        from app.commands.registry import get_command_registry
        from app.commands.schemas import Command

        alpha = await _project(async_db, f"{PREFIX}Alpha")
        alpha_id = alpha.id
        task = await _task(async_db, alpha, "việc")

        # Dự án của một tài khoản khác — TEST_USER_ID không phải thành viên,
        # nên không có hàng `project_members` nào nối hai bên.
        stranger_id = UUID("00000000-0000-4000-a000-000000000042")
        await async_db.execute(
            text(
                "INSERT INTO users (id, email, full_name, hashed_password, is_active, "
                "created_at, updated_at) VALUES (:id, :email, 'stranger', 'x', true, "
                "NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": stranger_id, "email": "pytest-9-2-stranger@cortex.invalid"},
        )
        stranger_project = Project(
            owner_id=stranger_id,
            name=f"{PREFIX}Của người khác",
            origin=ProjectOrigin.MANUAL,
        )
        async_db.add(stranger_project)
        await async_db.commit()
        # Giữ id ra biến trước khi chạy lệnh: lệnh thất bại rollback session
        # dùng chung, và đọc một thuộc tính đã expire sau đó sẽ kích hoạt
        # lazy-load ngoài greenlet — lỗi che mất chính thứ test đang đo.
        stranger_project_id = stranger_project.id
        task_id = task.id

        command = Command(
            command_name="task.move_project",
            args={"task_id": str(task_id), "project_id": str(stranger_project_id)},
            requested_by=TEST_USER_ID,
            source="AI",
        )
        result = await get_command_registry().execute(command, ctx)
        assert result.success is False
        assert "Project not found" in (result.error or "")

        # Đọc lại từ DB thay vì `refresh`: lệnh thất bại đã rollback session
        # dùng chung, nên thực thể trong bộ nhớ ở trạng thái không đáng tin.
        # Điều cần khẳng định là *hàng trong DB không đổi*, và câu này hỏi
        # đúng điều đó.
        stored_project_id = await async_db.scalar(
            select(Task.project_id).where(Task.id == task_id)
        )
        assert stored_project_id == alpha_id

        await async_db.execute(delete(Project).where(Project.id == stranger_project_id))
        await async_db.commit()
