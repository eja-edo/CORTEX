# SUBAGENT PROMPTS

## Copy-paste prompt cho từng phase — dành cho AI coding agent

> **Cách dùng**: Copy toàn bộ prompt của phase bạn muốn thực hiện, paste vào Claude Code hoặc bất kỳ AI coding agent nào.\
> \*\***Quan trọng**: Chạy theo đúng thứ tự Phase 1 → 2 → 3 → 4 → 5 → 6. Phase 3 và 4 có thể song song.

---

## PROMPT — PHASE 1: Foundation

```
Bạn là một senior backend engineer. Nhiệm vụ của bạn là implement Phase 1 của Cortex Workflow Runtime.

## Context
Cortex là một graduation project (FastAPI backend + React frontend) đang chạy với docker-compose. 
Bạn cần thêm Workflow Runtime như một module mới, chạy song song với codebase hiện tại.
Execution engine là Temporal (self-hosted). Không thay đổi bất kỳ file nào của Cortex hiện tại.

## Nhiệm vụ của bạn trong Phase 1

### 1. Tạo cấu trúc thư mục workflow_service/
Tạo thư mục `workflow_service/` ở root của project với cấu trúc:
```

workflow_service/ ├── Dockerfile ├── requirements.txt ├── alembic.ini ├── alembic/ │ ├── env.py │ └── versions/ ├── app/ │ ├── **init**.py │ ├── main.py │ ├── config.py │ ├── database.py │ ├── models/ │ │ ├── **init**.py │ │ ├── workflow.py │ │ └── execution.py │ ├── schemas/ │ │ ├── **init**.py │ │ ├── workflow.py │ │ └── execution.py │ ├── api/ │ │ ├── **init**.py │ │ └── v1/ │ │ ├── **init**.py │ │ ├── workflows.py (stub only) │ │ └── executions.py (stub only) │ ├── temporal/ │ │ ├── **init**.py │ │ ├── client.py │ │ └── worker.py (stub only) │ └── core/ │ ├── **init**.py │ └── security.py (stub only) └── tests/ └── **init**.py

```

### 2. Thêm Temporal vào docker-compose.yml
Thêm 4 services vào file docker-compose.yml hiện tại (KHÔNG xóa services cũ):
- temporal-postgresql (postgres:13)
- temporal (temporalio/auto-setup:1.24, port 7233)
- temporal-ui (temporalio/ui:2.26, port 8080)
- workflow_service (FastAPI, port 8001)

Tạo file infrastructure/temporal/dynamicconfig/development-sql.yaml

### 3. SQLAlchemy Models
Implement đầy đủ 3 models trong schema "workflow" (PostgreSQL schema, không phải DB riêng):
- WorkflowDefinition (table: workflow.workflow_definitions)
- WorkflowTriggerWebhook (table: workflow.workflow_trigger_webhooks)
- WorkflowInstance (table: workflow.workflow_instances)
- WorkflowStepExecution (table: workflow.workflow_step_executions)

### 4. Alembic migration
- Cấu hình alembic.ini và alembic/env.py để dùng async engine
- Migration đầu tiên phải tạo schema "workflow" trước: `op.execute("CREATE SCHEMA IF NOT EXISTS workflow")`
- Tạo migration file với tất cả 4 tables

### 5. Temporal Client
Implement singleton Temporal client trong app/temporal/client.py

### 6. main.py
FastAPI app với:
- CORS middleware (allow localhost:3000)
- Router stubs (workflows, executions)
- Health endpoint GET /health trả về {"status": "ok", "service": "workflow_service"}
- Startup event (empty cho Phase 1)

## Constraints quan trọng
- Dùng Python 3.11, FastAPI 0.115, SQLAlchemy 2.0 async, temporalio 1.7, Pydantic v2
- Tất cả DB operations phải async (không dùng sync session)
- Schema PostgreSQL là "workflow", không phải public
- Không sửa bất kỳ file nào trong backend/ hoặc frontend/ của Cortex

## File tham khảo
Đọc file `01_PHASE1_FOUNDATION.md` để xem code đầy đủ cho từng file.

## Definition of Done
- [ ] docker-compose up không có error
- [ ] curl http://localhost:8001/health trả về {"status": "ok", "service": "workflow_service"}
- [ ] Temporal UI accessible tại http://localhost:8080
- [ ] alembic upgrade head chạy không có error
- [ ] PostgreSQL có schema "workflow" với 4 tables
```

