# PHASE 3 — TEMPORAL INTEGRATION
## Temporal Workers + Workflow Definitions + State Management

> **Thời gian**: Tuần 5–6 (10 ngày làm việc)  
> **Prerequisite**: Phase 2 hoàn thành — CRUD API + Trigger Engine + Action Registry  
> **Mục tiêu**: Workflow thực sự chạy được trong Temporal, có execution history, có thể pause/resume  
> **Output cuối phase**: Tạo workflow, trigger event → Temporal chạy → log history hiện trong Temporal UI

---

## 1. Tổng quan công việc Phase 3

```
Tuần 5                               Tuần 6
──────────────────────────────────── ────────────────────────────────────
Day 1-2: Temporal Activities         Day 6-7: Execution API + DB sync
Day 3-4: Workflow Definition (Python) Day 8-9: State machine + error handling
Day 5:   Worker setup + startup      Day 10: End-to-end test (trigger → complete)
```

---

## 2. Kiến trúc Temporal trong Cortex

```
workflow_service/
├── app/
│   ├── temporal/
│   │   ├── client.py          ← Temporal Client (Phase 1)
│   │   ├── worker.py          ← Worker startup (Phase 3 - mở rộng)
│   │   ├── workflows/
│   │   │   └── cortex_workflow.py   ← Workflow Definition
│   │   └── activities/
│   │       ├── __init__.py
│   │       ├── execute_action.py    ← Thực thi action
│   │       ├── update_step_status.py ← Cập nhật DB
│   │       └── notify_completion.py  ← Thông báo khi xong
```

### Temporal Concepts cần hiểu

```
Workflow Definition    = Python class với @workflow.defn
                         Mô tả LOGIC (if/else, loop, wait)
                         KHÔNG được có side effects trực tiếp

Activity              = Python function với @activity.defn
                         Thực hiện CÔNG VIỆC thực tế (gọi API, đọc DB)
                         Có thể retry, có timeout

Worker                = Process chạy Workflow Definitions + Activities
                         Lắng nghe Task Queue từ Temporal server

Task Queue            = "cortex-workflow-queue"
                         Workflow và Activity đều dùng chung queue này
```

---

## 3. Activities — Đơn vị công việc thực tế

### 3.1 `app/temporal/activities/execute_action.py`

```python
from temporalio import activity
from dataclasses import dataclass
from typing import Any
from app.actions.registry import action_registry
from app.actions.base import ActionContext, ActionResult

@dataclass
class ExecuteActionInput:
    action_type: str        # Ví dụ: "action.create_note"
    config: dict            # Config từ node data trong React Flow
    user_id: str
    workflow_id: str
    instance_id: str
    node_id: str
    trigger_data: dict
    previous_outputs: dict  # Outputs của steps trước

@activity.defn(name="execute_action")
async def execute_action(input: ExecuteActionInput) -> dict:
    """
    Activity này thực thi một action.
    Temporal sẽ tự động retry nếu raise exception.
    """
    action = action_registry.get(input.action_type)
    
    if not action:
        raise ValueError(f"Unknown action type: {input.action_type}")
    
    context = ActionContext(
        user_id=input.user_id,
        workflow_id=input.workflow_id,
        instance_id=input.instance_id,
        node_id=input.node_id,
        trigger_data=input.trigger_data,
        previous_outputs=input.previous_outputs,
    )
    
    result: ActionResult = await action.execute(input.config, context)
    
    if not result.success:
        # Raise exception để Temporal biết activity này fail
        # Temporal sẽ retry theo retry policy
        raise Exception(f"Action failed: {result.error}")
    
    return result.output
```

### 3.2 `app/temporal/activities/update_step_status.py`

