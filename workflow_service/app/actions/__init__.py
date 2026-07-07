from app.actions.registry import action_registry
from app.actions.builtin.create_note import CreateNoteAction
from app.actions.builtin.send_notification import SendNotificationAction
from app.actions.builtin.success import SuccessAction
from app.actions.builtin.update_note import UpdateNoteAction
from app.actions.builtin.create_schedule import CreateScheduleAction
from app.actions.builtin.call_ai import CallAIAction
from app.actions.builtin.call_webhook import CallWebhookAction
from app.actions.builtin.wait_action import WaitAction
from app.actions.builtin.condition import ConditionAction

action_registry.register(CreateNoteAction())
action_registry.register(SendNotificationAction())
action_registry.register(SuccessAction())
action_registry.register(UpdateNoteAction())
action_registry.register(CreateScheduleAction())
action_registry.register(CallAIAction())
action_registry.register(CallWebhookAction())
action_registry.register(WaitAction())
action_registry.register(ConditionAction())
