"""Procedure command handlers.

Đi qua CommandRegistry như mọi đường ghi khác của agent: kiểm quyền, xác
thực tham số, snapshot để hoàn tác, và audit log ở một chỗ. Một tool ghi
thẳng vào service sẽ bỏ qua cả bốn.
"""

import re
from uuid import UUID

from sqlalchemy import select

from app.ai.agents.tool_context import ToolContext
from app.commands.args import ProcedureStepMarkArgs
from app.commands.schemas import Command
from app.models import Procedure
from app.services.procedures import ProcedureService
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Bao nhiêu lượt nói gần nhất của người dùng được coi là "vừa nói".
#
# Đủ rộng để bắt được ca họ báo xong nhiều bước rải rác trong một cuộc trò
# chuyện, đủ hẹp để một câu "xong rồi" của tuần trước không biện minh cho
# một lần đánh dấu hôm nay.
QUOTE_LOOKBACK_MESSAGES = 5


def _normalise_quote(text: str) -> str:
    """Chuẩn hoá vừa đủ để so khớp: thường hoá, gộp khoảng trắng.

    Không bỏ dấu tiếng Việt và không bỏ dấu câu: mục đích là chặn *bịa
    đặt*, không phải chấp nhận diễn giải. Nới thêm ở đây sẽ làm phép kiểm
    mất đúng thứ nó tồn tại để giữ.
    """
    return re.sub(r"\s+", " ", (text or "").strip().lower())


async def _quote_is_real(db, conversation_id, quote: str, current_message: str | None) -> bool:
    """Người dùng có thật sự nói câu này trong vài lượt gần đây không?

    Đây là phép chặn chính của tính năng, và nó tồn tại vì một hành vi đo
    được (2026-09-10, thí nghiệm đối chứng):

        bước "Daily — trước 9h sáng", chạy lúc 21h  → model TỰ đánh dấu xong
        bước "Daily" (không kèm giờ)                → model không đánh dấu

    Nghĩa là model diễn giải *"đã quá giờ"* thành *"đã làm xong"*, rồi ghi
    vào DB rằng người dùng đã làm một việc họ chưa hề nhắc tới. Prompt đã
    nói "chỉ khi họ báo" và bị bỏ qua — nên phép kiểm phải nằm ở code.

    Cùng lối với `source_quote` của `app.services.task_extraction`: model
    trích dẫn, code đối chiếu. Một câu diễn giải lại sẽ trượt, và đó là ý
    định — model không thể trích dẫn một câu người dùng chưa nói.
    """
    from app.models import AgentMessage

    needle = _normalise_quote(quote)
    if not needle:
        return False

    # Lượt nói **của lượt này** đến qua `ctx.current_message`, không đọc từ
    # DB — và đây là nửa quan trọng hơn của phép kiểm, vì gần như mọi lần
    # đánh dấu hợp lệ đều dựa trên câu người dùng vừa gõ.
    #
    # `ConversationStore.save_message` chỉ `flush()`, không commit, nên tin
    # nhắn vừa lưu còn nằm trong transaction chưa xong của session agent;
    # tool chạy trên session riêng và không nhìn thấy nó. Bản đầu của hàm
    # này chỉ tra DB, nên nó từ chối **mọi** lời báo xong ngay tại lượt
    # người dùng nói ra — đo được: "daily xong rồi nhé" → `done = []`,
    # trong khi agent vẫn trả lời "mình đã ghi nhận".
    if current_message and needle in _normalise_quote(current_message):
        return True

    stmt = (
        select(AgentMessage.content)
        .where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role == "user",
            AgentMessage.content.isnot(None),
        )
        .order_by(AgentMessage.created_at.desc())
        .limit(QUOTE_LOOKBACK_MESSAGES)
    )
    recent = (await db.execute(stmt)).scalars().all()
    return any(needle in _normalise_quote(m) for m in recent)


