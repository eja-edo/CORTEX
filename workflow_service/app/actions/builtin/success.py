from app.actions.base import BaseAction, ActionContext, ActionResult


class SuccessAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.test_success"

    @property
    def display_name(self) -> str:
        return "Success Test"

    @property
    def description(self) -> str:
        return "Luôn trả về success — dùng để test"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "title": "Message",
                    "default": "ok"
                }
            }
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        return ActionResult(
            success=True,
            output={"message": config.get("message", "ok"), "node_id": context.node_id}
        )
