import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult
from app.config import settings


class CallWebhookAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.call_webhook"

    @property
    def display_name(self) -> str:
        return "Call Webhook"

    @property
    def description(self) -> str:
        return "Gửi HTTP request ra ngoài"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "title": "URL",
                    "description": "URL đích, hỗ trợ template"
                },
                "method": {
                    "type": "string",
                    "title": "Method",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "default": "POST"
                },
                "headers": {
                    "type": "object",
                    "title": "Headers",
                    "description": "Headers dạng key-value",
                    "default": {}
                },
                "body": {
                    "type": "string",
                    "title": "Body",
                    "description": "Request body, hỗ trợ template variables"
                }
            },
            "required": ["url"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        url = self.resolve_template(config.get("url", ""), context)
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {}) or {}
        body = self.resolve_template(config.get("body", ""), context)

        # Resolve template in headers values too
        resolved_headers = {}
        for k, v in headers.items():
            if isinstance(v, str):
                resolved_headers[k] = self.resolve_template(v, context)
            else:
                resolved_headers[k] = v

        if not url:
            return ActionResult(success=False, output={}, error="url is required")

        async with httpx.AsyncClient() as client:
            try:
                request_kwargs = {
                    "headers": resolved_headers,
                    "timeout": 30.0,
                }

                if body:
                    request_kwargs["content"] = body

                if method == "GET":
                    response = await client.get(url, **request_kwargs)
                elif method == "POST":
                    response = await client.post(url, **request_kwargs)
                elif method == "PUT":
                    response = await client.put(url, **request_kwargs)
                elif method == "PATCH":
                    response = await client.patch(url, **request_kwargs)
                elif method == "DELETE":
                    response = await client.delete(url, **request_kwargs)
                else:
                    return ActionResult(
                        success=False, output={}, error=f"Unsupported method: {method}"
                    )

                return ActionResult(
                    success=True,
                    output={
                        "status_code": response.status_code,
                        "response_body": response.text[:10000],
                    }
                )

            except httpx.HTTPError as e:
                return ActionResult(
                    success=False,
                    output={},
                    error=f"Webhook call failed: {str(e)}"
                )
