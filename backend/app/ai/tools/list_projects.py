"""`list_projects` — cửa vào của agent với dự án (DESIGN 9.2).

Read-only, nên đi thẳng service chứ không qua `CommandRegistry`: không có
mutation nào để kiểm quyền, ghi audit hay hoàn tác.

**Bắt buộc có giới hạn số dòng.** Trả 50 dự án kèm task là thổi bay context
(9.2) — và tệ hơn giới hạn context, một danh sách dài làm model chọn tệ hơn
chứ không tốt hơn.
"""

from typing import Optional

from pydantic import BaseModel

from app.ai.agents.tool_context import ToolContext
from app.ai.tools.project_ref import MAX_LISTED_PROJECTS
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ListProjectsInput(BaseModel):
    status: Optional[str] = None
    include_personal: bool = False


async def list_projects_handler(args: dict, ctx: ToolContext) -> dict:
    from app.models import ProjectStatus
    from app.services.projects import ProjectService

    raw_status = (args.get("status") or "active").lower()
    status = None if raw_status == "all" else ProjectStatus(raw_status)
    include_personal = bool(args.get("include_personal"))

    async with ctx.async_db() as db:
        rows = await ProjectService(db).list_for_user(ctx.user_id, status=status)
        if not include_personal:
            # Ẩn mặc định (9.2): dự án cá nhân là nơi mọi việc lẻ rơi vào,
            # nên nó có mặt ở mọi lần liệt kê và chiếm chỗ trong ngữ cảnh
            # của mỗi lượt mà hiếm khi là thứ người dùng đang nói tới.
            rows = [(p, m) for p, m in rows if p.origin.value != "personal"]

        rows.sort(key=lambda pair: (-pair[1]["risk"], pair[0].name.lower()))
        shown = rows[:MAX_LISTED_PROJECTS]

        return {
            "projects": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "status": p.status.value,
                    "deadline": p.deadline.isoformat() if p.deadline else None,
                    "open_task_count": m["open_task_count"],
                    "completed_task_count": m["completed_task_count"],
                    "risk": round(m["risk"], 2),
                }
                for p, m in shown
            ],
            "count": len(shown),
            "truncated": len(rows) > len(shown),
            "success": True,
        }


LIST_PROJECTS_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["active", "closed", "all"],
            "description": "Which projects to list. Defaults to 'active'.",
        },
        "include_personal": {
            "type": "boolean",
            "description": (
                "Include the user's personal project — the catch-all every "
                "loose task lands in. Off by default; turn it on only when "
                "the user explicitly asks about their personal/loose work."
            ),
        },
    },
    "required": [],
}

LIST_PROJECTS_DEFINITION = {
    "name": "list_projects",
    "handler": list_projects_handler,
    "input_model": ListProjectsInput,
    "schema": LIST_PROJECTS_SCHEMA,
    "description": (
        "List the user's projects with their deadline, open/completed task "
        "counts and risk score. Use this first whenever the user mentions a "
        "project by name, so you can match what they said to a real project "
        "before acting on it. Never invent a project that isn't in this list.\n\n"
        "A project is also what the user means by a **goal**: Cortex has no "
        "separate goal entity, so 'mục tiêu', 'goal', 'kế hoạch X', 'OKR' and "
        "'đợt này' all resolve here. Call this before saying Cortex doesn't "
        "track something — it probably does, under this name."
    ),
}
