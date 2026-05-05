"""Agent tools initialization and registration."""

from app.services.agent.tool_registry import get_tool_registry

# Import tool definitions
from app.services.agent.tools.search_notes import SEARCH_NOTES_DEFINITION
from app.services.agent.tools.create_note import CREATE_NOTE_DEFINITION
from app.services.agent.tools.get_schedules import GET_SCHEDULES_DEFINITION
from app.services.agent.tools.create_schedule import CREATE_SCHEDULE_DEFINITION
from app.services.agent.tools.update_schedule import UPDATE_SCHEDULE_DEFINITION
from app.services.agent.tools.search_knowledge import SEARCH_KNOWLEDGE_DEFINITION
from app.services.agent.tools.summarize_asset import SUMMARIZE_ASSET_DEFINITION
from app.services.agent.tools.get_notifications import GET_NOTIFICATIONS_DEFINITION


def register_all_tools() -> None:
    """Register all tools with the global registry."""
    registry = get_tool_registry()

    # Register tools
    tools = [
        SEARCH_NOTES_DEFINITION,
        CREATE_NOTE_DEFINITION,
        GET_SCHEDULES_DEFINITION,
        CREATE_SCHEDULE_DEFINITION,
        UPDATE_SCHEDULE_DEFINITION,
        SEARCH_KNOWLEDGE_DEFINITION,
        SUMMARIZE_ASSET_DEFINITION,
        GET_NOTIFICATIONS_DEFINITION,
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
