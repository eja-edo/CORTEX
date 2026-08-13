import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult
from app.config import settings


class CreateTaskAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.create_task"

    @property
    def display_name(self) -> str:
        return "Tạo Task"

    @property
    def description(self) -> str:
        return "Tạo một task mới trong Cortex"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "title": "Tiêu đề",
                    "description": "Hỗ trợ template: {{trigger.title}}"
                },
                "description": {
                    "type": "string",
                    "title": "Mô tả",
                    "description": "Hỗ trợ template variables"
                },
                "due_date": {
                    "type": "string",
                    "title": "Hạn chót",
                    "description": "ISO 8601, hỗ trợ template. Để trống = không có hạn"
                },
                "priority": {
                    "type": "string",
                    "title": "Độ ưu tiên",
                    "enum": ["low", "medium", "high", "urgent"]
                }
            },
            "required": ["title"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        title = self.resolve_template(config.get("title", ""), context)
        description = self.resolve_template(config.get("description", ""), context)
        due_date = self.resolve_template(config.get("due_date", ""), context)
        priority = config.get("priority")

        if not title:
            return ActionResult(success=False, output={}, error="title is required")

        payload = {"title": title}
        if description:
            payload["description"] = description
        if due_date:
            payload["due_date"] = due_date
        if priority:
            payload["priority"] = priority

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{settings.cortex_backend_url}/api/tasks",
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
                    error=f"Failed to create task: {str(e)}"
                )