---

## PROMPT — PHASE 2: Backend Core

```
Bạn là một senior backend engineer. Nhiệm vụ của bạn là implement Phase 2 của Cortex Workflow Runtime.

## Prerequisite
Phase 1 đã hoàn thành:
- workflow_service/ đã có cấu trúc đầy đủ
- Docker-compose đã có Temporal + workflow_service
- DB schema "workflow" đã có 4 tables
- workflow_service chạy được tại port 8001

## Nhiệm vụ của bạn trong Phase 2

### 1. Pydantic Schemas
Implement đầy đủ trong app/schemas/:
- workflow.py: WorkflowCreate, WorkflowUpdate, WorkflowResponse, WorkflowListResponse, WorkflowNode, WorkflowEdge, WorkflowDefinitionSchema
- execution.py: ExecutionResponse, StepExecutionResponse, ManualTriggerRequest

### 2. Auth Middleware
Implement app/core/security.py:
- CurrentUser dataclass với user_id và email
- get_current_user() dependency: decode JWT token, extract sub → user_id
- Dùng cùng JWT_SECRET_KEY với Cortex backend (đọc từ env var)

### 3. Workflow CRUD API
Implement đầy đủ app/api/v1/workflows.py với các endpoints:
- GET /api/v1/workflows (list với pagination, filter by status và workspace_id)
- POST /api/v1/workflows (tạo mới, tự tạo webhook record nếu trigger_type=webhook)
- GET /api/v1/workflows/{id} (chi tiết, 404 nếu không phải của user này)
- PATCH /api/v1/workflows/{id} (partial update, tăng version nếu sửa definition khi đang active)
- DELETE /api/v1/workflows/{id} (soft delete: is_deleted=true)
- POST /api/v1/workflows/{id}/activate (validate: phải có trigger node và action node)
- POST /api/v1/workflows/{id}/pause

### 4. Webhook Trigger Endpoint
Tạo app/api/v1/webhooks.py:
- POST /api/v1/webhooks/{webhook_path}
- Không cần JWT auth, dùng X-Webhook-Secret header (optional verify)
- Parse request body, tìm workflow tương ứng, log trigger data
- Trả về 202 Accepted

### 5. Action Engine
Tạo cấu trúc plugin system:
- app/actions/base.py: BaseAction abstract class, ActionContext dataclass, ActionResult dataclass
  - BaseAction có: action_type (abstract), display_name (abstract), description (abstract), config_schema, execute() (abstract), resolve_template()
  - resolve_template() hỗ trợ {{trigger.xxx}} và {{steps.NODE_ID.xxx}} syntax
- app/actions/registry.py: ActionRegistry singleton với register(), get(), list_all()
- app/actions/builtin/create_note.py: CreateNoteAction (gọi Cortex backend qua httpx)
- app/actions/builtin/send_notification.py: SendNotificationAction
- app/actions/__init__.py: đăng ký tất cả builtin actions

### 6. Actions Catalog API
Tạo app/api/v1/actions.py:
- GET /api/v1/actions: trả về danh sách tất cả actions và triggers với config_schema

### 7. Internal Event Listener (Trigger Engine)
Tạo app/triggers/internal_event_listener.py:
- start_internal_event_listener(): async function subscribe Redis Pub/Sub channel "cortex:workflow:events"
- _handle_event(): tìm active workflows có trigger_type=internal_event và event match
- _matches_filters(): check event data với workflow trigger_config.filters
- _trigger_workflow_instance(): placeholder (chỉ log, sẽ implement Temporal ở Phase 3)

### 8. Cập nhật main.py
- Include tất cả routers (workflows, executions, webhooks, actions)
- Startup event: khởi động internal event listener

## Constraints
- Tất cả endpoints phải có authentication (trừ webhooks và health)
- User chỉ có thể xem/sửa workflow của chính mình (dùng user_id từ JWT)
- Không raise exception trong publish event — fail silently
- CreateNoteAction và SendNotificationAction gọi qua httpx đến CORTEX_BACKEND_URL

## File tham khảo
Đọc file `02_PHASE2_BACKEND_CORE.md` để xem code đầy đủ.

## Definition of Done
- [ ] POST /api/v1/workflows tạo workflow thành công, trả về 201
- [ ] GET /api/v1/workflows trả về danh sách có phân trang
- [ ] POST /api/v1/workflows/{id}/activate validate đúng (400 nếu thiếu trigger/action node)
- [ ] Endpoint không có JWT trả về 401
- [ ] User không thể truy cập workflow của user khác (404)
- [ ] GET /api/v1/actions trả về danh sách actions
- [ ] Internal event listener start không có error (kiểm tra log)
```

