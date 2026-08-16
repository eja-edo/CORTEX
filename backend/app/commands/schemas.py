"""
Command schemas for Cortex.

Commands represent validated, permission-checked operations.
AI never touches DB directly - only through CommandRegistry.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.ids import uuid7


class PermissionScope(str, Enum):
    """Permission level required to execute a command."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class CommandStatus(str, Enum):
    """Command execution status."""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERTED = "reverted"


class Command(BaseModel):
    """
    Command envelope.

    Format: {domain}.{action}
    Examples:
      - note.create
      - schedule.update
      - action.revert

    Flow:
      Tool handler → Command → CommandRegistry → Permission check → Execute → Audit
    """
    command_id: str = Field(default_factory=lambda: str(uuid7()))
    command_name: str = Field(..., description="Command name: domain.action")
    args: dict[str, Any] = Field(default_factory=dict, description="Validated arguments")

    # Context
    requested_by: UUID = Field(..., description="User ID (NEVER from LLM)")
    workspace_id: Optional[UUID] = Field(None, description="Workspace context")
    conversation_id: Optional[UUID] = Field(None, description="Conversation context")

    # Permission & Audit
    permission_scope: PermissionScope = Field(default=PermissionScope.WRITE)
    source: str = Field(default="AI", description="Command source: AI, API, Workflow, System")
    correlation_id: Optional[str] = Field(None, description="Request trace ID")

    # Versioning
    schema_version: str = Field(default="1.0.0", description="Command schema version")

    # Execution tracking (populated by CommandRegistry)
    status: CommandStatus = Field(default=CommandStatus.PENDING)
    executed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None

    # Undo support
    revertable: bool = Field(default=False)
    snapshot_id: Optional[str] = Field(None, description="ActionSnapshot ID for revert")


class CommandResult(BaseModel):
    """
    Result of command execution.

    Returned by CommandRegistry.execute().
    """
    command_id: str
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    # Audit trail
    action_id: Optional[str] = Field(None, description="Snapshot ID for revertable commands")
    duration_ms: int
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Revert hint
    revert_hint: Optional[str] = Field(None, description="Human-readable revert instruction")
