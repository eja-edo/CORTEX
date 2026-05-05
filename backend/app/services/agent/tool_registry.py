"""Tool registry for managing agent tools and their execution."""

import json
from typing import Callable, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, ValidationError

from app.services.agent.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ToolDefinition:
    """Definition of a single tool."""

    def __init__(
        self,
        name: str,
        description: str,
        schema: dict,
        handler: Callable,
        input_model: Optional[type[BaseModel]] = None,
    ):
        """Initialize tool definition."""
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler
        self.input_model = input_model

    def to_gemini_format(self) -> dict:
        """Convert to Gemini function calling format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.schema,
        }

    async def validate_and_execute(
        self,
        args: dict,
        ctx: ToolContext,
    ) -> dict:
        """
        Validate arguments and execute handler.
        
        Returns:
            {"result": ..., "success": True} or {"error": ..., "success": False}
        """
        start_time = datetime.utcnow()

        try:
            # Validate arguments if input model is provided
            if self.input_model:
                try:
                    validated_args = self.input_model(**args)
                    args = validated_args.model_dump()
                except ValidationError as exc:
                    error_msg = f"Invalid arguments: {exc.json()}"
                    logger.warning(f"Tool {self.name} validation failed: {error_msg}")
                    return {
                        "error": error_msg,
                        "success": False,
                    }

            # Execute handler
            result = await self.handler(args, ctx)

            # Log execution
            elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.info(
                f"✅ Tool '{self.name}' executed in {elapsed_ms:.1f}ms | user={ctx.user_id}"
            )

            return {
                "result": result,
                "success": True,
            }

        except Exception as exc:
            elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            error_msg = f"Tool execution failed: {str(exc)}"

            logger.error(
                f"❌ Tool '{self.name}' failed in {elapsed_ms:.1f}ms | user={ctx.user_id} | error={error_msg}",
                exc_info=True,
            )

            return {
                "error": error_msg,
                "success": False,
            }


class ToolRegistry:
    """Registry for agent tools."""

    def __init__(self):
        """Initialize empty registry."""
        self.tools: Dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        schema: dict,
        handler: Callable,
        input_model: Optional[type[BaseModel]] = None,
    ) -> None:
        """
        Register a new tool.
        
        Args:
            name: Tool name (must be valid identifier)
            description: Human-readable description
            schema: JSON schema for parameters (Gemini compatible)
            handler: Async callable(args: dict, ctx: ToolContext) -> dict
            input_model: Optional Pydantic model for validation
        """
        if not name.replace("_", "").isalnum():
            raise ValueError(f"Invalid tool name: {name}")

        tool = ToolDefinition(
            name=name,
            description=description,
            schema=schema,
            handler=handler,
            input_model=input_model,
        )

        self.tools[name] = tool
        logger.info(f"📝 Registered tool: {name}")

    async def execute(
        self,
        name: str,
        args: dict,
        ctx: ToolContext,
    ) -> dict:
        """
        Execute a tool by name with arguments.
        
        Args:
            name: Tool name
            args: Arguments dict
            ctx: Tool context
            
        Returns:
            {"result": ..., "success": True} or {"error": ..., "success": False}
        """
        if name not in self.tools:
            error_msg = f"Tool not found: {name}"
            logger.error(error_msg)
            return {
                "error": error_msg,
                "success": False,
            }

        tool = self.tools[name]
        return await tool.validate_and_execute(args, ctx)

    def get_gemini_tool_definitions(self) -> list[dict]:
        """
        Get all tools in Gemini function calling format.
        
        Returns:
            List of tool definitions compatible with Gemini API
        """
        return [tool.to_gemini_format() for tool in self.tools.values()]

    def list_tools(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self.tools.keys())

    def get_tool_description(self, name: str) -> Optional[str]:
        """Get tool description by name."""
        tool = self.tools.get(name)
        return tool.description if tool else None

    def __repr__(self) -> str:
        tools_str = ", ".join(self.list_tools())
        return f"ToolRegistry({len(self.tools)} tools: [{tools_str}])"


# Global registry instance
_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the global registry (used for testing)."""
    global _registry
    _registry = None
