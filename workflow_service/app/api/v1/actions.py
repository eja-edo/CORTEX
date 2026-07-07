from fastapi import APIRouter, Depends

from app.core.security import get_current_user, CurrentUser
from app.actions.registry import action_registry

router = APIRouter()


@router.get("")
async def list_actions(current_user: CurrentUser = Depends(get_current_user)):
    return {
        "actions": action_registry.list_all(),
        "triggers": [
            {
                "type": "trigger.internal_event",
                "display_name": "Cortex Event",
                "description": "Trigger khi có sự kiện trong Cortex",
                "config_schema": {
                    "properties": {
                        "event": {
                            "type": "string",
                            "enum": [
                                "note.created", "note.updated", "note.deleted",
                                "schedule.created", "schedule.updated", "schedule.completed",
                                "asset.uploaded", "asset.processed"
                            ]
                        },
                        "filters": {"type": "object"}
                    }
                }
            },
            {
                "type": "trigger.webhook",
                "display_name": "Webhook",
                "description": "Trigger khi nhận HTTP webhook từ bên ngoài",
                "config_schema": {}
            },
            {
                "type": "trigger.manual",
                "display_name": "Manual",
                "description": "Trigger thủ công bởi user",
                "config_schema": {}
            }
        ]
    }
