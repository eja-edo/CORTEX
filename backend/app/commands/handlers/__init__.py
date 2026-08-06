"""Command handlers initialization and registration."""

from app.commands.handlers.note_commands import register_note_commands
from app.commands.handlers.schedule_commands import register_schedule_commands


def register_all_commands() -> None:
    """Register all commands with the global CommandRegistry."""
    register_note_commands()
    register_schedule_commands()


# Auto-register on import (same convention as app/ai/tools/__init__.py)
register_all_commands()

__all__ = ["register_all_commands"]
