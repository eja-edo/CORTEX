"""
Event schemas for Cortex Event Bus.

All events in the system follow this unified envelope format.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.ids import uuid7


class EventEnvelope(BaseModel):
    """
    Unified event envelope for all events in Cortex.

    Format: domain.entity.action
    Examples:
      - schedule.reminder.due
      - note.created
      - tool.executed

    Design principles:
    - Self-contained: All metadata in envelope
    - Traceable: correlation_id for request tracing
    - Versioned: schema_version for evolution
    - Timestamped: UTC timestamp for ordering
    """

    event_id: str = Field(default_factory=lambda: str(uuid7()))
    type: str = Field(..., description="Event type: domain.entity.action")
    source: str = Field(..., description="Event source service/component")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = Field(None, description="Request trace ID")
    user_id: Optional[UUID] = Field(None, description="User who triggered event")
    workspace_id: Optional[UUID] = Field(None, description="Workspace context")
    conversation_id: Optional[UUID] = Field(None, description="Conversation context")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event-specific data")
    version: str = Field(default="1.0.0", description="Event schema version")

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-safe dict for Redis/transport."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope":
        """Parse from a dict decoded off Redis/JSON. Pydantic coerces
        ISO timestamp strings and UUID strings back to native types."""
        return cls(**data)
