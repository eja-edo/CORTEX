# PHASE 2 — BACKEND CORE
## Workflow CRUD API + Trigger Engine + Action Engine

> **Thời gian**: Tuần 3–4 (10 ngày làm việc)  
> **Prerequisite**: Phase 1 hoàn thành — Temporal chạy được, DB schema có sẵn  
> **Mục tiêu**: Có thể tạo/đọc/sửa/xóa workflow qua API, trigger gửi được event, action thực thi được  
> **Output cuối phase**: API endpoints hoạt động đầy đủ, test được bằng curl hoặc Postman

---

## 1. Tổng quan công việc Phase 2

```
Tuần 3                              Tuần 4
─────────────────────────────────── ───────────────────────────────────
Day 1-2: Pydantic schemas           Day 6-7: Trigger Engine
Day 3-4: Workflow CRUD API          Day 8-9: Action Engine (plugin system)
Day 5:   Auth middleware            Day 10: Integration test toàn bộ API
```

---

## 2. Pydantic Schemas (Request/Response)

**`app/schemas/workflow.py`**

```python
from pydantic import BaseModel, Field, UUID4
from typing import Optional, Any
from datetime import datetime
from enum import Enum

# --- Enums ---
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

# --- Node/Edge schemas (React Flow format) ---
class NodePosition(BaseModel):
    x: float
    y: float

class WorkflowNode(BaseModel):
    id: str                    # React Flow node ID (ví dụ: "node-1")
    type: str                  # Node type (ví dụ: "trigger.internal_event", "action.create_note")
    position: NodePosition
    data: dict[str, Any]       # Config của node này (khác nhau theo type)

class WorkflowEdge(BaseModel):
    id: str
    source: str                # Node ID nguồn
    target: str                # Node ID đích
    source_handle: Optional[str] = None   # Cho conditional branching
    target_handle: Optional[str] = None

class WorkflowDefinitionSchema(BaseModel):
    """Toàn bộ definition của workflow — đây là gì React Flow lưu"""
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    variables: dict[str, Any] = {}  # Global variables của workflow

# --- Trigger config ---
class InternalEventTriggerConfig(BaseModel):
    event: str                 # Ví dụ: "note.created", "schedule.created", "asset.uploaded"
    filters: dict[str, Any] = {}   # Điều kiện lọc event

class WebhookTriggerConfig(BaseModel):
    method: str = "POST"
    headers: dict[str, str] = {}   # Headers bắt buộc

class ScheduleTriggerConfig(BaseModel):
    cron: str                  # Ví dụ: "0 9 * * MON"
    timezone: str = "Asia/Ho_Chi_Minh"

# --- CRUD schemas ---
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
    webhook_url: Optional[str] = None  # Chỉ có khi trigger_type = webhook
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class WorkflowListResponse(BaseModel):
    items: list[WorkflowResponse]
    total: int
    page: int
    page_size: int
```

**`app/schemas/execution.py`**

```python
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

    class Config:
        from_attributes = True

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

    class Config:
        from_attributes = True

class ManualTriggerRequest(BaseModel):
    """Dùng để trigger workflow thủ công"""
    input_data: dict[str, Any] = {}
```

---

## 3. Auth Middleware

Workflow service cần xác thực user. Chiến lược: **dùng lại JWT secret của Cortex backend** — decode JWT token và lấy user_id từ đó.

**`app/core/security.py`**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from app.config import settings
from dataclasses import dataclass

security = HTTPBearer()

@dataclass
class CurrentUser:
    user_id: str
    email: str

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CurrentUser:
    """
    Dependency để xác thực user từ JWT token của Cortex.
    Dùng cùng JWT_SECRET_KEY với Cortex backend.
    """
    token = credentials.credentials
    
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        user_id: str = payload.get("sub")
        email: str = payload.get("email", "")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user_id"
            )
        
        return CurrentUser(user_id=user_id, email=email)
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )
```

---

## 4. Workflow CRUD API

**`app/api/v1/workflows.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.core.security import get_current_user, CurrentUser
from app.models.workflow import WorkflowDefinition, WorkflowStatus, WorkflowTriggerWebhook
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse, WorkflowListResponse
)
import uuid
import secrets
import hashlib

