import uuid
import enum

from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, JSON, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.ids import uuid7
from app.database import Base


class WorkflowStatus(enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class TriggerType(enum.Enum):
    INTERNAL_EVENT = "internal_event"
    WEBHOOK = "webhook"
    SCHEDULE = "schedule"
    MANUAL = "manual"


# Milestone 4.0: system workflows (Cortex's own built-in behavior) are real
# rows in workflow_definitions, owned by this sentinel user instead of being
# copied per workspace. See app/services/system_workflows.py.
SYSTEM_WORKFLOW_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    status = Column(Enum(WorkflowStatus), nullable=False, default=WorkflowStatus.DRAFT)
    version = Column(Integer, nullable=False, default=1)

    trigger_type = Column(Enum(TriggerType), nullable=False)
    trigger_config = Column(JSON, nullable=False, default=dict)
    definition = Column(JSON, nullable=False, default=dict)

    webhook_secret = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)


class WorkflowTrigger(Base):
    """Supplementary trigger on a workflow (multi-trigger support). The
    workflow's own trigger_type/trigger_config columns remain the "primary"
    trigger (unchanged, zero migration for existing single-trigger
    workflows) — a row here is an *additional* trigger, independently
    matched/activated/torn down. See app/api/v1/workflows.py's
    _activate_schedule_trigger and app/triggers/internal_event_listener.py."""
    __tablename__ = "workflow_triggers"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_definitions.id"), nullable=False, index=True)
    trigger_type = Column(Enum(TriggerType), nullable=False)
    trigger_config = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class WorkflowTriggerWebhook(Base):
    __tablename__ = "workflow_trigger_webhooks"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_definitions.id"), nullable=False)
    # NULL = webhook belongs to the workflow's primary trigger (unchanged
    # behavior). Set = belongs to a specific supplementary WorkflowTrigger
    # row, so deleting/deactivating that one trigger only touches its own
    # webhook, not the primary's or another supplementary one's.
    trigger_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_triggers.id"), nullable=True)
    webhook_path = Column(String(255), nullable=False, unique=True)
    secret_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class WorkspaceWorkflowSetting(Base):
    """Per-workspace override of a system workflow (Milestone 4.0 M1). No
    row = default-on, not forked. See app/services/system_workflows.py for
    the resolver that reads this."""
    __tablename__ = "workspace_workflow_settings"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    workspace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_definitions.id"), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    config_overrides = Column(JSON, nullable=False, default=dict)
    forked_workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_definitions.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