```python
from temporalio import activity
from dataclasses import dataclass
from datetime import datetime, timezone
from app.database import AsyncSessionLocal
from app.models.execution import WorkflowStepExecution, ExecutionStatus, WorkflowInstance
from sqlalchemy import select

@dataclass
class UpdateStepStatusInput:
    instance_id: str
    node_id: str
    node_type: str
    status: str          # "running", "completed", "failed"
    input_data: dict | None = None
    output_data: dict | None = None
    error_message: str | None = None

@activity.defn(name="update_step_status")
async def update_step_status(input: UpdateStepStatusInput) -> None:
    """Cập nhật trạng thái của một step vào PostgreSQL"""
    async with AsyncSessionLocal() as db:
        # Tìm step record (nếu có)
        result = await db.execute(
            select(WorkflowStepExecution).where(
                WorkflowStepExecution.instance_id == input.instance_id,
                WorkflowStepExecution.node_id == input.node_id,
            )
        )
        step = result.scalar_one_or_none()
        
        now = datetime.now(timezone.utc)
        
        if not step:
            # Tạo mới nếu chưa có
            step = WorkflowStepExecution(
                instance_id=input.instance_id,
                node_id=input.node_id,
                node_type=input.node_type,
                status=input.status,
                input_data=input.input_data,
                started_at=now if input.status == "running" else None,
            )
            db.add(step)
        else:
            step.status = input.status
            if input.output_data:
                step.output_data = input.output_data
            if input.error_message:
                step.error_message = input.error_message
            if input.status in ("completed", "failed"):
                step.completed_at = now
        
        await db.commit()

@dataclass
class UpdateInstanceStatusInput:
    instance_id: str
    status: str
    temporal_workflow_id: str | None = None
    temporal_run_id: str | None = None
    output: dict | None = None
    error_message: str | None = None

@activity.defn(name="update_instance_status")
async def update_instance_status(input: UpdateInstanceStatusInput) -> None:
    """Cập nhật trạng thái của toàn bộ workflow instance"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkflowInstance).where(WorkflowInstance.id == input.instance_id)
        )
        instance = result.scalar_one_or_none()
        
        if not instance:
            return
        
        now = datetime.now(timezone.utc)
        instance.status = input.status
        
        if input.temporal_workflow_id:
            instance.temporal_workflow_id = input.temporal_workflow_id
        if input.temporal_run_id:
            instance.temporal_run_id = input.temporal_run_id
        if input.output:
            instance.output = input.output
        if input.error_message:
            instance.error_message = input.error_message
        if input.status == "running" and not instance.started_at:
            instance.started_at = now
        if input.status in ("completed", "failed", "cancelled"):
            instance.completed_at = now
        
        await db.commit()
```

---

## 4. Workflow Definition — Cortex Generic Workflow

Đây là trái tim của Phase 3. Một Temporal Workflow Definition đủ linh hoạt để chạy **bất kỳ** workflow nào được định nghĩa trong DB.

**`app/temporal/workflows/cortex_workflow.py`**

