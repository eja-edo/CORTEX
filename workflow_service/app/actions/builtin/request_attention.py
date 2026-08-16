import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult
from app.config import settings


class RequestAttentionAction(BaseAction):
    """Milestone 4.3: workflows never write to the notifications table
    directly. They ask the Attention Gate for attention; the Gate decides
    whether/when/how to deliver it (today it's a pass-through stub — see
    backend's `app.services.attention_gate`)."""

    @property
    def action_type(self) -> str:
        return "action.request_attention"

    @property
    def display_name(self) -> str:
        return "Yêu Cầu Chú Ý"

    @property
    def description(self) -> str:
        return "Gửi yêu cầu đến Attention Gate — Gate quyết định có gửi, khi nào, và gộp với gì"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "title": "Tiêu đề thông báo"},
                "body": {"type": "string", "title": "Nội dung thông báo"},
                "type": {
                    "type": "string",
                    "title": "Loại",
                    "enum": ["info", "success", "warning", "error"],
                    "default": "info"
                },
                # Optional. Name the domain item this candidate is about
                # (e.g. "{{trigger.item_type}}"/"{{trigger.task_id}}") to let
                # the backend's Attention Gate actually dedup/rank it —
                # omit all three and it falls back to unconditional
                # pass-through (see backend's app.services.attention_gate).
                "item_type": {
                    "type": "string",
                    "title": "Loại đối tượng (tuỳ chọn)",
                    "enum": ["task", "commitment", "schedule"],
                },
                "item_id": {"type": "string", "title": "ID đối tượng (tuỳ chọn)"},
                "reason_key": {"type": "string", "title": "Lý do (tuỳ chọn)"},
            },
            "required": ["title"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        title = self.resolve_template(config.get("title", ""), context)
        # Support both body (FE) and message (legacy)
        body = config.get("body") or config.get("message", "")
        body = self.resolve_template(body, context)
        notif_type = config.get("type", "info")

        # Optional rich content blocks
        raw_content = config.get("content", [])
        if isinstance(raw_content, list) and len(raw_content) > 0:
            resolved_content = []
            for block in raw_content:
                resolved = dict(block)
                if "text" in resolved:
                    resolved["text"] = self.resolve_template(resolved["text"], context)
                if "html" in resolved:
                    resolved["html"] = self.resolve_template(resolved["html"], context)
                if "content" in resolved:
                    resolved["content"] = self.resolve_template(resolved["content"], context)
                resolved_content.append(resolved)
        else:
            resolved_content = []

        raw_actions = config.get("actions", [])
        resolved_actions = []
        if isinstance(raw_actions, list):
            for act in raw_actions:
                resolved = dict(act)
                if "url" in resolved:
                    resolved["url"] = self.resolve_template(resolved["url"], context)
                if "label" in resolved:
                    resolved["label"] = self.resolve_template(resolved["label"], context)
                resolved_actions.append(resolved)

        async with httpx.AsyncClient() as client:
            try:
                payload = {
                    "user_id": context.user_id,
                    "title": title,
                    "body": body,
                    "type": notif_type,
                }
                if resolved_content:
                    payload["content"] = resolved_content
                if resolved_actions:
                    payload["actions"] = resolved_actions

                item_type = config.get("item_type")
                item_id = config.get("item_id")
                reason_key = config.get("reason_key")
                if item_type and item_id and reason_key:
                    payload["item_type"] = item_type
                    payload["item_id"] = self.resolve_template(item_id, context)
                    payload["reason_key"] = self.resolve_template(reason_key, context)

                response = await client.post(
                    f"{settings.cortex_backend_url}/internal/attention/request",
                    json=payload,
                    headers={"X-Internal-API-Key": settings.cortex_internal_api_key},
                    timeout=5.0
                )
                response.raise_for_status()
                return ActionResult(success=True, output={"sent": True})

            except httpx.HTTPError as e:
                return ActionResult(success=False, output={}, error=str(e))
