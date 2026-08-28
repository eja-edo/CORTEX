"""`get_project_tasks` — việc trong một dự án (DESIGN 9.2).

Trả về cùng dữ liệu màn **Việc** (10.2) hiển thị, cố ý: nếu agent và màn
hình nói hai điều khác nhau về cùng một dự án thì người dùng tin cái nào là
tuỳ họ đang mở cái gì, và đó là kiểu mất niềm tin không sửa được bằng một
bản vá.

`project_ref` tường minh, không có "dự án hiện tại" ngầm — xem
`project_ref.py` về vì sao.
"""

from typing import Optional

from pydantic import BaseModel

from app.ai.agents.tool_context import ToolContext
from app.ai.tools.project_ref import resolve_project_ref, unresolved_result
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Cùng lý do với `MAX_LISTED_PROJECTS`: một dự án 200 việc trả về nguyên
# vẹn là một tệp text, không phải một câu trả lời.
MAX_LISTED_TASKS = 30


class GetProjectTasksInput(BaseModel):
    project_ref: str
    status: Optional[str] = None


async def get_project_tasks_handler(args: dict, ctx: ToolContext) -> dict:
    from sqlalchemy import select

    from app.models import Task, TaskStatus
    from app.services.today import OPEN_STATUSES

    project_ref = args["project_ref"]
    raw_status = (args.get("status") or "open").lower()

    async with ctx.async_db() as db:
        resolution = await resolve_project_ref(db, ctx.user_id, project_ref)
        if not resolution.resolved:
            return unresolved_result(resolution, project_ref)

        project = resolution.project
        stmt = select(Task).where(
            Task.project_id == project.id,
            Task.user_id == ctx.user_id,
            # Occurrence exception của một chuỗi lặp không phải việc độc
            # lập — cùng bộ lọc `TodayService._open_tasks` dùng.
            Task.recurrence_id.is_(None),
        )
        if raw_status == "open":
            stmt = stmt.where(Task.status.in_(OPEN_STATUSES))
        elif raw_status != "all":
            stmt = stmt.where(Task.status == TaskStatus(raw_status))

        stmt = stmt.order_by(Task.due_date.asc().nullslast(), Task.created_at.asc())
        tasks = list((await db.scalars(stmt)).all())
        shown = tasks[:MAX_LISTED_TASKS]

        return {
            "project": {
                "id": str(project.id),
                "name": project.name,
                "deadline": project.deadline.isoformat() if project.deadline else None,
            },
            "tasks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "status": t.status.value,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                    "priority": t.priority.value if t.priority else None,
                }
                for t in shown
            ],
            "count": len(shown),
            "truncated": len(tasks) > len(shown),
            "success": True,
        }


GET_PROJECT_TASKS_SCHEMA = {
    "type": "object",
    "properties": {
        "project_ref": {
            "type": "string",
            "description": (
                "The project's name exactly as the user said it, or its id. "
                "Required — there is no 'current project'; every call says "
                "which project it means."
            ),
        },
        "status": {
            "type": "string",
            "enum": ["open", "todo", "in_progress", "done", "all"],
            "description": "Defaults to 'open' (todo + in_progress).",
        },
    },
    "required": ["project_ref"],
}

GET_PROJECT_TASKS_DEFINITION = {
    "name": "get_project_tasks",
    "handler": get_project_tasks_handler,
    "input_model": GetProjectTasksInput,
    "schema": GET_PROJECT_TASKS_SCHEMA,
    "description": (
        "List the tasks inside one project. If the name doesn't match exactly "
        "one project, this returns the candidates instead of guessing — ask "
        "the user which one they meant rather than picking for them."
    ),
}