router = APIRouter()

@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    workspace_id: str | None = Query(None),
    status: str | None = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lấy danh sách workflow của user hiện tại"""
    query = select(WorkflowDefinition).where(
        WorkflowDefinition.user_id == current_user.user_id,
        WorkflowDefinition.is_deleted == False
    )
    
    if workspace_id:
        query = query.where(WorkflowDefinition.workspace_id == workspace_id)
    if status:
        query = query.where(WorkflowDefinition.status == status)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(WorkflowDefinition.created_at.desc())
    
    result = await db.execute(query)
    workflows = result.scalars().all()
    
    return WorkflowListResponse(
        items=[_to_response(wf) for wf in workflows],
        total=total,
        page=page,
        page_size=page_size
    )

@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    data: WorkflowCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Tạo workflow mới"""
    workflow = WorkflowDefinition(
        user_id=current_user.user_id,
        workspace_id=data.workspace_id,
        name=data.name,
        description=data.description,
        trigger_type=data.trigger_type.value,
        trigger_config=data.trigger_config,
        definition=data.definition.model_dump(),
        status=WorkflowStatus.DRAFT,
    )
    
    db.add(workflow)
    await db.flush()  # Để lấy workflow.id
    
    # Nếu trigger type là webhook, tạo webhook record
    webhook_url = None
    if data.trigger_type == "webhook":
        webhook_secret = secrets.token_urlsafe(32)
        webhook_path = str(uuid.uuid4()).replace("-", "")
        
        webhook = WorkflowTriggerWebhook(
            workflow_id=workflow.id,
            webhook_path=webhook_path,
            secret_hash=hashlib.sha256(webhook_secret.encode()).hexdigest(),
        )
        db.add(webhook)
        workflow.webhook_secret = webhook_secret
        webhook_url = f"/api/v1/webhooks/{webhook_path}"
    
    await db.commit()
    
    response = _to_response(workflow)
    response.webhook_url = webhook_url
    return response

@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lấy chi tiết một workflow"""
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    return _to_response(workflow)

@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    data: WorkflowUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cập nhật workflow — chỉ DRAFT mới được sửa definition"""
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    
    # Nếu workflow đang ACTIVE và thay đổi definition → tăng version
    if workflow.status == WorkflowStatus.ACTIVE and data.definition:
        workflow.version += 1
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "definition" and value:
            setattr(workflow, field, value.model_dump() if hasattr(value, 'model_dump') else value)
        elif value is not None:
            setattr(workflow, field, value)
    
    await db.commit()
    return _to_response(workflow)

@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Soft delete workflow"""
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    workflow.is_deleted = True
    workflow.status = WorkflowStatus.ARCHIVED
    await db.commit()

@router.post("/{workflow_id}/activate", response_model=WorkflowResponse)
async def activate_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Activate workflow — bắt đầu lắng nghe triggers"""
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    
    # Validate: workflow phải có ít nhất 1 node trigger và 1 action
    definition = workflow.definition
    nodes = definition.get("nodes", [])
    trigger_nodes = [n for n in nodes if n.get("type", "").startswith("trigger.")]
    action_nodes = [n for n in nodes if n.get("type", "").startswith("action.")]
    
    if not trigger_nodes:
        raise HTTPException(status_code=400, detail="Workflow must have at least one trigger node")
    if not action_nodes:
        raise HTTPException(status_code=400, detail="Workflow must have at least one action node")
    
    workflow.status = WorkflowStatus.ACTIVE
    await db.commit()
    return _to_response(workflow)

