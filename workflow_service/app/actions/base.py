from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass
import re


@dataclass
class ActionContext:
    user_id: str
    workflow_id: str
    instance_id: str
    node_id: str
    trigger_data: dict[str, Any]
    previous_outputs: dict[str, Any]
    node_id_labels: dict[str, str] | None = None


@dataclass
class ActionResult:
    success: bool
    output: dict[str, Any]
    error: str | None = None


class BaseAction(ABC):

    @property
    @abstractmethod
    def action_type(self) -> str:
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    def config_schema(self) -> dict:
        return {}

    @abstractmethod
    async def execute(self, config: dict[str, Any], context: ActionContext) -> ActionResult:
        pass

    def resolve_template(self, template: str, context: ActionContext) -> str:
        def replace_var(match):
            path = match.group(1).strip()
            parts = path.split(".")

            if parts[0] == "trigger":
                value = context.trigger_data
                for part in parts[1:]:
                    value = value.get(part, "") if isinstance(value, dict) else ""
            elif parts[0] == "steps":
                step_id = parts[1]
                # First try exact match (node_id), then try label match
                value = context.previous_outputs.get(step_id, {})
                if not value and context.node_id_labels:
                    # Try to find by label
                    actual_id = context.node_id_labels.get(step_id)
                    if actual_id:
                        value = context.previous_outputs.get(actual_id, {})
                for part in parts[2:]:
                    value = value.get(part, "") if isinstance(value, dict) else ""
            else:
                value = ""

            return str(value)

        return re.sub(r'\{\{(.+?)\}\}', replace_var, template)