```python
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
from dataclasses import dataclass
from typing import Any

# Import activities — phải dùng lazy import trong workflow
with workflow.unsafe.imports_passed_through():
    from app.temporal.activities.execute_action import execute_action, ExecuteActionInput
    from app.temporal.activities.update_step_status import (
        update_step_status, UpdateStepStatusInput,
        update_instance_status, UpdateInstanceStatusInput
    )

@dataclass
class CortexWorkflowInput:
    """Input khi start một Cortex workflow instance"""
    instance_id: str
    workflow_id: str
    user_id: str
    definition: dict          # Toàn bộ workflow definition (nodes + edges)
    trigger_data: dict        # Data từ trigger event

@workflow.defn(name="CortexWorkflow")
class CortexWorkflow:
    """
    Generic Workflow Definition cho Cortex.
    Tất cả workflows của user đều dùng class này.
    Logic cụ thể được đọc từ `definition` trong input.
    """
    
    @workflow.run
    async def run(self, input: CortexWorkflowInput) -> dict:
        """Main execution flow"""
        
        # 1. Cập nhật instance status → running
        await workflow.execute_activity(
            update_instance_status,
            UpdateInstanceStatusInput(
                instance_id=input.instance_id,
                status="running",
                temporal_workflow_id=workflow.info().workflow_id,
                temporal_run_id=workflow.info().run_id,
            ),
            start_to_close_timeout=timedelta(seconds=10),
        )
        
        # 2. Phân tích execution graph từ definition
        nodes = input.definition.get("nodes", [])
        edges = input.definition.get("edges", [])
        
        # Tìm action nodes (bỏ qua trigger node)
        action_nodes = [n for n in nodes if not n.get("type", "").startswith("trigger.")]
        
        # Sắp xếp theo thứ tự topological (dựa vào edges)
        ordered_nodes = self._topological_sort(action_nodes, edges)
        
        # 3. Thực thi từng node theo thứ tự
        all_outputs = {}
        final_output = {}
        
        for node in ordered_nodes:
            node_id = node["id"]
            node_type = node["type"]
            node_config = node.get("data", {}).get("config", {})
            
            # 3a. Cập nhật step → running
            await workflow.execute_activity(
                update_step_status,
                UpdateStepStatusInput(
                    instance_id=input.instance_id,
                    node_id=node_id,
                    node_type=node_type,
                    status="running",
                    input_data=node_config,
                ),
                start_to_close_timeout=timedelta(seconds=10),
            )
            
            # 3b. Thực thi action với retry policy
            retry_policy = RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_attempts=3,
                maximum_interval=timedelta(seconds=30),
            )
            
            try:
                output = await workflow.execute_activity(
                    execute_action,
                    ExecuteActionInput(
                        action_type=node_type,
                        config=node_config,
                        user_id=input.user_id,
                        workflow_id=input.workflow_id,
                        instance_id=input.instance_id,
                        node_id=node_id,
                        trigger_data=input.trigger_data,
                        previous_outputs=all_outputs,
                    ),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=retry_policy,
                )
                
                all_outputs[node_id] = output
                final_output[node_id] = output
                
                # 3c. Cập nhật step → completed
                await workflow.execute_activity(
                    update_step_status,
                    UpdateStepStatusInput(
                        instance_id=input.instance_id,
                        node_id=node_id,
                        node_type=node_type,
                        status="completed",
                        output_data=output,
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                )
            
            except Exception as e:
                # 3d. Step fail — cập nhật step → failed
                await workflow.execute_activity(
                    update_step_status,
                    UpdateStepStatusInput(
                        instance_id=input.instance_id,
                        node_id=node_id,
                        node_type=node_type,
                        status="failed",
                        error_message=str(e),
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                )
                
                # Cập nhật instance → failed
                await workflow.execute_activity(
                    update_instance_status,
                    UpdateInstanceStatusInput(
                        instance_id=input.instance_id,
                        status="failed",
                        error_message=f"Step {node_id} failed: {str(e)}",
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                )
                
                # Raise để Temporal ghi nhận workflow failed
                raise
        
        # 4. Tất cả steps hoàn thành → cập nhật instance → completed
        await workflow.execute_activity(
            update_instance_status,
            UpdateInstanceStatusInput(
                instance_id=input.instance_id,
                status="completed",
                output=final_output,
            ),
            start_to_close_timeout=timedelta(seconds=10),
        )
        
        return final_output
    
    def _topological_sort(self, nodes: list[dict], edges: list[dict]) -> list[dict]:
        """
        Sắp xếp nodes theo thứ tự thực thi dựa vào edges.
        Dùng Kahn's algorithm.
        """
        node_map = {n["id"]: n for n in nodes}
        
        # Tính in-degree cho mỗi node
        in_degree = {n["id"]: 0 for n in nodes}
        adjacency = {n["id"]: [] for n in nodes}
        
        for edge in edges:
            src = edge["source"]
            tgt = edge["target"]
            if src in adjacency and tgt in in_degree:
                adjacency[src].append(tgt)
                in_degree[tgt] += 1
        
        # BFS
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []
        
        while queue:
            nid = queue.pop(0)
            if nid in node_map:
                result.append(node_map[nid])
            for neighbor in adjacency.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        return result
```

---

## 5. Worker Setup

**`app/temporal/worker.py`** (mở rộng từ Phase 1)

