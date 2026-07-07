import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult
from app.config import settings


class CreateScheduleAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.schedule"

    @property
    def display_name(self) -> str:
        return "Create Schedule"

    @property
    def description(self) -> str:
        return "Create a new calendar event in Cortex"

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
                "start_time": {
                    "type": "string",
                    "title": "Thời gian bắt đầu",
                    "description": "ISO 8601, hỗ trợ template"
                },
                "end_time": {
                    "type": "string",
                    "title": "Thời gian kết thúc",
                    "description": "ISO 8601, hỗ trợ template"
                },
                "description": {
                    "type": "string",
                    "title": "Mô tả",
                    "description": "Hỗ trợ template variables"
                }
            },
            "required": ["title", "start_time", "end_time"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        title = self.resolve_template(config.get("title", "Untitled"), context)
        start_time = self.resolve_template(config.get("start_time", ""), context)
        end_time = self.resolve_template(config.get("end_time", ""), context)
        description = self.resolve_template(config.get("description", ""), context)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{settings.cortex_backend_url}/api/schedules",
                    json={
                        "title": title,
                        "start_time": start_time,
                        "end_time": end_time,
                        "description": description or None,
                    },
                    headers={
                        "X-Internal-API-Key": settings.cortex_internal_api_key,
                        "X-User-ID": context.user_id,
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                schedule_data = response.json()

                return ActionResult(
                    success=True,
                    output={
                        "schedule_id": schedule_data.get("id"),
                        "title": title,
                        "start_time": start_time,
                    }
                )

            except httpx.HTTPError as e:
                return ActionResult(
                    success=False,
                    output={},
                    error=f"Failed to create schedule: {str(e)}"
                )
