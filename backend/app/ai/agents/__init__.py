"""Agent service module for AI conversation management."""

# Import commands first: migrated tool handlers (create_note, update_note,
# create_schedule, update_schedule, revert_action) call get_command_registry()
# and expect note.*/schedule.* commands to already be registered.
# app/commands/handlers/__init__.py registers on import (module-level call,
# guarded by Python's import cache) — CommandRegistry.register() raises on
# a duplicate name, unlike ToolRegistry below, so this must NOT be called
# again here.
from app.commands.handlers import register_all_commands

# Import tools to auto-register them
from app.ai.tools import register_all_tools

# Auto-register all tools on module import (ToolRegistry.register()
# silently overwrites duplicates, so re-calling here is harmless/defensive).
register_all_tools()

__all__ = ["register_all_commands", "register_all_tools"]