---

## PROMPT — PHASE 3: Temporal Integration

```
Bạn là một senior backend engineer chuyên về distributed systems. Nhiệm vụ của bạn là implement Phase 3 của Cortex Workflow Runtime — tích hợp Temporal để workflow thực sự chạy được.

## Prerequisite
Phase 1 và Phase 2 đã hoàn thành:
- Temporal server đang chạy tại temporal:7233
- workflow_service có CRUD API, Auth, Action Engine
- DB có workflow_definitions và workflow_instances tables
- ActionRegistry đã có CreateNoteAction, SendNotificationAction

## Temporal Concepts cần hiểu trước khi code
- Workflow Definition (@workflow.defn): mô tả LOGIC. KHÔNG được có side effects (không gọi DB, không HTTP, không time.now())
- Activity (@activity.defn): thực hiện CÔNG VIỆC thực tế. Có thể gọi DB, HTTP, v.v.
- Worker: process chạy cả Workflows và Activities, lắng nghe Task Queue
- Task Queue: channel để Temporal server giao việc cho Worker

## Nhiệm vụ của bạn trong Phase 3

### 1. Activities
Tạo app/temporal/activities/:

**execute_action.py**
- @activity.defn(name="execute_action")
- Input: ExecuteActionInput dataclass (action_type, config, user_id, workflow_id, instance_id, node_id, trigger_data, previous_outputs)
- Lấy action từ action_registry, tạo ActionContext, gọi action.execute()
- Nếu action result.success=False → raise Exception (Temporal sẽ retry)
- Return: dict output

**update_step_status.py**
- @activity.defn(name="update_step_status"): cập nhật WorkflowStepExecution trong DB
- @activity.defn(name="update_instance_status"): cập nhật WorkflowInstance trong DB

### 2. CortexWorkflow Definition
Tạo app/temporal/workflows/cortex_workflow.py:
- @workflow.defn(name="CortexWorkflow")
- Input: CortexWorkflowInput dataclass (instance_id, workflow_id, user_id, definition, trigger_data)
- Logic:
  1. update_instance_status → "running"
  2. Đọc nodes/edges từ definition, bỏ qua trigger nodes
  3. Sắp xếp action nodes theo topological sort (Kahn's algorithm)
  4. Với mỗi node: update_step_status("running") → execute_action → update_step_status("completed")
  5. Nếu execute_action raise exception: update_step_status("failed") → update_instance_status("failed") → re-raise
  6. Sau tất cả nodes: update_instance_status("completed")
- _topological_sort(): Kahn's algorithm, nhận nodes và edges, trả về sorted list

QUAN TRỌNG: Trong @workflow.defn, KHÔNG được import trực tiếp activities. Dùng:
```python
with workflow.unsafe.imports_passed_through():
    from app.temporal.activities.execute_action import execute_action, ExecuteActionInput
