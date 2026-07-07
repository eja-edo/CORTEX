from app.actions.base import BaseAction


class ActionRegistry:
    _instance = None
    _actions: dict[str, BaseAction] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, action: BaseAction):
        self._actions[action.action_type] = action
        print(f"[ActionRegistry] Registered action: {action.action_type}")

    def get(self, action_type: str) -> BaseAction | None:
        return self._actions.get(action_type)

    def list_all(self) -> list[dict]:
        return [
            {
                "type": action.action_type,
                "display_name": action.display_name,
                "description": action.description,
                "config_schema": action.config_schema,
            }
            for action in self._actions.values()
        ]


action_registry = ActionRegistry()
