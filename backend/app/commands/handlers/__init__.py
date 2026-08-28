"""Command handlers initialization and registration."""

from app.commands.handlers.note_commands import register_note_commands
from app.commands.handlers.plan_commands import register_plan_commands
from app.commands.handlers.project_commands import register_project_commands
from app.commands.handlers.schedule_commands import register_schedule_commands
from app.commands.handlers.task_commands import register_task_commands


def register_all_commands() -> None:
    """Register all commands with the global CommandRegistry."""
    register_note_commands()
    register_schedule_commands()
    register_task_commands()
    register_plan_commands()
    register_project_commands()


# Auto-register on import (same convention as app/ai/tools/__init__.py)
register_all_commands()

__all__ = ["register_all_commands"]