```

### 3. Temporal Worker Setup

Mở rộng app/temporal/worker.py:

- run_worker(): async function khởi động Worker với CortexWorkflow + tất cả activities
- start_worker_background(): dùng asyncio.ensure_future(run_worker())

Cập nhật app/main.py startup event:

- Gọi start_worker_background()
- Gọi asyncio.ensure_future(start_internal_event_listener())

### 4. Kết nối Trigger Engine với Temporal

Cập nhật app/triggers/internal_event_listener.py:

- \_trigger_workflow_instance() không còn là placeholder nữa
- Tạo WorkflowInstance record trong DB với status="pending"
- temporal_workflow_id = f"cortex-wf-{instance_id}"
- Gọi client.start_workflow(CortexWorkflow.run, CortexWorkflowInput(...), id=temporal_workflow_id, task_queue=settings.temporal_task_queue)

### 5. Webhook Trigger → Temporal

Cập nhật app/api/v1/webhooks.py:

- Sau khi verify webhook, gọi \_trigger_workflow_instance() thay vì chỉ log

### 6. Manual Trigger

Cập nhật app/api/v1/workflows.py:

- POST /{id}/trigger: gọi \_trigger_workflow_instance() với trigger_data = {"event": "manual.triggered", ...}

### 7. Executions API

Implement đầy đủ app/api/v1/executions.py:

- GET /api/v1/workflows/{wf_id}/executions: list với pagination
- GET /api/v1/executions/{instance_id}: chi tiết với steps
- POST /api/v1/executions/{instance_id}/cancel: cancel Temporal workflow + update DB

## Constraints

- workflow.\_topological_sort() phải handle disconnected nodes gracefully (không crash)
- Tất cả Temporal Activity calls phải có start_to_close_timeout
- execute_action Activity phải có retry_policy (max 3 attempts)
- Không đặt code có side effects bên trong @workflow.defn (chỉ workflow.execute_activity và workflow.sleep)

## File tham khảo

Đọc file `03_PHASE3_TEMPORAL_INTEGRATION.md` để xem code đầy đủ.

## Definition of Done

- [ ] Worker khởi động: log "\[TemporalWorker\] Starting worker on task queue: cortex-workflow-queue"

- [ ] Worker hiện trong Temporal UI (http://localhost:8080) tab Workers

- [ ] Manual trigger: POST /api/v1/workflows/{id}/trigger → Temporal UI hiện execution mới

- [ ] Execution DB có instance với status="completed" sau khi workflow chạy xong

- [ ] Step executions được log đúng trong workflow_step_executions table

- [ ] Internal event trigger: publish event Redis → workflow tự động chạy

```

---

