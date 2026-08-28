"""`create_project` — tạo tay, **hạn chế** (DESIGN 9.2).

> *Chỉ khi người dùng nói thẳng tên và ý định. **Không bao giờ tạo từ suy
> luận.***

Đây là tool nguy hiểm nhất trong bốn tool mới, vì nó là tool duy nhất tạo
ra một thực thể mới từ một câu nói. Cửa chính để một dự án ra đời là 4.1 —
một channel Mezon có việc thì tự thành dự án, không ai bấm gì. Tool này là
lối phụ cho trường hợp người dùng biết chính xác họ muốn gì.

Vì sao phải hạn chế bằng cả mô tả lẫn code: người dùng nói *"tôi cần làm
xong cái landing page"* thì agent rất dễ hiểu thành "tạo dự án Landing
Page". Kết quả là một bảng dự án đầy những thứ không ai coi là dự án — đúng
cách `goals` đã chết (P4), chỉ nhanh hơn.

Đi qua `CommandRegistry` (`project.create`) như mọi mutation khác: khai
`permission_scope`, để lại audit trail, và hoàn tác được. Hoàn tác ở đây là
**đóng** dự án chứ không xoá — DESIGN 9.1 cố ý không có đường xoá, và undo
không được mở một cửa sau vòng qua ràng buộc đó.
"""

from pydantic import BaseModel

from app.ai.agents.tool_context import ToolContext
from app.ai.tools.project_ref import brief, resolve_project_ref
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CreateProjectInput(BaseModel):
    name: str


async def create_project_handler(args: dict, ctx: ToolContext) -> dict:
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    name = (args.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "empty_name"}

    async with ctx.async_db() as db:
        # Trùng tên thì trả về cái đã có thay vì tạo bản thứ hai. Hai dự án
        # cùng tên là trạng thái không sửa được từ phía người dùng: mọi
        # `project_ref` về sau đều nhập nhằng, mãi mãi.
        existing = await resolve_project_ref(db, ctx.user_id, name)
        if existing.resolved:
            return {
                "project": brief(existing.project),
                "created": False,
                "success": True,
                "note": "Dự án tên này đã có — dùng lại, không tạo thêm bản thứ hai.",
            }

    command = Command(
        command_name="project.create",
        args={"name": name},
        requested_by=ctx.user_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )
    result = await get_command_registry().execute(command, ctx)
    if not result.success:
        return {"success": False, "error": "create_failed", "detail": result.error}

    logger.info("agent created project", extra={"project_id": result.data.get("id")})
    return {
        "project": {
            "id": result.data.get("id"),
            "name": result.data.get("name"),
            "deadline": None,
        },
        "created": True,
        "action_id": result.action_id,
        "revert_hint": "Bạn có thể hoàn tác (đóng dự án vừa tạo) bằng action_id trên.",
        "success": True,
    }


CREATE_PROJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "The project name, exactly as the user said it.",
        }
    },
    "required": ["name"],
}

CREATE_PROJECT_DEFINITION = {
    "name": "create_project",
    "handler": create_project_handler,
    "input_model": CreateProjectInput,
    "schema": CREATE_PROJECT_SCHEMA,
    "description": (
        "Create a new project. Use ONLY when the user explicitly asks for a "
        "new project and names it — e.g. 'tạo dự án Alpha'. Never call this "
        "because a project_ref didn't match, never to make another tool call "
        "succeed, and never because the user described work that sounds like "
        "a project. Most projects are created automatically from the Mezon "
        "channel their work arrives in; this is the exception, not the rule."
    ),
}