@router.post("/{workflow_id}/pause", response_model=WorkflowResponse)
async def pause_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Pause workflow — tạm dừng nhận triggers mới"""
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    workflow.status = WorkflowStatus.PAUSED
    await db.commit()
    return _to_response(workflow)

# --- Helper functions ---
async def _get_workflow_or_404(workflow_id: str, user_id: str, db: AsyncSession) -> WorkflowDefinition:
    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.user_id == user_id,
            WorkflowDefinition.is_deleted == False
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow

def _to_response(wf: WorkflowDefinition) -> WorkflowResponse:
    return WorkflowResponse(
        id=wf.id,
        user_id=wf.user_id,
        workspace_id=wf.workspace_id,
        name=wf.name,
        description=wf.description,
        status=wf.status.value if hasattr(wf.status, 'value') else wf.status,
        version=wf.version,
        trigger_type=wf.trigger_type.value if hasattr(wf.trigger_type, 'value') else wf.trigger_type,
        trigger_config=wf.trigger_config,
        definition=wf.definition,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )
```

---

## 5. Trigger Engine

Trigger Engine lắng nghe các sự kiện và khởi động Workflow Instances tương ứng.

### 5.1 Internal Event Triggers (từ Cortex)

Cortex backend sẽ publish events lên Redis khi có sự kiện xảy ra (note tạo, schedule tạo...). Workflow service lắng nghe Redis channel này.

**`app/triggers/internal_event_listener.py`**

```python
"""
Lắng nghe events từ Cortex backend qua Redis Pub/Sub.
Chạy như một background task khi workflow_service start.
"""
import asyncio
import json
import redis.asyncio as aioredis
from sqlalchemy import select
from app.config import settings
from app.models.workflow import WorkflowDefinition, WorkflowStatus, TriggerType
from app.database import AsyncSessionLocal

REDIS_CHANNEL = "cortex:workflow:events"

SUPPORTED_EVENTS = [
    "note.created",
    "note.updated",
    "note.deleted",
    "schedule.created",
    "schedule.updated",
    "schedule.completed",
    "asset.uploaded",
    "asset.processed",
]

async def start_internal_event_listener():
    """
    Background task: lắng nghe Redis, match với active workflows, trigger instances.
    """
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(REDIS_CHANNEL)
    
    print(f"[TriggerEngine] Listening on Redis channel: {REDIS_CHANNEL}")
    
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        
        try:
            event_data = json.loads(message["data"])
            event_type = event_data.get("event")
            
            if event_type not in SUPPORTED_EVENTS:
                continue
            
            await _handle_event(event_type, event_data)
        
        except Exception as e:
            print(f"[TriggerEngine] Error handling event: {e}")

async def _handle_event(event_type: str, event_data: dict):
    """Tìm workflow phù hợp và trigger instance"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkflowDefinition).where(
                WorkflowDefinition.status == WorkflowStatus.ACTIVE,
                WorkflowDefinition.trigger_type == TriggerType.INTERNAL_EVENT,
                WorkflowDefinition.is_deleted == False
            )
        )
        workflows = result.scalars().all()
        
        for workflow in workflows:
            trigger_config = workflow.trigger_config
            configured_event = trigger_config.get("event")
            
            if configured_event != event_type:
                continue
            
            # Check filters
            filters = trigger_config.get("filters", {})
            if not _matches_filters(event_data, filters):
                continue
            
            # Trigger workflow instance (sẽ implement đầy đủ ở Phase 3)
            await _trigger_workflow_instance(workflow, event_data)
            print(f"[TriggerEngine] Triggered workflow {workflow.id} for event {event_type}")

def _matches_filters(event_data: dict, filters: dict) -> bool:
    """Kiểm tra event data có khớp với filters không"""
    for key, value in filters.items():
        if event_data.get(key) != value:
            return False
    return True

async def _trigger_workflow_instance(workflow: WorkflowDefinition, trigger_data: dict):
    """
    Placeholder — sẽ được implement đầy đủ ở Phase 3 khi có Temporal integration.
    Ở Phase 2, chỉ log ra.
    """
    print(f"[TriggerEngine] Would trigger workflow {workflow.name} with data: {trigger_data}")
```

### 5.2 Webhook Trigger Endpoint

**`app/api/v1/webhooks.py`** (file mới, thêm vào router trong main.py)

```python
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.workflow import WorkflowTriggerWebhook, WorkflowDefinition, WorkflowStatus
import hashlib
import json

