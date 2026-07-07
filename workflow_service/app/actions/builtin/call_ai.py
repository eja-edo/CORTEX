import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult
from app.config import settings


class CallAIAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.call_ai"

    @property
    def display_name(self) -> str:
        return "Call AI"

    @property
    def description(self) -> str:
        return "Send a prompt to AI for one-shot text completion"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "title": "Prompt",
                    "description": "Hỗ trợ template variables. Ví dụ: {{trigger.content}}, {{steps.node_id.output}}"
                },
                "output_key": {
                    "type": "string",
                    "title": "Output key",
                    "description": "Tên key để lưu kết quả (mặc định: ai_result)",
                    "default": "ai_result"
                }
            },
            "required": ["prompt"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        prompt = self.resolve_template(config.get("prompt", ""), context)
        output_key = config.get("output_key", "ai_result")

        if not prompt:
            return ActionResult(success=False, output={}, error="prompt is required")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{settings.cortex_backend_url}/api/agent/complete",
                    json={"prompt": prompt},
                    headers={
                        "X-Internal-API-Key": settings.cortex_internal_api_key,
                        "X-User-ID": context.user_id,
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                print(f"AI call response: {data}")  # Debugging line to log the response

                return ActionResult(
                    success=True,
                    output={
                        output_key: data.get("reply", ""),
                        "model_used": data.get("model_used", ""),
                    }
                )

            except httpx.HTTPError as e:
                return ActionResult(
                    success=False,
                    output={},
                    error=f"AI call failed: {str(e)}"
                )
