"""Tool registry for managing agent tools and their execution."""

import json
import os
import re
from pathlib import Path
from typing import Callable, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, ValidationError

from app.ai.agents.provider_types import ToolDefinition as ProviderToolDef
from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Structured logging config ──────────────────────────────────────────────

TOOL_LOG_DIR = Path(os.getenv("TOOL_LOG_DIR", "logs"))
TOOL_LOG_FILE = TOOL_LOG_DIR / "tool-executions.jsonl"

SENSITIVE_ARG_KEYS = re.compile(
    r"^(api[_-]?key|password|secret|token|authorization|bearer|auth|private[_-]?key)$",
    re.IGNORECASE,
)
CONTENT_ARG_KEYS = frozenset({"content"})
TRUNCATE_LENGTH = 500
MAX_SANITIZE_DEPTH = 5


def _sanitize_args(args: dict) -> dict:
    """Return a sanitised copy of tool arguments suitable for logging."""
    def _walk(obj: Any, depth: int = 0) -> Any:
        if depth > MAX_SANITIZE_DEPTH:
            return "[MAX_DEPTH]"
        if isinstance(obj, str):
            if obj == "":
                return obj
            if len(obj) > TRUNCATE_LENGTH:
                return obj[:TRUNCATE_LENGTH] + "..."
            return obj
        if not isinstance(obj, dict):
            return obj

        cleaned: dict = {}
        for key, value in obj.items():
            low_key = key.lower()
            if SENSITIVE_ARG_KEYS.match(key):
                cleaned[key] = "[REDACTED]"
            elif low_key in CONTENT_ARG_KEYS:
                cleaned[key] = "[REDACTED]"
            elif isinstance(value, list):
                cleaned[key] = [_walk(v, depth + 1) for v in value]
            else:
                cleaned[key] = _walk(value, depth + 1)
        return cleaned

    return _walk(args)  # type: ignore[return-value]


def _write_tool_log(
    *,
    tool_name: str,
    args: dict,
    user_id: str,
    conversation_id: str | None,
    duration_ms: float,
    success: bool,
    error: str | None = None,
) -> None:
    """Append a structured JSON line to the tool log file."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_name": tool_name,
        "args": _sanitize_args(args),
        "user_id": str(user_id),
        "conversation_id": str(conversation_id) if conversation_id else None,
        "duration_ms": round(duration_ms, 1),
        "success": success,
        "error": error,
    }
    try:
        TOOL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOOL_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass  # non-fatal; logging should never break execution


# ── Tool execution logging (legacy Python logger + structured JSONL) ────────

def _log_execution(
    *,
    tool_name: str,
    args: dict,
    ctx: ToolContext,
    duration_ms: float,
    success: bool,
    error: str | None = None,
    exc_info: bool = False,
) -> None:
    """Log tool execution through both the Python logger and the JSONL file."""
    level = logger.error if error else logger.info
    log_msg = (
        f"event=tool_execution "
        f"tool_name={tool_name} "
        f"success={'true' if success else 'false'} "
        f"elapsed_ms={duration_ms:.1f} "
        f"user={ctx.user_id}"
    )
    if error:
        log_msg += f" error={error}"

    log_fn = lambda: level(log_msg, exc_info=exc_info)  # noqa: E731
    log_fn()

    conv_id = str(ctx.conversation_id) if ctx.conversation_id else None
    _write_tool_log(
        tool_name=tool_name,
        args=args,
        user_id=str(ctx.user_id),
        conversation_id=conv_id,
        duration_ms=duration_ms,
        success=success,
        error=error,
    )


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

    def to_provider_format(self) -> ProviderToolDef:
        """Convert to provider-agnostic ToolDefinition format."""
        return ProviderToolDef(
            name=self.name,
            description=self.description,
            parameters=self.schema,
        )

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
                    duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                    _log_execution(
                        tool_name=self.name,
                        args=args,
                        ctx=ctx,
                        duration_ms=duration_ms,
                        success=False,
                        error=error_msg,
                    )
                    return {
                        "error": error_msg,
                        "success": False,
                    }

            # Execute handler
            result = await self.handler(args, ctx)

            duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            _log_execution(
                tool_name=self.name,
                args=args,
                ctx=ctx,
                duration_ms=duration_ms,
                success=True,
            )

            return {
                "result": result,
                "success": True,
            }

        except Exception as exc:
            duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            error_msg = str(exc)

            _log_execution(
                tool_name=self.name,
                args=args,
                ctx=ctx,
                duration_ms=duration_ms,
                success=False,
                error=error_msg,
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
            _log_execution(
                tool_name=name,
                args=args,
                ctx=ctx,
                duration_ms=0.0,
                success=False,
                error=error_msg,
            )
            return {
                "error": error_msg,
                "success": False,
            }

        tool = self.tools[name]
        return await tool.validate_and_execute(args, ctx)

    def get_provider_tools(self) -> list[ProviderToolDef]:
        """Get all tools in provider-agnostic format for the new provider system."""
        return [tool.to_provider_format() for tool in self.tools.values()]

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