router = APIRouter()

@router.post("/{webhook_path}")
async def receive_webhook(
    webhook_path: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Nhận webhook từ external services.
    URL: POST /api/v1/webhooks/{webhook_path}
    """
    # Tìm webhook config
    result = await db.execute(
        select(WorkflowTriggerWebhook).where(
            WorkflowTriggerWebhook.webhook_path == webhook_path,
            WorkflowTriggerWebhook.is_active == True
        )
    )
    webhook = result.scalar_one_or_none()
    
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    # Verify secret nếu có header X-Webhook-Secret
    secret_header = request.headers.get("X-Webhook-Secret")
    if secret_header:
        provided_hash = hashlib.sha256(secret_header.encode()).hexdigest()
        if provided_hash != webhook.secret_hash:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
    
    # Lấy workflow
    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == webhook.workflow_id,
            WorkflowDefinition.status == WorkflowStatus.ACTIVE
        )
    )
    workflow = result.scalar_one_or_none()
    
    if not workflow:
        raise HTTPException(status_code=409, detail="Workflow is not active")
    
    # Parse body
    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {"raw": body.decode()}
    
    trigger_data = {
        "event": "webhook.received",
        "webhook_path": webhook_path,
        "headers": dict(request.headers),
        "payload": payload,
    }
    
    # Trigger workflow (đầy đủ ở Phase 3)
    print(f"[WebhookTrigger] Received webhook for workflow {workflow.id}")
    
    return {"status": "accepted", "workflow_id": str(workflow.id)}
```

---

## 6. Action Engine — Plugin System

Action Engine cho phép thêm action mới dễ dàng mà không cần sửa core logic.

**`app/actions/base.py`**

```python
from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass

@dataclass
class ActionContext:
    """Context được truyền vào mỗi action khi thực thi"""
    user_id: str
    workflow_id: str
    instance_id: str
    node_id: str
    trigger_data: dict[str, Any]
    previous_outputs: dict[str, Any]  # Outputs của các steps trước

@dataclass
class ActionResult:
    success: bool
    output: dict[str, Any]
    error: str | None = None

class BaseAction(ABC):
    """
    Base class cho tất cả actions.
    Mỗi action mới phải kế thừa class này.
    """
    
    @property
    @abstractmethod
    def action_type(self) -> str:
        """
        Unique identifier cho action này.
        Phải khớp với node type trong React Flow.
        Ví dụ: "action.create_note", "action.send_notification"
        """
        pass
    
    @property
    @abstractmethod
    def display_name(self) -> str:
        """Tên hiển thị trong UI"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Mô tả ngắn cho UI"""
        pass
    
    @property
    def config_schema(self) -> dict:
        """JSON Schema cho config của action này (dùng trong UI form)"""
        return {}
    
    @abstractmethod
    async def execute(self, config: dict[str, Any], context: ActionContext) -> ActionResult:
        """
        Thực thi action.
        config: cấu hình từ node data trong React Flow
        context: runtime context
        """
        pass
    
    def resolve_template(self, template: str, context: ActionContext) -> str:
        """
        Helper để resolve template variables.
        Ví dụ: "Note từ {{trigger.note_id}}" → "Note từ abc-123"
        """
        import re
        def replace_var(match):
            path = match.group(1).strip()
            parts = path.split(".")
            
            if parts[0] == "trigger":
                value = context.trigger_data
                for part in parts[1:]:
                    value = value.get(part, "") if isinstance(value, dict) else ""
            elif parts[0] == "steps":
                step_id = parts[1]
                value = context.previous_outputs.get(step_id, {})
                for part in parts[2:]:
                    value = value.get(part, "") if isinstance(value, dict) else ""
            else:
                value = ""
            
            return str(value)
        
        return re.sub(r'\{\{(.+?)\}\}', replace_var, template)
```

**`app/actions/registry.py`**

```python
from app.actions.base import BaseAction

class ActionRegistry:
    """
    Registry lưu tất cả actions đã được đăng ký.
    Singleton pattern.
    """
    _instance = None
    _actions: dict[str, BaseAction] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def register(self, action: BaseAction):
        self._actions[action.action_type] = action
        print(f"[ActionRegistry] Registered action: {action.action_type}")
    
    def get(self, action_type: str) -> BaseAction | None:
        return self._actions.get(action_type)
    
    def list_all(self) -> list[dict]:
        """Trả về danh sách actions cho UI"""
        return [
            {
                "type": action.action_type,
                "display_name": action.display_name,
                "description": action.description,
                "config_schema": action.config_schema,
            }
            for action in self._actions.values()
        ]

# Singleton instance
action_registry = ActionRegistry()
```

**`app/actions/builtin/create_note.py`** — Action đầu tiên

```python
from app.actions.base import BaseAction, ActionContext, ActionResult
import httpx
from app.config import settings

class CreateNoteAction(BaseAction):
    
    @property
    def action_type(self) -> str:
        return "action.create_note"
    
    @property
    def display_name(self) -> str:
        return "Tạo Note"
    
    @property
    def description(self) -> str:
        return "Tạo một note mới trong Cortex"
    
    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "title": "Tiêu đề",
                    "description": "Hỗ trợ template: {{trigger.event}}"
                },
                "content": {
                    "type": "string",
                    "title": "Nội dung",
                    "description": "Hỗ trợ template variables"
                },
                "workspace_id": {
                    "type": "string",
                    "title": "Workspace ID",
                    "description": "Để trống = personal workspace"
                }
            },
            "required": ["title"]
        }
    
    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        title = self.resolve_template(config.get("title", "Untitled"), context)
        content = self.resolve_template(config.get("content", ""), context)
        workspace_id = config.get("workspace_id")
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{settings.cortex_backend_url}/api/notes",
                    json={
                        "title": title,
                        "content": content,
                        "workspace_id": workspace_id,
                    },
                    headers={
                        "X-Internal-API-Key": settings.cortex_internal_api_key,
                        "X-User-ID": context.user_id,
                    },
                    timeout=10.0
                )
                response.raise_for_status()
                note_data = response.json()
                
                return ActionResult(
                    success=True,
                    output={"note_id": note_data.get("id"), "title": title}
                )
            
            except httpx.HTTPError as e:
                return ActionResult(
                    success=False,
                    output={},
                    error=f"Failed to create note: {str(e)}"
                )
