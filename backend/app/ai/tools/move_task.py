"""`move_task` — chuyển một việc sang dự án khác (DESIGN 9.2).

Hai điều tool này cố ý **không** làm:

**Không đụng `related_event_id`.** Việc này sinh ra từ cuộc họp nào là một
sự thật lịch sử; nó không đổi vì việc được xếp lại. Gộp hai quan hệ sẽ làm
mất câu trả lời cho *"Cortex lấy việc này ở đâu ra"*.

**Không tự tạo dự án đích.** Nếu tên không khớp gì, tool trả về danh sách
và dừng. Agent tạo dự án `"Alpah"` vì người dùng gõ sai chính tả là kiểu
hỏng im lặng tệ nhất (P7).

Mỗi lượt gọi thành công ghi một nhãn cho 4.4 — xem `ProjectService.move_task`.

Đi qua `CommandRegistry` (`task.move_project`), không gọi thẳng service:
đây là một mutation, nên nó phải khai `permission_scope`, để lại audit
trail, và **hoàn tác được**. Cái cuối quan trọng nhất ở đây — tool này là
lối sửa của 10.1, tức là thứ người dùng bấm *vì họ vừa thấy một cái sai*,
và một thao tác sửa sai không hoàn tác được là thao tác người ta ngần ngại
dùng.
"""

from uuid import UUID

from pydantic import BaseModel

from app.ai.agents.tool_context import ToolContext
from app.ai.tools.project_ref import resolve_project_ref, unresolved_result
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MoveTaskInput(BaseModel):
    task_id: UUID
    project_ref: str


async def move_task_handler(args: dict, ctx: ToolContext) -> dict:
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    project_ref = args["project_ref"]

    # Giải tên **trước** khi dựng Command: giải có thể phải hỏi lại người
    # dùng, và một command không có chỗ cho một câu hỏi — nó thành công
    # hoặc thất bại.
    async with ctx.async_db() as db:
        resolution = await resolve_project_ref(db, ctx.user_id, project_ref)
    if not resolution.resolved:
        return unresolved_result(resolution, project_ref)

    try:
        task_id = UUID(str(args["task_id"]))
    except (ValueError, TypeError):
        return {"success": False, "error": "invalid_task_id"}

    command = Command(
        command_name="task.move_project",
        args={"task_id": str(task_id), "project_id": str(resolution.project.id)},
        requested_by=ctx.user_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )

    result = await get_command_registry().execute(command, ctx)
    if not result.success:
        # "Task not found" ở đây gần như luôn là agent dùng nhầm id, nên
        # câu trả lời phải chỉ đường lấy id đúng thay vì chỉ báo lỗi.
        return {
            "success": False,
            "error": "task_not_found",
            "detail": result.error,
            "next_step": (
                "Không chuyển được. Dùng get_project_tasks hoặc "
                "list_pending_tasks để lấy đúng task_id rồi thử lại."
            ),
        }

    data = {k: v for k, v in result.data.items() if k != "prev_state"}
    return {
        "task_id": data.get("id"),
        "title": data.get("title"),
        "moved": data.get("moved"),
        "project": {"id": str(resolution.project.id), "name": resolution.project.name},
        "action_id": result.action_id,
        "revert_hint": "Bạn có thể hoàn tác lần chuyển này bằng action_id trên.",
        "success": True,
    }


MOVE_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "The task's id."},
        "project_ref": {
            "type": "string",
            "description": "Destination project — its name as the user said it, or its id.",
        },
    },
    "required": ["task_id", "project_ref"],
}

MOVE_TASK_DEFINITION = {
    "name": "move_task",
    "handler": move_task_handler,
    "input_model": MoveTaskInput,
    "schema": MOVE_TASK_SCHEMA,
    "description": (
        "Move a task into a different project. Use when the user says a task "
        "belongs somewhere else. If the destination name doesn't match exactly "
        "one existing project, this returns the candidates — ask the user "
        "which they meant. Never create a project to make this call succeed."
    ),
}
