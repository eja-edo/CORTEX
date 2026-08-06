"""Revert Action Tool — cho phép agent hoàn tác mutating action gần nhất.

LLM sẽ gọi tool này khi user nói:
- "undo", "hoàn tác", "bỏ đi", "xóa cái vừa tạo", etc.
- "revert action_id abc123"
- "undo the last note I created"
"""

from typing import Optional
from pydantic import BaseModel, Field

from app.ai.agents.action_snapshot_store import get_snapshot_store
from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RevertActionInput(BaseModel):
    action_id: Optional[str] = Field(
        None,
        description="action_id từ kết quả của tool trước. Nếu không cung cấp, sẽ revert action gần nhất."
    )


async def revert_action_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Hoàn tác một action đã thực hiện bởi agent — delegate toàn bộ logic cho
    CommandRegistry.revert_command() (permission/idempotent-guard/actual
    revert/mark-reverted đều nằm trong đó, xem app/commands/registry.py).

    ⚠️ 2026-08-06: Trước khi có Milestone 1.6, hàm này tự tra snapshot +
    dispatch theo `snapshot.snapshot["op"]` (create_note/update_note/
    create_schedule/update_schedule) bằng các hàm `_revert_*` thủ công.
    Snapshot của các command mới (note.create, schedule.create, ...) dùng
    `snapshot.tool_name` để dispatch qua CommandRegistry — snapshot cũ tạo
    trước migration (TTL 24h) sẽ không revert được qua đường mới; tự hết
    hạn trong vòng 24h nên không cần logic tương thích ngược cho cửa sổ này.
    """
    from app.commands.registry import get_command_registry

    store = get_snapshot_store()
    user_id_str = str(ctx.user_id)
    action_id = args.get("action_id")

    if not action_id:
        recent = await store.list_recent(user_id_str, limit=1)
        if not recent:
            return {
                "success": False,
                "error": "Không tìm thấy action nào có thể hoàn tác. Các action chỉ có thể hoàn tác trong vòng 24h.",
            }
        action_id = recent[0].action_id

    result = await get_command_registry().revert_command(action_id, ctx)

    if not result.success:
        return {"success": False, "error": result.error, "action_id": action_id}

    return {
        "success": True,
        "action_id": action_id,
        "message": f"Đã hoàn tác thành công (action_id={action_id}).",
        "detail": result.data,
    }


REVERT_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action_id": {
            "type": "string",
            "description": (
                "action_id từ kết quả của một tool trước (create_note, update_note, "
                "create_schedule, update_schedule). Nếu bỏ trống, sẽ hoàn tác action gần nhất."
            ),
        },
    },
}

REVERT_ACTION_DEFINITION = {
    "name": "revert_action",
    "handler": revert_action_handler,
    "input_model": RevertActionInput,
    "schema": REVERT_ACTION_SCHEMA,
    "description": (
        "Hoàn tác (undo) một action đã thực hiện: tạo note, sửa note, tạo lịch, sửa lịch. "
        "Cung cấp action_id từ kết quả tool trước, hoặc để trống để undo action gần nhất. "
        "Chỉ có thể hoàn tác trong vòng 24 giờ. Mỗi action chỉ có thể hoàn tác một lần."
    ),
}