```

**`app/actions/builtin/send_notification.py`**

```python
from app.actions.base import BaseAction, ActionContext, ActionResult
import httpx
from app.config import settings

class SendNotificationAction(BaseAction):
    
    @property
    def action_type(self) -> str:
        return "action.send_notification"
    
    @property
    def display_name(self) -> str:
        return "Gửi Notification"
    
    @property
    def description(self) -> str:
        return "Gửi thông báo đến user trong Cortex"
    
    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "title": "Tiêu đề thông báo"},
                "message": {"type": "string", "title": "Nội dung thông báo"},
                "type": {
                    "type": "string",
                    "title": "Loại",
                    "enum": ["info", "success", "warning", "error"],
                    "default": "info"
                }
            },
            "required": ["title", "message"]
        }
    
    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        title = self.resolve_template(config.get("title", ""), context)
        message = self.resolve_template(config.get("message", ""), context)
        notif_type = config.get("type", "info")
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{settings.cortex_backend_url}/api/notifications/internal",
                    json={
                        "user_id": context.user_id,
                        "title": title,
                        "message": message,
                        "type": notif_type,
                        "source": "workflow",
                        "source_id": context.workflow_id,
                    },
                    headers={"X-Internal-API-Key": settings.cortex_internal_api_key},
                    timeout=5.0
                )
                response.raise_for_status()
                return ActionResult(success=True, output={"sent": True})
            
            except httpx.HTTPError as e:
                return ActionResult(success=False, output={}, error=str(e))
```

**`app/actions/__init__.py`** — Đăng ký tất cả actions

```python
from app.actions.registry import action_registry
from app.actions.builtin.create_note import CreateNoteAction
from app.actions.builtin.send_notification import SendNotificationAction

