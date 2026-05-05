"""Agent service module for AI conversation management."""

# Import tools to auto-register them
from app.services.agent.tools import register_all_tools

# Auto-register all tools on module import
register_all_tools()

__all__ = ["register_all_tools"]
