import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult
from app.config import settings


class UpdateTaskAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.update_task"

    @property
    def display_name(self) -> str:
        return "Cập Nhật Task"

    @property
    def description(self) -> str:
        return "Cập nhật một task đã có trong Cortex"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "title": "Task ID",
                    "description": "Hỗ trợ template: {{trigger.task_id}}"
                },
                "title": {
                    "type": "string",
                    "title": "Tiêu đề mới",
                    "description": "Để trống = không đổi"
                },
                "description": {
                    "type": "string",
                    "title": "Mô tả mới",
                    "description": "Để trống = không đổi"
                },
                "status": {
                    "type": "string",
                    "title": "Trạng thái",
                    "enum": ["todo", "in_progress", "done", "cancelled"]
                },
                "due_date": {
                    "type": "string",
                    "title": "Hạn chót mới",
                    "description": "ISO 8601. Để trống = không đổi"
                },
                "priority": {
                    "type": "string",
                    "title": "Độ ưu tiên mới",
                    "enum": ["low", "medium", "high", "urgent"]
                }
            },
            "required": ["task_id"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        task_id = self.resolve_template(config.get("task_id", ""), context)
        if not task_id:
            return ActionResult(success=False, output={}, error="task_id is required")

        payload = {}
        title = self.resolve_template(config.get("title", ""), context)
        if title:
            payload["title"] = title
        description = self.resolve_template(config.get("description", ""), context)
        if description:
            payload["description"] = description
        due_date = self.resolve_template(config.get("due_date", ""), context)
        if due_date:
            payload["due_date"] = due_date
        if config.get("status"):
            payload["status"] = config["status"]
        if config.get("priority"):
            payload["priority"] = config["priority"]

        if not payload:
            return ActionResult(success=False, output={}, error="No fields to update")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.patch(
                    f"{settings.cortex_backend_url}/api/tasks/{task_id}",
                    json=payload,
                    headers={
                        "X-Internal-API-Key": settings.cortex_internal_api_key,
                        "X-User-ID": context.user_id,
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                task_data = response.json()

                return ActionResult(
                    success=True,
                    output={
                        "task_id": task_data.get("id"),
                        "title": task_data.get("title"),
                        "status": task_data.get("status"),
                    }
                )

            except httpx.HTTPError as e:
                return ActionResult(
                    success=False,
                    output={},
                    error=f"Failed to update task: {str(e)}"
                )
