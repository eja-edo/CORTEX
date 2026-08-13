"""Agent tools initialization and registration."""

from app.ai.agents.tool_registry import get_tool_registry

# Import tool definitions
from app.ai.tools.search_notes import SEARCH_NOTES_DEFINITION
from app.ai.tools.create_note import CREATE_NOTE_DEFINITION
from app.ai.tools.update_note import UPDATE_NOTE_DEFINITION
from app.ai.tools.get_schedules import GET_SCHEDULES_DEFINITION
from app.ai.tools.create_schedule import CREATE_SCHEDULE_DEFINITION
from app.ai.tools.create_task import CREATE_TASK_DEFINITION
from app.ai.tools.propose_plan import PROPOSE_PLAN_DEFINITION
from app.ai.tools.list_pending_tasks import LIST_PENDING_TASKS_DEFINITION
from app.ai.tools.confirm_task import CONFIRM_TASK_DEFINITION
from app.ai.tools.update_schedule import UPDATE_SCHEDULE_DEFINITION
from app.ai.tools.search_knowledge import SEARCH_KNOWLEDGE_DEFINITION
from app.ai.tools.summarize_asset import SUMMARIZE_ASSET_DEFINITION
from app.ai.tools.get_notifications import GET_NOTIFICATIONS_DEFINITION
from app.ai.tools.web_search import WEB_SEARCH_DEFINITION
from app.ai.tools.neural_search import NEURAL_SEARCH_DEFINITION
from app.ai.tools.deep_research import DEEP_RESEARCH_DEFINITION
from app.ai.tools.revert_action import REVERT_ACTION_DEFINITION
from app.ai.tools.extract_memory import EXTRACT_MEMORY_DEFINITION
from app.ai.tools.web_fetch import WEB_FETCH_DEFINITION
from app.ai.tools.ask_user_choice import ASK_USER_CHOICE_DEFINITION

def register_all_tools() -> None:
    """Register all tools with the global registry."""
    registry = get_tool_registry()

    # Register tools
    tools = [
        SEARCH_NOTES_DEFINITION,
        CREATE_NOTE_DEFINITION,
        UPDATE_NOTE_DEFINITION,
        GET_SCHEDULES_DEFINITION,
        CREATE_SCHEDULE_DEFINITION,
        CREATE_TASK_DEFINITION,
        PROPOSE_PLAN_DEFINITION,
        LIST_PENDING_TASKS_DEFINITION,
        CONFIRM_TASK_DEFINITION,
        UPDATE_SCHEDULE_DEFINITION,
        SEARCH_KNOWLEDGE_DEFINITION,
        SUMMARIZE_ASSET_DEFINITION,
        GET_NOTIFICATIONS_DEFINITION,
        WEB_SEARCH_DEFINITION,
        NEURAL_SEARCH_DEFINITION,
        DEEP_RESEARCH_DEFINITION,
        REVERT_ACTION_DEFINITION,
        EXTRACT_MEMORY_DEFINITION,
        WEB_FETCH_DEFINITION,
        ASK_USER_CHOICE_DEFINITION,
    ]

    for tool_def in tools:
        registry.register(
            name=tool_def["name"],
            description=tool_def["description"],
            schema=tool_def["schema"],
            handler=tool_def["handler"],
            input_model=tool_def.get("input_model"),
        )


# Auto-register on import
register_all_tools()

__all__ = [
    "register_all_tools",
    "get_tool_registry",
]
