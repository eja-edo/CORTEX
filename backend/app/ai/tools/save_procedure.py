"""Save procedure tool — thin wrapper around the procedure.create command.

Đường ghi trực tiếp cho quy trình lặp lại, sống trong lúc chat — thay cho
đường cũ (chỉ tạo được gián tiếp, sau khi batch trích xuất bộ nhớ phân loại
đúng category `routine` rồi mới cấu trúc hoá, qua `procedure_extraction.py`
đã xoá). Model gọi tool này ngay khi nhận ra một chuỗi công việc, còn
nguyên ngữ cảnh gốc của lượt hội thoại thay vì một bản tóm tắt đã nén qua
một lớp trung gian.
"""

from typing import Optional
from pydantic import BaseModel, Field, model_validator

from app.ai.agents.tool_context import ToolContext
from app.ai.tools.title_fallback import rescue_title
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ProcedureStepInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Tên ngắn của bước")
    due_hint: Optional[str] = Field(None, max_length=100, description="Mốc thời gian, nếu có (ví dụ 'trước 9h sáng')")
    detail: Optional[str] = Field(
        None, max_length=500,
        description=(
            "Mô tả cụ thể hơn tiêu đề — loại hành động, đối tượng liên quan "
            "(note/task/schedule), điều kiện áp dụng. Vẫn là mô tả để bạn tự "
            "diễn giải lại mỗi lần, không phải lệnh cố định."
        ),
    )

    # Đo được (tests/eval/test_save_procedure_live.py, 2026-09-22): model bỏ
    # trống `title` và chỉ điền `detail`, ở 100% số lần gọi trong lần eval
    # sống đầu tiên — cùng kiểu hỏng `title_fallback.py` đã ghi cho
    # `create_schedule`/`create_task`. Cứu bằng cách mượn `detail` làm
    # `title` khi trống, xem docstring `rescue_title`.
    @model_validator(mode="before")
    @classmethod
    def _rescue_title(cls, data):
        return rescue_title(data, fallback_field="detail")


class SaveProcedureInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    trigger_text: str = Field(
        ..., min_length=1, max_length=500,
        description=(
            "BẮT BUỘC liệt kê ÍT NHẤT 3 cách khác nhau người dùng có thể "
            "nhắc lại hoàn cảnh này SAU NÀY, cách nhau bởi dấu phẩy — không "
            "chỉ chép lại đúng câu họ vừa nói. Tự nghĩ thêm từ đồng nghĩa, "
            "cách nói tắt, cách diễn đạt khác. Ví dụ người dùng nói 'khi tôi "
            "remote' → viết 'remote, làm việc từ xa, wfh, làm việc ở nhà', "
            "không phải chỉ 'khi tôi remote'. Không kèm các bước."
        ),
    )
    steps: list[ProcedureStepInput] = Field(..., min_length=1)

    # Cùng kiểu hỏng như `ProcedureStepInput` ở trên, đo cùng lúc: model
    # cũng bỏ trống `title` của cả quy trình. Không có `description` để
    # mượn ở đây — mượn cách nói ĐẦU TIÊN của `trigger_text` làm tên ngắn,
    # và **không** xoá `trigger_text` (khác `detail`/`description`, nó vẫn
    # là trường bắt buộc riêng, không phải phần mở rộng của `title`).
    @model_validator(mode="before")
    @classmethod
    def _rescue_procedure_title(cls, data):
        if not isinstance(data, dict):
            return data
        title = data.get("title")
        title = title.strip() if isinstance(title, str) else title
        if title:
            return data
        trigger_text = data.get("trigger_text")
        if isinstance(trigger_text, str) and trigger_text.strip():
            data = dict(data)
            first_phrase = trigger_text.split(",")[0].strip()
            data["title"] = (first_phrase or trigger_text.strip())[:255]
        return data


async def save_procedure_handler(args: dict, ctx: ToolContext) -> dict:
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command

    command = Command(
        command_name="procedure.create",
        args={
            "title": args["title"],
            "trigger_text": args["trigger_text"],
            "steps": args["steps"],
        },
        requested_by=ctx.user_id,
        conversation_id=ctx.conversation_id,
        source="AI",
    )

    result = await get_command_registry().execute(command, ctx)

    if not result.success:
        raise ValueError(result.error)

    data = {k: v for k, v in result.data.items() if k != "prev_state"}  # internal-only, not for the LLM
    return {
        **data,
        "action_id": result.action_id,
        "success": True,
    }


SAVE_PROCEDURE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Tên ngắn gọn cho quy trình"},
        "trigger_text": {
            "type": "string",
            "description": (
                "BẮT BUỘC liệt kê ÍT NHẤT 3 cách khác nhau người dùng có thể "
                "nhắc lại hoàn cảnh này SAU NÀY, cách nhau bởi dấu phẩy — "
                "không chỉ chép lại đúng câu họ vừa nói. Tự nghĩ thêm từ "
                "đồng nghĩa, cách nói tắt, cách diễn đạt khác. Ví dụ người "
                "dùng nói 'khi tôi remote' → viết 'remote, làm việc từ xa, "
                "wfh, làm việc ở nhà', không phải chỉ 'khi tôi remote'. "
                "Không kèm các bước."
            ),
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Tên ngắn của bước"},
                    "due_hint": {"type": "string", "description": "Mốc thời gian, nếu có"},
                    "detail": {
                        "type": "string",
                        "description": "Mô tả cụ thể hơn — loại hành động, đối tượng liên quan (note/task/schedule), điều kiện áp dụng",
                    },
                },
                "required": ["title"],
            },
        },
    },
    "required": ["title", "trigger_text", "steps"],
}

SAVE_PROCEDURE_DEFINITION = {
    "name": "save_procedure",
    "handler": save_procedure_handler,
    "input_model": SaveProcedureInput,
    "schema": SAVE_PROCEDURE_SCHEMA,
    "description": (
        "Lưu lại một quy trình lặp lại người dùng vừa mô tả — một hoàn cảnh "
        "sẽ lặp lại, kèm những gì họ luôn làm khi nó xảy ra. Nhận ra nó ở "
        "MỌI cách diễn đạt, không chỉ câu dạng 'khi X thì Y' — 'mỗi lần...', "
        "'cứ...là...', 'từ giờ mỗi khi...', một chỉ thị đứng ('từ giờ lần "
        "nào cũng làm vậy nhé'), hay chỉ kể lại việc gì luôn xảy ra tiếp "
        "theo mà không có từ nối nào cả đều tính. Gọi NGAY khi phát hiện "
        "trong lượt hiện tại, không đợi tới cuối hội thoại và không cần hỏi "
        "xác nhận trước khi gọi. Nhưng PHẢI báo lại một câu ngắn sau khi lưu "
        "— đừng im lặng. Nếu trùng một quy trình đã lưu trước đó (cùng hoàn "
        "cảnh), lần gọi này CẬP NHẬT thay vì tạo bản sao."
    ),
}