## PROMPT — PHASE 4: Frontend Builder
```

Bạn là một senior frontend engineer chuyên React và TypeScript. Nhiệm vụ của bạn là implement Phase 4 — Visual Workflow Builder dùng React Flow.

## Prerequisite

Phase 2 đã hoàn thành:

- workflow_service API hoạt động tại http://localhost:8001
- GET /api/v1/actions trả về danh sách actions và triggers
- GET/POST/PATCH/DELETE /api/v1/workflows hoạt động
- Cortex frontend đang chạy tại http://localhost:3000 (React 19 + TypeScript + Vite + Zustand)

## Cài đặt dependencies trước

```bash
cd frontend
npm install reactflow @reactflow/core
npm install react-hook-form zod @hookform/resolvers
```

## Nhiệm vụ của bạn trong Phase 4

### 1. Types

Tạo frontend/src/types/workflow.ts với đầy đủ TypeScript interfaces: WorkflowStatus, TriggerType, ExecutionStatus, NodePosition, WorkflowNodeData, WorkflowNode, WorkflowEdge, WorkflowDefinition, Workflow, WorkflowListResponse, StepExecution, WorkflowInstance, ActionDefinition

### 2. Zustand Store

Tạo frontend/src/stores/workflowStore.ts:

- State: workflow, nodes, edges, isDirty, isSaving, selectedNodeId, availableActions, availableTriggers
- Actions: setWorkflow, onNodesChange, onEdgesChange, onConnect, addNode, updateNodeConfig, selectNode, setAvailableActions, setIsSaving, markSaved
- onConnect phải dùng addEdge từ reactflow với id tự generate

### 3. Custom Nodes

Tạo frontend/src/components/workflow/nodes/:

**TriggerNode.tsx**:

- Màu xanh (blue-500), border blue
- Hiện label, event name nếu đã config
- Warning "Chưa cấu hình" nếu isConfigured=false
- Chỉ có source handle (bottom)

**ActionNode.tsx**:

- Màu tím (purple-500), border purple
- Emoji icon theo action type (📝 create_note, 🔔 notification, 🤖 call_ai, ...)
- Target handle (top) + source handle (bottom)

**nodes/index.ts**: export nodeTypes = { triggerNode: TriggerNode, actionNode: ActionNode }

### 4. Node Palette (Left sidebar)

Tạo frontend/src/components/workflow/NodePalette.tsx:

- Width: 256px, border-right
- 2 sections: Triggers (blue) và Actions (purple)
- Mỗi item: draggable với onDragStart set dataTransfer data "application/workflow-node"
- Hiện display_name và description từ availableTriggers/availableActions store

### 5. Canvas

Tạo frontend/src/components/workflow/WorkflowCanvas.tsx:

- ReactFlow wrapper với nodeTypes
- onDrop: parse dataTransfer, tính position relative to canvas, addNode với id="node-{Date.now()}"
- onDragOver: event.preventDefault()
- onNodeClick: selectNode(node.id)
- onPaneClick: selectNode(null)
- Background (dots), Controls, MiniMap
- MiniMap màu: triggerNode=blue, actionNode=purple

### 6. Config Panel (Right sidebar)

Tạo frontend/src/components/workflow/ConfigPanel.tsx:

- Width: 288px, border-left
- Nếu không có selectedNodeId: hiện empty state "Chọn một node để cấu hình"
- Nếu là triggerNode: render TriggerConfigPanel
- Nếu là actionNode: render ActionConfigPanel

**TriggerConfigPanel.tsx** (xử lý từng nodeType):

- trigger.internal_event: dropdown chọn event (note.created, schedule.created, v.v.)
- trigger.webhook: hiện info "URL sẽ được tạo tự động"
- trigger.manual: hiện info "Không cần cấu hình"
- Mỗi khi thay đổi: gọi updateNodeConfig(node.id, newConfig)

**ActionConfigPanel.tsx** (render dynamic form từ config_schema):

- action.create_note: inputs cho title, content, workspace_id
- action.send_notification: inputs cho title, message, select type
- action.call_ai: textarea cho prompt, input cho output_key
- action.wait: number input + select unit
- Tất cả inputs hỗ trợ {{template}} syntax (không cần validate template, chỉ là text input)

### 7. Toolbar

Tạo frontend/src/components/workflow/WorkflowToolbar.tsx:

- Back button → /workflows
- Workflow name
- Status badge (active=green, draft=gray, paused=yellow)
- "● Chưa lưu" indicator khi isDirty=true
- Buttons: Lưu (disabled khi !isDirty), Activate/Pause, Run Now (chỉ khi active), History

### 8. Pages

Tạo frontend/src/pages/workflows/:

- index.tsx: danh sách workflows, empty state, button "Tạo mới"
- \[id\]/builder.tsx: WorkflowBuilderPage (load workflow + actions, compose Palette+Canvas+ConfigPanel+Toolbar)
- \[id\]/executions.tsx: Execution history với step timeline

### 9. API Hook

Tạo frontend/src/hooks/workflow/useWorkflowApi.ts với tất cả API calls theo file 10_INTEGRATION_GUIDE.md

### 10. Routes

Thêm vào Cortex router (App.tsx hoặc router config):

- /workflows → WorkflowListPage
- /workflows/new → WorkflowBuilderPage (không có id, tạo mới khi save lần đầu)
- /workflows/:id/builder → WorkflowBuilderPage
- /workflows/:id/executions → WorkflowExecutionsPage

Thêm "Workflows" vào sidebar navigation của Cortex.

### 11. Config: WORKFLOW_API_BASE

Thêm VITE_WORKFLOW_API_URL vào frontend/.env và sử dụng trong useWorkflowApi

## Constraints

- Dùng Tailwind CSS (Cortex đã có)
- Không dùng form HTML element, dùng controlled components
- Node ID format: "node-{Date.now()}" khi drop từ palette
- Edge ID format: "edge-{Date.now()}" khi connect
- Khi load workflow từ API, setWorkflow() trong store tự populate nodes và edges

## File tham khảo

Đọc file `04_PHASE4_FRONTEND_BUILDER.md` để xem code đầy đủ.

## Definition of Done

- [ ] /workflows hiện danh sách + empty state

- [ ] Kéo Trigger node từ palette vào canvas → node xuất hiện đúng vị trí

- [ ] Kéo Action node từ palette vào canvas → node xuất hiện

- [ ] Click node → Config panel mở bên phải

- [ ] Select event trong TriggerConfigPanel → node data cập nhật (không reload)

- [ ] Kéo từ source handle đến target handle → edge xuất hiện

- [ ] Click Lưu → gọi PATCH API, "● Chưa lưu" biến mất

- [ ] Click Activate → status badge đổi sang "active"

- [ ] Reload trang → workflow load lại đúng nodes + edges

```

