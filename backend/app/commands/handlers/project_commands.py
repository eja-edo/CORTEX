"""Project commands — mọi mutation cấp dự án đi qua `CommandRegistry`.

**Vì sao không gọi thẳng service.** `ProjectService` đã kiểm quyền ở mức
tài nguyên (thành viên qua `project_members`, task qua `user_id`), nên gọi
thẳng *không* mở lỗ hổng truy cập. Nhưng nó bỏ mất bốn thứ khác mà mọi
mutation khác trong hệ thống đều có:

  1. **`permission_scope` khai báo được** — một dòng đọc được ở registry
     trả lời "lệnh này cần quyền gì", thay vì phải đọc thân handler.
  2. **Audit trail** — `action_history` ghi ai làm gì lúc nào.
  3. **Undo** — `revert_action` cần một snapshot, và snapshot chỉ sinh ra ở
     đường này.
  4. **Event `command.{name}`** — thứ các subscriber khác nghe.

Thiếu (3) là nặng nhất về mặt sản phẩm: `move_task` là lối sửa của DESIGN
10.1, tức là thao tác người dùng thực hiện *vì họ vừa phát hiện một cái
sai*. Một thao tác sửa sai mà không hoàn tác được là thao tác người ta ngần
ngại dùng — và tỷ lệ dùng nó chính là chỉ số ở 4.4.

Đọc (`list_projects`, `get_project_tasks`) vẫn đi thẳng service, cùng lý do
`list_pending_tasks` làm vậy: không có mutation nào để kiểm quyền, ghi
audit hay hoàn tác.
"""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.ai.agents.action_snapshot_store import ActionSnapshot
from app.ai.agents.tool_context import ToolContext
from app.commands.schemas import Command, PermissionScope
from app.models import Project, ProjectStatus, Task
from app.services.projects import ProjectService
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------


class ProjectCreateArgs(BaseModel):
    """No `workspace_id`: dự án là thực thể riêng, không nằm trong workspace
    (DESIGN 3.6). Nên lệnh này đi nhánh ownership của `_check_permission`."""

    name: str = Field(..., min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Project name cannot be empty")
        return v.strip()


class TaskMoveProjectArgs(BaseModel):
    """`project_id`, không phải `project_ref`.

    Giải tên xảy ra ở tầng tool và có thể phải *hỏi lại người dùng*
    (`ask_user_choice`). Một command không có chỗ cho một câu hỏi — nó
    thành công hoặc thất bại — nên nó chỉ nhận thứ đã giải xong.
    """

    task_id: UUID
    project_id: UUID


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def project_create_handler(command: Command, ctx: ToolContext) -> dict:
    args = ProjectCreateArgs(**command.args)

    async with ctx.async_db() as db:
        service = ProjectService(db)
        project = await service.create_manual(ctx.user_id, args.name)
        await db.commit()
        await db.refresh(project)

        logger.info(f"Project created: {project.id}")
        return {
            "id": str(project.id),
            "name": project.name,
            "status": project.status.value,
            "origin": project.origin.value,
            "prev_state": {"project_id": str(project.id)},
        }


async def project_create_revert_handler(snapshot: ActionSnapshot, ctx: ToolContext) -> None:
    """Hoàn tác một lần tạo dự án = **đóng nó**, không xoá.

    DESIGN 9.1 cố ý không có đường xoá dự án: xoá sẽ mồ côi lịch sử
    `attention_log`, vốn vẫn đúng sau khi thứ được nhắc biến mất. Undo phải
    tôn trọng ràng buộc đó thay vì mở một cửa sau vòng qua nó — nếu không
    thì "xoá dự án" tồn tại, chỉ là phải gọi nó bằng tên khác.
    """
    # `snapshot.snapshot` **là** `prev_state`: `CommandRegistry._create_snapshot`
    # đã bóc lớp đó ra rồi (`snapshot=result_data.get("prev_state", {})`).
    # Đọc thêm một tầng nữa thì mọi lần hoàn tác đều báo "snapshot incomplete",
    # và nó chỉ lộ ra khi có người thật bấm undo.
    prev_state = snapshot.snapshot or {}
    project_id = prev_state.get("project_id")
    if not project_id:
        raise ValueError("Cannot revert project.create: snapshot missing project_id")

    async with ctx.async_db() as db:
        project = await db.get(Project, UUID(project_id))
        if project is None or project.owner_id != ctx.user_id:
            # Đã biến mất hoặc không phải của người này — không có gì để
            # hoàn tác, và cố sửa hàng của người khác thì tệ hơn nhiều.
            return
        project.status = ProjectStatus.CLOSED
        await db.commit()


async def task_move_project_handler(command: Command, ctx: ToolContext) -> dict:
    args = TaskMoveProjectArgs(**command.args)

    async with ctx.async_db() as db:
        service = ProjectService(db)

        # Quyền ở mức tài nguyên, kiểm ở đây chứ không tin tầng gọi:
        # command có thể tới từ một đường vào khác trong tương lai, và
        # "tầng trên đã kiểm rồi" là giả định hết đúng lúc nào không ai biết.
        task = await db.get(Task, args.task_id)
        if task is None or task.user_id != ctx.user_id:
            raise ValueError("Task not found")

        if await service.get_for_user(args.project_id, ctx.user_id) is None:
            raise ValueError("Project not found")

        previous_project_id = str(task.project_id)
        was_corrected = bool(task.project_id_corrected)

        await service.move_task(task, args.project_id, ctx.user_id)
        await db.commit()
        await db.refresh(task)

        return {
            "id": str(task.id),
            "title": task.title,
            "project_id": str(task.project_id),
            "moved": previous_project_id != str(task.project_id),
            "prev_state": {
                "task_id": str(task.id),
                "project_id": previous_project_id,
                # Khôi phục cả nhãn 4.4: nếu không, một lượt chuyển rồi
                # hoàn tác vẫn để lại một nhãn âm vĩnh viễn, và quy tắc suy
                # ra bị tính là sai cho một thao tác người dùng đã rút lại.
                "project_id_corrected": was_corrected,
            },
        }


async def task_move_project_revert_handler(snapshot: ActionSnapshot, ctx: ToolContext) -> None:
    prev_state = snapshot.snapshot or {}
    task_id = prev_state.get("task_id")
    project_id = prev_state.get("project_id")
    if not task_id or not project_id:
        raise ValueError("Cannot revert task.move_project: snapshot incomplete")

    async with ctx.async_db() as db:
        task = await db.get(Task, UUID(task_id))
        if task is None or task.user_id != ctx.user_id:
            return
        task.project_id = UUID(project_id)
        task.project_id_corrected = bool(prev_state.get("project_id_corrected"))
        await db.commit()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_project_commands() -> None:
    from app.commands.registry import get_command_registry

    registry = get_command_registry()

    registry.register(
        name="project.create",
        description="Create a project (a shared unit of work with its own deadline and members)",
        args_schema=ProjectCreateArgs,
        handler=project_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=project_create_revert_handler,
    )

    registry.register(
        name="task.move_project",
        description="Move a task into a different project (never changes where the task came from)",
        args_schema=TaskMoveProjectArgs,
        handler=task_move_project_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True,
        revert_handler=task_move_project_revert_handler,
    )
