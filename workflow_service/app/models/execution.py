import uuid
import enum

from sqlalchemy import Column, String, Text, Integer, DateTime, JSON, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ExecutionStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_definitions.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    status = Column(Enum(ExecutionStatus), nullable=False, default=ExecutionStatus.PENDING)

    temporal_workflow_id = Column(String(255), nullable=True)
    temporal_run_id = Column(String(255), nullable=True)

    trigger_data = Column(JSON, nullable=True)

    output = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    steps = relationship(
        "WorkflowStepExecution",
        backref="instance",
        lazy="selectin",
        order_by="WorkflowStepExecution.created_at",
    )


class WorkflowStepExecution(Base):
    __tablename__ = "workflow_step_executions"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_instances.id"), nullable=False, index=True)

    node_id = Column(String(255), nullable=False)
    node_type = Column(String(100), nullable=False)

    status = Column(Enum(ExecutionStatus), nullable=False)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
