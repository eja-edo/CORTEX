from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum
from uuid import UUID


class WorkflowStatusEnum(str, Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    archived = "archived"


class TriggerTypeEnum(str, Enum):
    internal_event = "internal_event"
    webhook = "webhook"
    schedule = "schedule"
    manual = "manual"


class NodePosition(BaseModel):
    x: float
    y: float


class WorkflowNode(BaseModel):
    id: str
    type: str
    position: NodePosition
    data: dict[str, Any]


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    source_handle: Optional[str] = None
    target_handle: Optional[str] = None


class WorkflowDefinitionSchema(BaseModel):
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    variables: dict[str, Any] = {}


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    workspace_id: Optional[UUID] = None
    trigger_type: TriggerTypeEnum
    trigger_config: dict[str, Any] = {}
    definition: WorkflowDefinitionSchema


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[WorkflowStatusEnum] = None
    trigger_config: Optional[dict[str, Any]] = None
    definition: Optional[WorkflowDefinitionSchema] = None


class WorkflowConflict(BaseModel):
    """A duplicate-delivery risk (Milestone A3) — see
    app/services/workflow_conflicts.py. Informational: never blocks a save
    or an activation, just names the overlap so it isn't silent."""
    kind: str  # "backend_direct" | "workflow"
    event_type: str
    action_type: str
    message: str
    conflicting_workflow_id: Optional[UUID] = None
    conflicting_workflow_name: Optional[str] = None


class WorkflowResponse(BaseModel):
    id: UUID
    user_id: UUID
    workspace_id: Optional[UUID]
    name: str
    description: Optional[str]
    status: WorkflowStatusEnum
    version: int
    trigger_type: TriggerTypeEnum
    trigger_config: dict[str, Any]
    definition: dict[str, Any]
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # None = not computed for this response (most endpoints). A list
    # (possibly empty) = computed — currently only `activate_workflow` and
    # `GET /workflows/{id}/conflicts` populate this; see A3.
    warnings: Optional[list[WorkflowConflict]] = None

    model_config = {"from_attributes": True}


class WorkflowListResponse(BaseModel):
    items: list[WorkflowResponse]
    total: int
    page: int
    page_size: int


class WorkflowTriggerCreate(BaseModel):
    trigger_type: TriggerTypeEnum
    trigger_config: dict[str, Any] = {}


class WorkflowTriggerUpdate(BaseModel):
    trigger_config: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class WorkflowTriggerResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    trigger_type: TriggerTypeEnum
    trigger_config: dict[str, Any]
    is_active: bool
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