async def procedure_mark_step_handler(command: Command, ctx: ToolContext) -> dict:
    """Đánh dấu một bước trong lần chạy đang mở của quy trình."""
    args = ProcedureStepMarkArgs(**command.args)

    async with ctx.async_db() as db:
        service = ProcedureService(db)

        procedure = await db.get(Procedure, args.procedure_id)
        # Không phải chủ sở hữu thì coi như không tồn tại — cùng lối "404,
        # không 403" của phần còn lại: nói "bạn không có quyền" đã là tiết
        # lộ rằng quy trình đó có thật.
        if procedure is None or procedure.user_id != ctx.user_id:
            return {"success": False, "error": "procedure_not_found"}

        # Trạng thái `pending` là hoàn tác một lần đánh dấu, không phải
        # khẳng định người dùng đã làm gì — không cần trích dẫn.
        if args.status != "pending":
            if ctx.conversation_id is None and not getattr(ctx, "current_message", None):
                # Không lượt nói hiện tại, không hội thoại — không còn gì để
                # đối chiếu. Từ chối, chứ không bỏ qua phép kiểm: đây là
                # đường ghi, và một phép kiểm tự tắt khi thiếu dữ liệu thì
                # không phải phép kiểm.
                return {
                    "success": False,
                    "error": "no_conversation_context",
                    "message": "Không xác thực được lời người dùng ngoài hội thoại.",
                }
            if not await _quote_is_real(
                db, ctx.conversation_id, args.user_said,
                getattr(ctx, "current_message", None),
            ):
                logger.warning(
                    "Từ chối mark_step: %r không có trong %d lượt nói gần nhất "
                    "(procedure=%s, bước %d)",
                    args.user_said[:60], QUOTE_LOOKBACK_MESSAGES,
                    procedure.id, args.step_order,
                )
                return {
                    "success": False,
                    "error": "quote_not_found",
                    "message": (
                        "Người dùng chưa nói câu đó. Chỉ đánh dấu một bước khi "
                        "họ thật sự báo đã làm — quá giờ không có nghĩa là đã "
                        "xong. Nếu chưa chắc, hãy hỏi họ."
                    ),
                }

        run = await service.get_active_run(procedure.id)
        if run is None:
            return {
                "success": False,
                "error": "no_active_run",
                "message": (
                    "Quy trình này chưa có lần chạy nào đang mở. Nó mở khi "
                    "người dùng nhắc tới hoàn cảnh của quy trình."
                ),
            }

        # Snapshot trước khi đổi, để `revert_action` lùi lại được đúng
        # trạng thái cũ của các bước.
        prev_states = [dict(s) for s in (run.step_states or [])]

        try:
            await service.mark_step(run, args.step_order, args.status)
        except ValueError as exc:
            return {"success": False, "error": "invalid_step", "message": str(exc)}

        await db.commit()

        pending = service.pending_steps(procedure, run)
        logger.info(
            "Procedure step %d → %s (procedure=%s, còn %d bước)",
            args.step_order, args.status, procedure.id, len(pending),
        )

        return {
            "success": True,
            "procedure_id": str(procedure.id),
            "procedure_title": procedure.title,
            "run_status": run.status.value,
            "pending_steps": pending,
            "prev_state": {
                "run_id": str(run.id),
                "step_states": prev_states,
            },
        }


async def revert_procedure_mark_step(snapshot: dict, ctx: ToolContext) -> dict:
    """Hoàn tác: đặt lại toàn bộ trạng thái bước về ảnh chụp trước đó.

    Đặt lại cả khối chứ không chỉ bước vừa đổi: đánh dấu bước cuối cùng có
    thể đã đóng luôn run, nên lùi một bước lẻ sẽ để lại một run `completed`
    còn bước dở dang.
    """
    from sqlalchemy.orm.attributes import flag_modified

    from app.models import ProcedureRun, ProcedureRunStatus

    before = snapshot.get("before_state") or snapshot
    run_id = before.get("run_id")
    if not run_id:
        return {"success": False, "error": "missing_run_id"}

    async with ctx.async_db() as db:
        run = await db.get(ProcedureRun, UUID(run_id))
        if run is None or run.user_id != ctx.user_id:
            return {"success": False, "error": "run_not_found"}

        run.step_states = before.get("step_states") or []
        flag_modified(run, "step_states")
        run.status = ProcedureRunStatus.ACTIVE
        run.completed_at = None
        await db.commit()

        return {"success": True, "run_id": str(run.id)}


def register_procedure_commands() -> None:
    """Register procedure commands with the global CommandRegistry."""
    from app.commands.registry import get_command_registry

    registry = get_command_registry()

    registry.register(
        name="procedure.mark_step",
        description="Đánh dấu một bước của quy trình là đã xong / bỏ qua / chưa làm",
        args_schema=ProcedureStepMarkArgs,
        handler=procedure_mark_step_handler,
        revertable=True,
        revert_handler=revert_procedure_mark_step,
    )
    logger.info("Procedure commands registered")