---

## PROMPT — PHASE 5: Built-in Triggers & Actions
```

Bạn là một senior backend và frontend engineer. Nhiệm vụ của bạn là implement Phase 5 — tất cả built-in triggers và actions tích hợp sâu với Cortex.

## Prerequisite

Phase 3 (Temporal integration) và Phase 4 (Frontend builder) đã hoàn thành.

## Nhiệm vụ Backend

### 1. Thêm built-in actions vào workflow_service

**app/actions/builtin/update_note.py** — UpdateNoteAction

- action_type: "action.update_note"
- Config: note_id (template supported), content, append (bool)
- Gọi PATCH {cortex_backend_url}/api/notes/{note_id} qua httpx
- Header: X-Internal-API-Key + X-User-ID

**app/actions/builtin/create_schedule.py** — CreateScheduleAction

- action_type: "action.create_schedule"
- Config: title, start_time, end_time, description
- Gọi POST {cortex_backend_url}/api/schedules

**app/actions/builtin/call_ai.py** — CallAIAction

- action_type: "action.call_ai"
- Config: prompt (template supported), output_key (default: "ai_result")
- Gọi POST {cortex_backend_url}/api/agent/complete
- Return: {output_key: ai_text, "model_used": ...}

**app/actions/builtin/call_webhook.py** — CallWebhookAction

- action_type: "action.call_webhook"
- Config: url, method, headers (dict), body (string, template supported)
- Gọi HTTP request ra ngoài qua httpx
- Return: {status_code: int, response_body: str}

**app/actions/builtin/wait_action.py** — WaitAction

- action_type: "action.wait"
- execute() chỉ return success (Temporal workflow tự xử lý via workflow.sleep)
- Cập nhật CortexWorkflow.\_run() để check node_type == "action.wait" và dùng workflow.sleep()

**app/actions/builtin/condition.py** — ConditionAction

- action_type: "action.condition"
- Operators: equals, not_equals, contains, not_contains, is_empty, is_not_empty
- Return: {condition_result: bool, branch: "true"|"false"}
- Cập nhật CortexWorkflow để handle condition node: check output branch, chỉ execute nodes trên đúng branch

Đăng ký tất cả actions mới trong app/actions/**init**.py

### 2. Schedule Due Soon Trigger

Tạo app/temporal/workflows/schedule_checker.py:

- @workflow.defn(name="ScheduleCheckerWorkflow")
- Chạy infinite loop với workflow.sleep(timedelta(minutes=1))
- Mỗi vòng: execute_activity(check_due_schedules)

Tạo app/temporal/activities/check_due_schedules.py:

- @activity.defn(name="check_due_schedules")
- Gọi GET {cortex_backend_url}/api/schedules/upcoming?minutes=61 (internal endpoint)
- Với mỗi schedule sắp đến hạn trong 60 phút: publish event "schedule.due_soon" lên Redis

Khởi động ScheduleCheckerWorkflow khi workflow_service startup (chỉ start nếu chưa running).

### 3. Internal endpoints trong Cortex Backend

Thêm vào Cortex backend (file backend/app/api/notifications.py):

- POST /api/notifications/internal: tạo notification, verify X-Internal-API-Key

Thêm vào backend/app/api/agent.py (hoặc tương đương):

- POST /api/agent/complete: one-shot AI completion, verify X-Internal-API-Key + X-User-ID

Thêm vào backend/app/api/schedules.py:

- GET /api/schedules/upcoming?minutes=N: trả về schedules có start_time trong N phút tới, verify X-Internal-API-Key

Tạo backend/app/services/redis/event_publisher.py và thêm publish calls vào NoteService, ScheduleService, AssetService.

Tạo backend/app/core/internal_auth.py: verify_internal_api_key dependency.

## Nhiệm vụ Frontend

### 4. Thêm nodes mới vào Node Palette

Sau khi backend trả về thêm actions từ GET /api/v1/actions, palette tự động hiện. Nhưng cần thêm Config Panels cho:

**ActionConfigPanel** — thêm xử lý cho:

- action.update_note: note_id input + content textarea + append checkbox
- action.create_schedule: title, start_time, end_time inputs
- action.call_ai: prompt textarea + output_key input (với gợi ý placeholder)
- action.call_webhook: url input, method select, headers key-value editor, body textarea
- action.wait: duration number + unit select (seconds/minutes/hours)
- action.condition: left input + operator select + right input (right ẩn nếu is_empty/is_not_empty)

### 5. Condition Node UI

Tạo frontend/src/components/workflow/nodes/ConditionNode.tsx:

- Hiện nội dung condition (left operator right)
- 2 output handles: "true" (xanh) và "false" (đỏ)
- Thêm vào nodeTypes export

### 6. Template Variable Helper

Thêm tooltip/helper text trong Config Panels hiển thị các template variables có sẵn:

- Dựa vào trigger type của workflow, hiện gợi ý: {{trigger.title}}, {{trigger.note_id}}, v.v.
- Dựa vào nodes đã có trong workflow, hiện gợi ý: {{steps.NODE_ID.output_key}}

## Constraints

- Tất cả actions phải xử lý httpx.HTTPError gracefully (return ActionResult với success=False)
- Không expose internal API endpoints trong Swagger docs của Cortex (include_in_schema=False)
- ScheduleCheckerWorkflow chỉ được start 1 instance duy nhất (check trước khi start)

## File tham khảo

Đọc file `05_PHASE5_BUILTIN_AND_POLISH.md` phần A.

## Definition of Done

- [ ] GET /api/v1/actions trả về 8 actions và 3 triggers

- [ ] action.call_ai thực sự gọi được AI và trả về text

- [ ] action.send_notification tạo notification xuất hiện trong Cortex UI

- [ ] action.create_note tạo note mới trong Cortex

- [ ] Demo Scenario 1 hoạt động: tạo note → AI summary → notification xuất hiện (end-to-end &lt; 15s)

- [ ] Demo Scenario 3 hoạt động: POST webhook → note mới được tạo

```

