from app.actions.registry import action_registry
from app.actions.builtin.create_note import CreateNoteAction
from app.actions.builtin.request_attention import RequestAttentionAction
from app.actions.builtin.send_notification import SendNotificationAction
from app.actions.builtin.success import SuccessAction
from app.actions.builtin.update_note import UpdateNoteAction
from app.actions.builtin.create_schedule import CreateScheduleAction
from app.actions.builtin.call_ai import CallAIAction
from app.actions.builtin.call_api import CallApiAction
from app.actions.builtin.extract_html import ExtractHtmlAction
from app.actions.builtin.wait_action import WaitAction
from app.actions.builtin.condition import ConditionAction
from app.actions.builtin.get_schedules import GetSchedulesAction
from app.actions.builtin.create_task import CreateTaskAction
from app.actions.builtin.update_task import UpdateTaskAction

action_registry.register(CreateNoteAction())
action_registry.register(RequestAttentionAction())
action_registry.register(SendNotificationAction())
action_registry.register(SuccessAction())
action_registry.register(UpdateNoteAction())
action_registry.register(CreateScheduleAction())
action_registry.register(CallAIAction())
action_registry.register(CallApiAction())
action_registry.register(ExtractHtmlAction())
action_registry.register(WaitAction())
action_registry.register(ConditionAction())
action_registry.register(GetSchedulesAction())
action_registry.register(CreateTaskAction())
action_registry.register(UpdateTaskAction())
