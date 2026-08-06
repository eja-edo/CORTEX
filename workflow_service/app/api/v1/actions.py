from fastapi import APIRouter, Depends

from app.core.security import get_current_user, CurrentUser
from app.actions.registry import action_registry
from app.triggers.internal_event_listener import load_implemented_event_types

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
                        # Milestone 1.9: sourced from the shared event
                        # vocabulary (backend/app/events/vocabulary.py, via
                        # event_vocabulary.json) instead of a 4th hardcoded
                        # list — this used to only list 8 of the 12 known
                        # event types (missing schedule.reminder.due,
                        # conversation.message.created, tool.executed,
                        # google_calendar.synced entirely), and included 2
                        # reserved types nothing publishes. Only
                        # has_payload_schema=true types are offered here —
                        # a user shouldn't be able to pick a trigger event
                        # that will never fire.
                        "event": {
                            "type": "string",
                            "enum": load_implemented_event_types(),
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