```python
from temporalio.client import Client
from temporalio.worker import Worker
from app.config import settings
from app.temporal.workflows.cortex_workflow import CortexWorkflow
from app.temporal.activities.execute_action import execute_action
from app.temporal.activities.update_step_status import update_step_status, update_instance_status
import asyncio

async def run_worker():
    """
    Khởi động Temporal Worker.
    Worker này chạy trong cùng process với FastAPI (dùng asyncio background task).
    """
    from app.temporal.client import get_temporal_client
    client = await get_temporal_client()
    
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[CortexWorkflow],
        activities=[
            execute_action,
            update_step_status,
            update_instance_status,
        ],
    )
    
    print(f"[TemporalWorker] Starting worker on task queue: {settings.temporal_task_queue}")
    await worker.run()

def start_worker_background():
    """Chạy worker như một asyncio background task"""
    asyncio.ensure_future(run_worker())
```

**Cập nhật `app/main.py`** — thêm worker startup:

```python
@app.on_event("startup")
async def startup_event():
    from app.temporal.worker import start_worker_background
    from app.triggers.internal_event_listener import start_internal_event_listener
    
    # Start Temporal Worker
    start_worker_background()
    
    # Start Internal Event Listener
    asyncio.ensure_future(start_internal_event_listener())
    
    print("[App] Startup complete")
```

---

## 6. Kết nối Trigger Engine với Temporal

Quay lại `app/triggers/internal_event_listener.py`, thay thế `_trigger_workflow_instance` placeholder bằng code thực:

```python
async def _trigger_workflow_instance(workflow_def: WorkflowDefinition, trigger_data: dict):
    """
    Tạo WorkflowInstance trong DB và start Temporal workflow.
    """
    import uuid
    from app.temporal.client import get_temporal_client
    from app.temporal.workflows.cortex_workflow import CortexWorkflow, CortexWorkflowInput
    from temporalio.common import RetryPolicy
    from datetime import timedelta
    
    async with AsyncSessionLocal() as db:
        # 1. Tạo instance record trong DB
        instance_id = str(uuid.uuid4())
        temporal_workflow_id = f"cortex-wf-{instance_id}"
        
        instance = WorkflowInstance(
            id=instance_id,
            workflow_id=workflow_def.id,
            user_id=workflow_def.user_id,
            status=ExecutionStatus.PENDING,
            trigger_data=trigger_data,
        )
        db.add(instance)
        await db.commit()
        
        # 2. Start Temporal workflow
        client = await get_temporal_client()
        
        handle = await client.start_workflow(
            CortexWorkflow.run,
            CortexWorkflowInput(
                instance_id=instance_id,
                workflow_id=str(workflow_def.id),
                user_id=str(workflow_def.user_id),
                definition=workflow_def.definition,
                trigger_data=trigger_data,
            ),
            id=temporal_workflow_id,
            task_queue=settings.temporal_task_queue,
        )
        
        print(f"[TriggerEngine] Started Temporal workflow: {temporal_workflow_id}, run_id: {handle.result_run_id}")
```

---

## 7. Execution API

**`app/api/v1/executions.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.core.security import get_current_user, CurrentUser
from app.models.execution import WorkflowInstance, WorkflowStepExecution
from app.models.workflow import WorkflowDefinition
from app.schemas.execution import ExecutionResponse
from app.temporal.client import get_temporal_client
from temporalio.service import RPCError

router = APIRouter()

@router.get("/workflows/{workflow_id}/executions")
async def list_executions(
    workflow_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lấy danh sách execution history của một workflow"""
    # Verify workflow ownership
    wf_result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.user_id == current_user.user_id,
        )
    )
    if not wf_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    result = await db.execute(
        select(WorkflowInstance)
        .where(WorkflowInstance.workflow_id == workflow_id)
        .order_by(desc(WorkflowInstance.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    instances = result.scalars().all()
    
    return {"items": [ExecutionResponse.model_validate(i) for i in instances], "page": page}

@router.get("/executions/{instance_id}", response_model=ExecutionResponse)
async def get_execution(
    instance_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lấy chi tiết một execution, bao gồm tất cả step logs"""
    result = await db.execute(
        select(WorkflowInstance)
        .options(selectinload(WorkflowInstance.steps))
        .where(WorkflowInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()
    
    if not instance:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    # Verify ownership qua workflow
    wf_result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == instance.workflow_id,
            WorkflowDefinition.user_id == current_user.user_id,
        )
    )
    if not wf_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Execution not found")
    
    return ExecutionResponse.model_validate(instance)

@router.post("/executions/{instance_id}/cancel")
async def cancel_execution(
    instance_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel một workflow đang chạy"""
    result = await db.execute(
        select(WorkflowInstance).where(WorkflowInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()
    
    if not instance or not instance.temporal_workflow_id:
        raise HTTPException(status_code=404, detail="Execution not found or not started")
    
    # Cancel trên Temporal
    client = await get_temporal_client()
    try:
        handle = client.get_workflow_handle(instance.temporal_workflow_id)
        await handle.cancel()
    except RPCError:
        pass  # Workflow có thể đã complete
    
    # Cập nhật DB
    instance.status = "cancelled"
    await db.commit()
    
    return {"status": "cancelled"}
```

