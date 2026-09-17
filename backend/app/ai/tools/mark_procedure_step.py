"""Tick một bước của quy trình — vỏ mỏng quanh command `procedure.mark_step`.

Đây là nửa còn lại của tính năng quy trình. Ngữ cảnh nói cho agent biết
người dùng *còn* bước nào; tool này là cách bước đó chuyển sang đã xong khi
họ báo. Thiếu nó, tiến độ đóng băng ở lúc mở run và lần nhắc sau lại đọc
nguyên danh sách từ đầu.
"""

from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MarkProcedureStepInput(BaseModel):
    procedure_id: str = Field(..., description="UUID của quy trình")
    step_order: int = Field(..., ge=1, description="Số thứ tự bước, bắt đầu từ 1")
    status: str = Field(default="done", description="done | skipped | pending")
    user_said: str = Field(
        ...,
        description="Câu của người dùng chứng minh điều đó, copy nguyên văn",
    )


async def mark_procedure_step_handler(args: dict, ctx: ToolContext) -> dict:
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    command = Command(
        command_name="procedure.mark_step",
        args={
            "procedure_id": args["procedure_id"],
            "step_order": args["step_order"],
            "status": args.get("status", "done"),
            "user_said": args.get("user_said", ""),
        },
        requested_by=ctx.user_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )

    result = await get_command_registry().execute(command, ctx)
    if not result.success:
        raise ValueError(result.error)

    data = {k: v for k, v in result.data.items() if k != "prev_state"}
    return {**data, "action_id": result.action_id, "success": True}


MARK_PROCEDURE_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "procedure_id": {
            "type": "string",
            "description": "UUID của quy trình — lấy từ khối quy trình trong ngữ cảnh",
        },
        "step_order": {
            "type": "integer",
            "description": "Số thứ tự bước như hiển thị trong ngữ cảnh (bắt đầu từ 1)",
        },
        "status": {
            "type": "string",
            "enum": ["done", "skipped", "pending"],
            "description": "done khi họ đã làm, skipped khi họ cố ý bỏ qua",
            "default": "done",
        },
        "user_said": {
            "type": "string",
            "description": (
                "Câu của NGƯỜI DÙNG chứng minh điều này, copy nguyên văn từ "
                "tin nhắn của họ — ví dụ 'daily xong rồi nhé'. Được đối "
                "chiếu lại với những gì họ thật sự đã nói."
            ),
        },
    },
    "required": ["procedure_id", "step_order", "user_said"],
}

MARK_PROCEDURE_STEP_DEFINITION = {
    "name": "mark_procedure_step",
    "handler": mark_procedure_step_handler,
    "input_model": MarkProcedureStepInput,
    "schema": MARK_PROCEDURE_STEP_SCHEMA,
    "description": (
        "Đánh dấu một bước của quy trình đang chạy là đã xong (hoặc bỏ qua).\n\n"
        "**Chỉ gọi được khi ngữ cảnh của bạn có khối \"Quy trình khớp hoàn "
        "cảnh vừa nêu\" kèm một procedure_id.** Không có khối đó thì không có "
        "quy trình nào đang chạy: hãy trả lời bình thường và TUYỆT ĐỐI KHÔNG "
        "hỏi người dùng procedure_id, UUID, hay bất cứ id nào — đó là chuyện "
        "nội bộ, người dùng không biết và không cần biết. Nếu họ báo vừa làm "
        "xong một việc không có trong khối nào, coi đó là một việc bình "
        "thường.\n\n"
        "Gọi khi người dùng BÁO họ vừa làm xong một bước có trong khối "
        '"Quy trình khớp hoàn cảnh vừa nêu" của ngữ cảnh — "daily xong rồi", '
        '"đã check-in", "gửi báo cáo rồi".\n\n'
        "**Quá giờ KHÔNG có nghĩa là đã xong.** Một bước ghi \"trước 9h "
        "sáng\" mà bây giờ đã 10h thì nó đang TRỄ và vẫn chưa làm — không "
        "phải đã hoàn thành. Nói cho người dùng biết nó trễ, hoặc hỏi họ đã "
        "làm chưa; đừng tự đánh dấu.\n\n"
        "`user_said` là bắt buộc và phải là câu của chính người dùng, copy "
        "nguyên văn. Nó được đối chiếu với những gì họ thật sự đã nói, nên "
        "một câu bạn tự diễn giải sẽ bị từ chối. Nếu không trích được câu "
        "nào, nghĩa là họ chưa báo — hãy hỏi thay vì đánh dấu.\n\n"
        "Dùng `skipped` khi họ cố ý bỏ một bước ('hôm nay khỏi sync'), để lần "
        "sau không hỏi lại bước đó nữa.\n\n"
        "Chỉ gọi cho bước thật sự có trong khối quy trình đang hiển thị. Nếu "
        "việc người dùng nhắc tới không nằm trong đó, đấy là một task bình "
        "thường — dùng create_task."
    ),
}
