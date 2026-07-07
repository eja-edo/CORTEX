import uuid
import enum

from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, JSON, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

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


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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


class WorkflowTriggerWebhook(Base):
    __tablename__ = "workflow_trigger_webhooks"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_definitions.id"), nullable=False)
    webhook_path = Column(String(255), nullable=False, unique=True)
    secret_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