---

## PROMPT — PHASE 6: Polish & Testing
```

Bạn là một senior engineer. Nhiệm vụ của bạn là implement Phase 6 — viết tests, polish UI, setup monitoring, và chuẩn bị demo.

## Prerequisite

Phase 1-5 đã hoàn thành. Workflow Runtime chạy end-to-end được.

## Nhiệm vụ

### 1. Unit Tests (pytest)

Tạo workflow_service/tests/conftest.py:

- Fixture test_db: SQLite in-memory async database
- Fixture client: httpx AsyncClient với override get_db
- Fixture auth_headers: JWT token hợp lệ với TEST_USER_ID
- Helper make_test_token()

Tạo workflow_service/tests/test_actions.py (dùng pytest-asyncio):

- test_template_resolve_trigger_field()
- test_template_resolve_nested_field()
- test_template_resolve_previous_step()
- test_template_resolve_missing_var() — phải return empty string, không crash
- test_action_registry_has_builtins()
- test_condition_equals_true/false()
- test_condition_contains()
- test_condition_is_empty()

Tạo workflow_service/tests/test_workflow_api.py:

- test_create_workflow() — 201, status=draft
- test_get_workflow() — 200
- test_list_workflows_pagination() — page_size đúng
- test_activate_workflow_without_trigger_node_fails() — 400
- test_cannot_access_other_user_workflow() — 404
- test_delete_workflow_soft_deletes() — 204, sau đó GET trả 404

Tạo workflow_service/tests/test_trigger_engine.py:

- test_matches_filters_empty()
- test_matches_filters_match()
- test_matches_filters_no_match()
- test_matches_filters_missing_key()

Thêm vào requirements.txt: pytest, pytest-asyncio, httpx, aiosqlite

### 2. Prometheus Metrics

Tạo workflow_service/app/core/metrics.py với:

- workflow_triggers_total: Counter, labels=\[trigger_type, status\]
- workflow_execution_duration: Histogram, buckets=\[1,5,10,30,60,300\]
- active_instances: Gauge

Mount metrics endpoint trong main.py: app.mount("/metrics", make_asgi_app())

Thêm metric increment vào:

- \_trigger_workflow_instance(): workflow_triggers_total.labels(...).inc()
- update_instance_status activity: active_instances.inc() khi running, dec() khi completed/failed

### 3. Structured Logging

Tạo workflow_service/app/core/logging.py: JSONFormatter class Gọi setup_logging() trong main.py startup Thay tất cả print() statements bằng logging calls

### 4. Frontend Error States

Cập nhật WorkflowListPage:

- Loading spinner khi đang fetch
- Empty state với "Tạo workflow đầu tiên" button khi list rỗng
- Error state khi API fail

Cập nhật WorkflowBuilderPage:

- Loading state khi đang load workflow
- Error toast khi save fail
- "Unsaved changes" warning khi user navigate away với isDirty=true (dùng beforeunload hoặc React Router prompt)

Cập nhật WorkflowToolbar:

- Validation trước khi activate: check trigger nodes, action nodes, disconnected nodes
- Hiện error message cụ thể: "Workflow cần ít nhất 1 trigger node", "2 nodes chưa được kết nối"

Cập nhật ExecutionHistory:

- Polling mỗi 3 giây nếu có instance đang "running" hoặc "pending"
- Link "Xem trong Temporal UI" với đúng URL

### 5. Node Validation Highlight

Khi user click Activate và có nodes chưa configured:

- Highlight các nodes lỗi bằng border đỏ (thêm `selected: true` hoặc custom class)
- Scroll canvas đến node đầu tiên bị lỗi

### 6. workflow_service README.md

Tạo workflow_service/README.md với:

- Quick start: docker-compose up, verify health
- Cấu trúc thư mục
- Environment variables (copy từ 10_INTEGRATION_GUIDE.md phần 10)
- API endpoints summary
- Demo scenarios step-by-step (3 scenarios)
- Known limitations

### 7. E2E Test Script

Tạo workflow_service/scripts/test_e2e.sh:

- Nhận TOKEN làm argument
- Test manual trigger workflow (create → activate → trigger → wait → check execution status)
- Print PASS/FAIL cho từng step
- Exit code 0 nếu tất cả pass, 1 nếu có fail

## Constraints

- Tests phải chạy không cần Docker (dùng SQLite in-memory)
- pytest phải pass mà không cần Temporal server
- Không thay đổi business logic, chỉ thêm tests và monitoring
- README.md phải đủ chi tiết để người không biết codebase cũng setup được trong 15 phút

## File tham khảo

Đọc file `06_PHASE6_POLISH_TESTING.md` để xem đầy đủ.

## Definition of Done

- [ ] pytest workflow_service/tests/ -v — tất cả tests pass (không cần Docker)

- [ ] curl http://localhost:8001/metrics — trả về Prometheus metrics

- [ ] WorkflowListPage hiện empty state đúng khi chưa có workflow

- [ ] Activate workflow với nodes chưa cấu hình → hiện error message cụ thể

- [ ] README.md đủ để setup từ zero trong 15 phút

- [ ] test_e2e.sh chạy và in PASS cho manual trigger scenario

```
```