---

## 8. Manual Trigger Endpoint

```python
# Thêm vào app/api/v1/workflows.py

@router.post("/{workflow_id}/trigger", status_code=201)
async def manual_trigger(
    workflow_id: str,
    data: ManualTriggerRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Trigger workflow thủ công"""
    workflow = await _get_workflow_or_404(workflow_id, current_user.user_id, db)
    
    if workflow.status.value != "active":
        raise HTTPException(status_code=409, detail="Workflow must be active to trigger")
    
    trigger_data = {
        "event": "manual.triggered",
        "user_id": current_user.user_id,
        "input": data.input_data,
    }
    
    from app.triggers.internal_event_listener import _trigger_workflow_instance
    await _trigger_workflow_instance(workflow, trigger_data)
    
    return {"status": "triggered"}
```

---

## 9. Verification Checklist — Cuối Phase 3

### Temporal Worker

- [ ] Worker khởi động không có error: `[TemporalWorker] Starting worker on task queue: cortex-workflow-queue`
- [ ] Worker hiện trong Temporal UI (`http://localhost:8080`) tab "Workers"
- [ ] `CortexWorkflow` và tất cả activities được list trong Temporal UI

### End-to-End Flow

- [ ] **Test 1 — Manual trigger**:
  1. Tạo workflow với trigger_type=`manual`, 1 action `action.send_notification`
  2. Activate workflow
  3. `POST /api/v1/workflows/{id}/trigger`
  4. Temporal UI hiện workflow run mới với status "Completed"
  5. DB có `workflow_instances` row với status "completed"
  6. DB có `workflow_step_executions` row với status "completed"

- [ ] **Test 2 — Internal event trigger**:
  1. Tạo workflow với trigger_type=`internal_event`, event=`note.created`
  2. Activate workflow
  3. Publish event vào Redis: `redis-cli publish cortex:workflow:events '{"event":"note.created","note_id":"test-123","user_id":"your-user-id"}'`
  4. Workflow tự động trigger và chạy

- [ ] **Test 3 — Webhook trigger**:
  1. Tạo workflow với trigger_type=`webhook`
  2. Lấy webhook_url từ response
  3. `curl -X POST http://localhost:8001{webhook_url} -H "Content-Type: application/json" -d '{"test":"data"}'`
  4. Workflow trigger và chạy

- [ ] **Test 4 — Cancel**:
  1. Start một workflow instance
  2. `POST /api/v1/executions/{instance_id}/cancel`
  3. Temporal UI hiện status "Cancelled"

### Error Handling

- [ ] Khi action fail, step status = "failed" trong DB
- [ ] Temporal retry 3 lần trước khi mark workflow failed
- [ ] Instance status = "failed" khi workflow fail

---

## 10. Troubleshooting

**Worker không kết nối được Temporal:**
- Kiểm tra `TEMPORAL_HOST=temporal:7233` (trong Docker) hoặc `localhost:7233` (local)
- Temporal server cần ~30s khởi động

**Workflow không start được:**
- Kiểm tra task queue name khớp giữa Worker và `client.start_workflow()`
- Cả hai phải dùng `settings.temporal_task_queue`

**Activities không được register:**
- Đảm bảo tất cả activities được pass vào `Worker(activities=[...])`

**"No workflow worker polling" error trong Temporal UI:**
- Worker chưa start hoặc bị crash
- Xem log: `docker logs workflow_service`
