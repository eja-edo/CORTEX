import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult
from app.config import settings


class UpdateNoteAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.update_note"

    @property
    def display_name(self) -> str:
        return "Update Note"

    @property
    def description(self) -> str:
        return "Update an existing note in Cortex"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "title": "Note ID",
                    "description": "Hỗ trợ template: {{trigger.note_id}}"
                },
                "content": {
                    "type": "string",
                    "title": "Nội dung mới",
                    "description": "Hỗ trợ template variables"
                },
                "append": {
                    "type": "boolean",
                    "title": "Ghi thêm (append)",
                    "default": False,
                    "description": "True = thêm vào cuối, False = ghi đè"
                }
            },
            "required": ["note_id", "content"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        note_id = self.resolve_template(config.get("note_id", ""), context)
        content = self.resolve_template(config.get("content", ""), context)
        append = config.get("append", False)

        if not note_id:
            return ActionResult(success=False, output={}, error="note_id is required")

        async with httpx.AsyncClient() as client:
            try:
                # First get current content if appending
                if append:
                    get_resp = await client.get(
                        f"{settings.cortex_backend_url}/api/notes/{note_id}",
                        headers={
                            "X-Internal-API-Key": settings.cortex_internal_api_key,
                            "X-User-ID": context.user_id,
                        },
                        timeout=10.0,
                    )
                    get_resp.raise_for_status()
                    existing = get_resp.json()
                    existing_content = existing.get("content", "")
                    content = existing_content + "\n" + content

                response = await client.patch(
                    f"{settings.cortex_backend_url}/api/notes/{note_id}",
                    json={"content": content},
                    headers={
                        "X-Internal-API-Key": settings.cortex_internal_api_key,
                        "X-User-ID": context.user_id,
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                note_data = response.json()

                return ActionResult(
                    success=True,
                    output={
                        "note_id": note_id,
                        "updated": True,
                        "title": note_data.get("title"),
                    }
                )

            except httpx.HTTPError as e:
                return ActionResult(
                    success=False,
                    output={},
                    error=f"Failed to update note: {str(e)}"
                )
