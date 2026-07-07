from pydantic import BaseModel, UUID4
from typing import Optional, Any
from datetime import datetime
from enum import Enum


class ExecutionStatusEnum(str, Enum):
    pending = "pending"
    running = "running"
    waiting = "waiting"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timed_out = "timed_out"


class StepExecutionResponse(BaseModel):
    id: UUID4
    node_id: str
    node_type: str
    status: ExecutionStatusEnum
    input_data: Optional[dict[str, Any]]
    output_data: Optional[dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ExecutionResponse(BaseModel):
    id: UUID4
    workflow_id: UUID4
    status: ExecutionStatusEnum
    temporal_workflow_id: Optional[str]
    trigger_data: Optional[dict[str, Any]]
    output: Optional[dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    steps: list[StepExecutionResponse] = []

    model_config = {"from_attributes": True}


class ManualTriggerRequest(BaseModel):
    input_data: dict[str, Any] = {}


class ExecutionListResponse(BaseModel):
    items: list[ExecutionResponse]
    total: int
    page: int
    page_size: int
