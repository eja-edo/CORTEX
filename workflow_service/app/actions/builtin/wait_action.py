from app.actions.base import BaseAction, ActionContext, ActionResult


class WaitAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.wait"

    @property
    def display_name(self) -> str:
        return "Chờ (Wait)"

    @property
    def description(self) -> str:
        return "Tạm dừng workflow trong một khoảng thời gian"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "duration": {
                    "type": "integer",
                    "title": "Duration",
                    "description": "Số lượng đơn vị thời gian",
                    "default": 1,
                    "minimum": 1
                },
                "unit": {
                    "type": "string",
                    "title": "Unit",
                    "enum": ["seconds", "minutes", "hours"],
                    "default": "minutes",
                    "description": "Đơn vị thời gian"
                }
            },
            "required": ["duration", "unit"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        duration = config.get("duration", 1)
        unit = config.get("unit", "minutes")

        return ActionResult(
            success=True,
            output={
                "waited": True,
                "duration": duration,
                "unit": unit,
            }
        )
