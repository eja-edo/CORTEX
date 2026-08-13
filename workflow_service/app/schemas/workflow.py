from pydantic import BaseModel, Field, UUID4
from typing import Optional, Any
from datetime import datetime
from enum import Enum


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
    workspace_id: Optional[UUID4] = None
    trigger_type: TriggerTypeEnum
    trigger_config: dict[str, Any] = {}
    definition: WorkflowDefinitionSchema


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[WorkflowStatusEnum] = None
    trigger_config: Optional[dict[str, Any]] = None
    definition: Optional[WorkflowDefinitionSchema] = None


class WorkflowResponse(BaseModel):
    id: UUID4
    user_id: UUID4
    workspace_id: Optional[UUID4]
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
    id: UUID4
    workflow_id: UUID4
    trigger_type: TriggerTypeEnum
    trigger_config: dict[str, Any]
    is_active: bool
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
