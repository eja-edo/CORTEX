from app.actions.base import BaseAction, ActionContext, ActionResult


class ConditionAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.condition"

    @property
    def display_name(self) -> str:
        return "Điều kiện (Condition)"

    @property
    def description(self) -> str:
        return "Rẽ nhánh dựa trên điều kiện so sánh"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "left": {
                    "type": "string",
                    "title": "Giá trị trái",
                    "description": "Hỗ trợ template variables. Ví dụ: {{steps.node_id.output}}"
                },
                "operator": {
                    "type": "string",
                    "title": "Operator",
                    "enum": [
                        "equals", "not_equals",
                        "contains", "not_contains",
                        "is_empty", "is_not_empty"
                    ],
                    "default": "equals"
                },
                "right": {
                    "type": "string",
                    "title": "Giá trị phải",
                    "description": "Ẩn nếu operator là is_empty/is_not_empty. Hỗ trợ template."
                }
            },
            "required": ["left", "operator"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        left = self.resolve_template(config.get("left", ""), context)
        operator = config.get("operator", "equals")
        right = self.resolve_template(config.get("right", ""), context)

        result = False

        if operator == "equals":
            result = left == right
        elif operator == "not_equals":
            result = left != right
        elif operator == "contains":
            result = right in left
        elif operator == "not_contains":
            result = right not in left
        elif operator == "is_empty":
            result = not left or left.strip() == ""
        elif operator == "is_not_empty":
            result = bool(left and left.strip())
        else:
            return ActionResult(
                success=False,
                output={},
                error=f"Unknown operator: {operator}"
            )

        branch = "true" if result else "false"

        return ActionResult(
            success=True,
            output={
                "condition_result": result,
                "branch": branch,
                "left": left,
                "operator": operator,
                "right": right,
            }
        )
