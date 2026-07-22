"""Revert Action Tool — cho phép agent hoàn tác mutating action gần nhất.

LLM sẽ gọi tool này khi user nói:
- "undo", "hoàn tác", "bỏ đi", "xóa cái vừa tạo", etc.
- "revert action_id abc123"
- "undo the last note I created"
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timezone
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
    Hoàn tác một action đã thực hiện bởi agent.

    Logic:
    1. Lấy snapshot từ Redis (theo action_id hoặc action mới nhất của user)
    2. Validate ownership (user_id phải khớp)
    3. Validate chưa revert (idempotent guard)
    4. Thực thi revert tương ứng với op type
    5. Đánh dấu đã revert trong Redis
    """
    store = get_snapshot_store()
    user_id_str = str(ctx.user_id)
    action_id = args.get("action_id")

    # --- Tìm snapshot ---
    if action_id:
        snapshot = await store.get(user_id_str, action_id)
        if snapshot is None:
            return {
                "success": False,
                "error": f"Không tìm thấy action_id '{action_id}'. Có thể đã hết hạn (24h) hoặc action_id không đúng.",
            }
    else:
        recent = await store.list_recent(user_id_str, limit=1)
        if not recent:
            return {
                "success": False,
                "error": "Không tìm thấy action nào có thể hoàn tác. Các action chỉ có thể hoàn tác trong vòng 24h.",
            }
        snapshot = recent[0]

    # --- Validate ownership ---
    if snapshot.user_id != user_id_str:
        logger.warning(f"Revert ownership mismatch: snapshot.user_id={snapshot.user_id} ctx.user_id={user_id_str}")
        return {
            "success": False,
            "error": "Permission denied: action này không thuộc về bạn.",
        }

    # --- Idempotent guard ---
    if snapshot.reverted_at is not None:
        return {
            "success": False,
            "error": f"Action này đã được hoàn tác vào lúc {datetime.fromtimestamp(snapshot.reverted_at, tz=timezone.utc).isoformat()}.",
            "already_reverted": True,
        }

    # --- Thực thi revert ---
    op = snapshot.snapshot.get("op")
    try:
        if op == "create_note":
            result = await _revert_create_note(snapshot.snapshot, ctx)
        elif op == "update_note":
            result = await _revert_update_note(snapshot.snapshot, ctx)
        elif op == "create_schedule":
            result = await _revert_create_schedule(snapshot.snapshot, ctx)
        elif op == "update_schedule":
            result = await _revert_update_schedule(snapshot.snapshot, ctx)
        else:
            return {
                "success": False,
                "error": f"Không hỗ trợ revert cho op='{op}'.",
            }
    except Exception as exc:
        logger.error(f"Revert failed for op={op} action_id={snapshot.action_id}: {exc}", exc_info=True)
        return {
            "success": False,
            "error": f"Hoàn tác thất bại: {str(exc)}",
        }

    # --- Đánh dấu đã revert ---
    await store.mark_reverted(user_id_str, snapshot.action_id)

    return {
        "success": True,
        "action_id": snapshot.action_id,
        "tool_name": snapshot.tool_name,
        "op": op,
        "detail": result,
        "message": result.get("message", f"Đã hoàn tác thành công: {op}"),
    }


# ── Revert implementations ──────────────────────────────────────────────────

async def _revert_create_note(snap: dict, ctx: ToolContext) -> dict:
    """Soft-delete note vừa tạo."""
    from uuid import UUID
    from sqlalchemy import select
    from app.models import Note

    note_id = UUID(snap["note_id"])

    async with ctx.async_db() as db:
        stmt = select(Note).where(
            Note.id == note_id,
            Note.user_id == ctx.user_id,
        )
        result = await db.execute(stmt)
        note = result.scalar_one_or_none()

        if not note:
            raise ValueError(f"Note {note_id} không tồn tại hoặc đã bị xóa.")

        if note.is_deleted:
            return {"message": f"Note {note_id} đã bị xóa từ trước.", "note_id": str(note_id)}

        note.is_deleted = True
        await db.flush()

    return {
        "message": f"Đã xóa note '{str(note_id)[:8]}...' (soft delete).",
        "note_id": str(note_id),
    }


async def _revert_update_note(snap: dict, ctx: ToolContext) -> dict:
    """Khôi phục note về nội dung trước khi update."""
    from uuid import UUID
    from app.schemas import NotePatchRequest
    from app.services.notes import NoteService
    from app.utils.note_delta import build_text_patch

    note_id = UUID(snap["note_id"])
    prev_content = snap["prev_content"]

    async with ctx.async_db() as db:
        service = NoteService(db)
        current = await service.get_note(note_id=note_id, user_id=ctx.user_id)
        if current is None:
            raise ValueError(f"Note {note_id} không tồn tại.")

        current_content = await service.materialize_note_content(current)
        if current_content == prev_content:
            return {"message": "Nội dung note đã giống với trạng thái trước, không cần hoàn tác.", "note_id": str(note_id)}

        patch = build_text_patch(current_content, prev_content)
        if not patch:
            raise ValueError("Không thể tạo patch để hoàn tác.")

        payload = NotePatchRequest(version=current.version, patch=patch)
        updated = await service.patch_note(note_id=note_id, user_id=ctx.user_id, payload=payload)
        if updated is None:
            raise ValueError("Version conflict khi hoàn tác. Vui lòng thử lại.")

    return {
        "message": f"Đã khôi phục note về phiên bản trước.",
        "note_id": str(note_id),
        "new_version": updated.version,
    }


async def _revert_create_schedule(snap: dict, ctx: ToolContext) -> dict:
    """Xóa schedule vừa tạo."""
    from uuid import UUID
    from app.database import SessionLocal
    from app.services.schedule_service import ScheduleService

    schedule_id = UUID(snap["schedule_id"])

    db = SessionLocal()
    try:
        svc = ScheduleService(db)
        deleted = svc.delete_schedule(schedule_id=schedule_id, user_id=ctx.user_id)
        if not deleted:
            raise ValueError(f"Schedule {schedule_id} không tồn tại hoặc bạn không có quyền xóa.")
    finally:
        db.close()

    return {
        "message": (
            f"Đã xóa schedule '{snap['schedule_id'][:8]}...'.\n"
            "⚠️ Lưu ý: Sự kiện có thể vẫn còn trên Google Calendar — vui lòng xóa thủ công nếu cần."
        ),
        "schedule_id": str(schedule_id),
    }


async def _revert_update_schedule(snap: dict, ctx: ToolContext) -> dict:
    """Khôi phục schedule về trạng thái trước khi update."""
    from uuid import UUID
    from datetime import datetime
    from app.database import SessionLocal
    from app.services.schedule_service import ScheduleService

    schedule_id = UUID(snap["schedule_id"])
    prev = snap["prev_fields"]

    start_time = datetime.fromisoformat(prev["start_time"]) if prev.get("start_time") else None
    end_time = datetime.fromisoformat(prev["end_time"]) if prev.get("end_time") else None

    db = SessionLocal()
    try:
        svc = ScheduleService(db)
        schedule = svc.update_schedule_fields(
            schedule_id=schedule_id,
            user_id=ctx.user_id,
            title=prev.get("title"),
            start_time=start_time,
            end_time=end_time,
            description=prev.get("description"),
            is_completed=prev.get("is_completed"),
        )
    finally:
        db.close()

    return {
        "message": f"Đã khôi phục lịch về trạng thái trước.",
        "schedule_id": str(schedule_id),
        "restored_title": schedule.title,
    }


# ── Tool definition ──────────────────────────────────────────────────────────

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