# Đăng ký built-in actions
action_registry.register(CreateNoteAction())
action_registry.register(SendNotificationAction())

# Phase 5 sẽ thêm nhiều actions hơn
```

---

## 7. API cho Action Registry (cho frontend dùng)

Thêm endpoint để frontend biết có những actions nào:

**`app/api/v1/actions.py`**

```python
from fastapi import APIRouter, Depends
from app.core.security import get_current_user, CurrentUser
from app.actions.registry import action_registry

router = APIRouter()

@router.get("")
async def list_actions(current_user: CurrentUser = Depends(get_current_user)):
    """Trả về danh sách tất cả actions có thể dùng trong workflow builder"""
    return {
        "actions": action_registry.list_all(),
        "triggers": [
            {
                "type": "trigger.internal_event",
                "display_name": "Cortex Event",
                "description": "Trigger khi có sự kiện trong Cortex",
                "config_schema": {
                    "properties": {
                        "event": {
                            "type": "string",
                            "enum": [
                                "note.created", "note.updated", "note.deleted",
                                "schedule.created", "schedule.updated", "schedule.completed",
                                "asset.uploaded", "asset.processed"
                            ]
                        },
                        "filters": {"type": "object"}
                    }
                }
            },
            {
                "type": "trigger.webhook",
                "display_name": "Webhook",
                "description": "Trigger khi nhận HTTP webhook từ bên ngoài",
                "config_schema": {}
            },
            {
                "type": "trigger.manual",
                "display_name": "Manual",
                "description": "Trigger thủ công bởi user",
                "config_schema": {}
            }
        ]
    }
```

---

## 8. Verification Checklist — Cuối Phase 2

### API hoạt động

- [ ] `POST /api/v1/workflows` tạo workflow thành công, trả về 201
- [ ] `GET /api/v1/workflows` trả về danh sách có phân trang
- [ ] `GET /api/v1/workflows/{id}` trả về chi tiết
- [ ] `PATCH /api/v1/workflows/{id}` cập nhật thành công
- [ ] `DELETE /api/v1/workflows/{id}` soft-delete (is_deleted=true)
- [ ] `POST /api/v1/workflows/{id}/activate` chuyển status sang "active"
- [ ] `POST /api/v1/workflows/{id}/pause` chuyển status sang "paused"
- [ ] `POST /api/v1/webhooks/{path}` nhận webhook và log ra

### Auth

- [ ] Endpoint không có JWT trả về 401
- [ ] JWT của Cortex được decode đúng, lấy được user_id
- [ ] User không thể truy cập workflow của user khác (trả về 404)

### Action Registry

- [ ] `GET /api/v1/actions` trả về danh sách actions và triggers
- [ ] `CreateNoteAction` và `SendNotificationAction` được đăng ký

### Trigger Engine

- [ ] Internal event listener start không có error
- [ ] Khi publish event vào Redis channel `cortex:workflow:events`, log hiện ra đúng workflow

---

## 9. Cortex Backend — Những gì cần thêm

Phase 2 yêu cầu Cortex backend publish events lên Redis. Thêm vào Cortex backend (không phải workflow_service):

```python
# Thêm vào backend/app/services/redis/event_publisher.py (file mới)

import json
import redis.asyncio as aioredis

WORKFLOW_EVENT_CHANNEL = "cortex:workflow:events"

async def publish_workflow_event(redis_client, event_type: str, data: dict):
    """
    Gọi hàm này sau mỗi operation quan trọng trong Cortex backend.
    Ví dụ: sau khi tạo note thành công.
    """
    payload = json.dumps({
        "event": event_type,
        **data
    })
    await redis_client.publish(WORKFLOW_EVENT_CHANNEL, payload)
```

Thêm vào cuối `NoteService.create_note()`:

```python
await publish_workflow_event(redis_client, "note.created", {
    "note_id": str(note.id),
    "user_id": str(note.user_id),
    "workspace_id": str(note.workspace_id) if note.workspace_id else None,
    "title": note.title,
})
```
