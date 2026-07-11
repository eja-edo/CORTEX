import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult
from app.config import settings


class CreateNoteAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.create_note"

    @property
    def display_name(self) -> str:
        return "Tạo Note"

    @property
    def description(self) -> str:
        return "Tạo một note mới trong Cortex"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "title": "Tiêu đề",
                    "description": "Hỗ trợ template: {{trigger.event}}"
                },
                "content": {
                    "type": "string",
                    "title": "Nội dung",
                    "description": "Hỗ trợ template variables"
                },
                "workspace_id": {
                    "type": "string",
                    "title": "Workspace ID",
                    "description": "Để trống = personal workspace"
                }
            },
            "required": ["title"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        title = self.resolve_template(config.get("title", "Untitled"), context)
        content = self.resolve_template(config.get("content", ""), context)
        workspace_id = config.get("workspace_id") or context.workspace_id
        if not workspace_id:
            return ActionResult(
                success=False,
                output={},
                error="workspace_id is required (set in node config or workflow workspace)"
            )
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{settings.cortex_backend_url}/api/notes",
                    json={
                        "workspace_id": workspace_id,
                        "content": content or title,
                        "content_type": "markdown",
                    },
                    headers={
                        "X-Internal-API-Key": settings.cortex_internal_api_key,
                        "X-User-ID": context.user_id,
                    },
                    timeout=10.0
                )
                response.raise_for_status()
                note_data = response.json()

                return ActionResult(
                    success=True,
                    output={"note_id": note_data.get("id"), "title": title}
                )

            except httpx.HTTPError as e:
                return ActionResult(
                    success=False,
                    output={},
                    error=f"Failed to create note: {str(e)}"
                )
