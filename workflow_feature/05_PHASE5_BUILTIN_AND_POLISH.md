# PHASE 5 & 6 — BUILT-IN TRIGGERS/ACTIONS + POLISH & TESTING
## Cortex Integration + Demo Scenarios + Final QA

> **Thời gian**: Tuần 9–12 (20 ngày làm việc)  
> **Prerequisite**: Phase 3 + Phase 4 hoàn thành  
> **Mục tiêu**: Workflow Runtime hoàn chỉnh, demo được, tích hợp sâu với Cortex  

---

# PHẦN A — PHASE 5: BUILT-IN TRIGGERS & ACTIONS

## A.1 Tổng quan Built-in Components

Đây là danh sách đầy đủ triggers và actions cần implement để Workflow Runtime có ý nghĩa trong Cortex:

### Triggers (6 loại)

| Trigger Type | Mô tả | Cortex event key |
|---|---|---|
| `trigger.note_created` | Khi một note mới được tạo | `note.created` |
| `trigger.schedule_created` | Khi một lịch mới được tạo | `schedule.created` |
| `trigger.schedule_due` | Khi một lịch sắp đến hạn (15 phút trước) | `schedule.due_soon` |
| `trigger.asset_processed` | Khi OCR/STT xử lý xong một file | `asset.processed` |
| `trigger.webhook` | Nhận HTTP webhook | (external) |
| `trigger.manual` | User trigger thủ công | (manual) |

### Actions (8 loại)

| Action Type | Mô tả | Gọi vào đâu |
|---|---|---|
| `action.create_note` | Tạo note mới | Cortex Notes API |
| `action.update_note` | Cập nhật note hiện tại | Cortex Notes API |
| `action.send_notification` | Gửi notification cho user | Cortex Notifications API |
| `action.create_schedule` | Tạo lịch mới | Cortex Schedules API |
| `action.call_ai` | Gọi Gemini với prompt tùy chỉnh | Cortex AI endpoint |
| `action.call_webhook` | Gọi HTTP endpoint bên ngoài | External HTTP |
| `action.wait` | Delay X giây/phút trước khi bước tiếp | Temporal timer |
| `action.condition` | Rẽ nhánh dựa vào điều kiện | Logic trong workflow |

---

## A.2 Implement: `action.call_ai`

Đây là action quan trọng nhất — cho phép workflow gọi AI trong Cortex.

**`workflow_service/app/actions/builtin/call_ai.py`**

```python
from app.actions.base import BaseAction, ActionContext, ActionResult
import httpx
from app.config import settings

class CallAIAction(BaseAction):
    
    @property
    def action_type(self) -> str:
        return "action.call_ai"
    
    @property
    def display_name(self) -> str:
        return "Gọi AI"
    
    @property
    def description(self) -> str:
        return "Gọi Gemini với prompt tùy chỉnh, lấy kết quả cho bước tiếp theo"
    
    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "title": "Prompt",
                    "description": "Hỗ trợ template: {{trigger.note_content}}, {{steps.step1.output}}"
                },
                "output_key": {
                    "type": "string",
                    "title": "Tên kết quả",
                    "description": "Tên để các bước sau tham chiếu. Ví dụ: 'summary'",
                    "default": "ai_result"
                }
            },
            "required": ["prompt"]
        }
    
    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        prompt = self.resolve_template(config.get("prompt", ""), context)
        output_key = config.get("output_key", "ai_result")
        
        async with httpx.AsyncClient() as client:
            try:
                # Gọi vào Cortex backend agent endpoint
                response = await client.post(
                    f"{settings.cortex_backend_url}/api/agent/complete",
                    json={
                        "prompt": prompt,
                        "stream": False,
                    },
                    headers={
                        "X-Internal-API-Key": settings.cortex_internal_api_key,
                        "X-User-ID": context.user_id,
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                data = response.json()
                
                ai_text = data.get("content", "")
                
                return ActionResult(
                    success=True,
                    output={output_key: ai_text, "model_used": data.get("model")}
                )
            
            except httpx.HTTPError as e:
                return ActionResult(success=False, output={}, error=str(e))
```

---

## A.3 Implement: `action.wait` (Temporal Timer)

Action này khác các action khác — không gọi API mà dùng Temporal timer trực tiếp.

```python
# workflow_service/app/actions/builtin/wait_action.py

from app.actions.base import BaseAction, ActionContext, ActionResult

class WaitAction(BaseAction):
    """
    QUAN TRỌNG: Action này là special case.
    Thay vì implement execute(), nó return một signal cho Temporal Workflow
    để sử dụng workflow.sleep() thay vì activity execution.
    """
    
    @property
    def action_type(self) -> str:
        return "action.wait"
    
    @property
    def display_name(self) -> str:
        return "Chờ"
    
    @property
    def description(self) -> str:
        return "Dừng workflow một khoảng thời gian rồi tiếp tục"
    
    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "duration": {"type": "number", "title": "Thời gian", "default": 5},
                "unit": {
                    "type": "string",
                    "title": "Đơn vị",
                    "enum": ["seconds", "minutes", "hours"],
                    "default": "minutes"
                }
            },
            "required": ["duration", "unit"]
        }
    
    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        # Hàm này không được gọi trực tiếp
        # Temporal Workflow nhận biết action.wait và dùng workflow.sleep()
        # (xem CortexWorkflow._handle_special_actions)
        return ActionResult(success=True, output={"waited": True})
```

**Cập nhật `CortexWorkflow`** — xử lý special actions:

```python
# Thêm vào CortexWorkflow.run(), trong vòng lặp các nodes

# Trước khi execute action, check special cases
if node_type == "action.wait":
    duration = node_config.get("duration", 5)
    unit = node_config.get("unit", "minutes")
    
    seconds = duration
    if unit == "minutes":
        seconds = duration * 60
    elif unit == "hours":
        seconds = duration * 3600
    
    # Dùng Temporal sleep — durable, có thể survive server restart
    await workflow.sleep(timedelta(seconds=seconds))
    all_outputs[node_id] = {"waited_seconds": seconds}
    continue  # Skip normal activity execution
```

---

## A.4 Publish Events từ Cortex Backend

Đây là việc cần làm trong **Cortex backend** (không phải workflow_service). Thêm event publishing vào tất cả services liên quan:

### Endpoint nội bộ: Notification

Cortex backend cần thêm endpoint để workflow service có thể gửi notification:

```python
# backend/app/api/notifications.py — thêm route mới

@router.post("/internal", include_in_schema=False)
async def create_internal_notification(
    data: dict,
    api_key: str = Header(..., alias="X-Internal-API-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Chỉ dùng nội bộ — từ workflow_service"""
    if api_key != settings.internal_api_key:
        raise HTTPException(status_code=401)
    
    notification = Notification(
        user_id=data["user_id"],
        title=data["title"],
        message=data["message"],
        type=data.get("type", "info"),
        source=data.get("source", "system"),
        source_id=data.get("source_id"),
    )
    db.add(notification)
    await db.commit()
    
    # Publish qua SSE để user nhận realtime
    await sse_manager.publish_to_user(
        data["user_id"],
        {"type": "notification", "data": {...}}
    )
    
    return {"id": str(notification.id)}
```

---

## A.5 Condition Node — Rẽ nhánh

Condition node cho phép workflow rẽ nhánh theo điều kiện.

**React Flow node type mới: `conditionNode`**

```typescript
// Thêm vào WorkflowNode types
// Condition node có 2 output handles: "true" và "false"
```

**Backend: Condition evaluation**

```python
# workflow_service/app/actions/builtin/condition.py

class ConditionAction(BaseAction):
    
    @property
    def action_type(self) -> str:
        return "action.condition"
    
    @property
    def config_schema(self) -> dict:
        return {
            "properties": {
                "left": {"type": "string", "description": "Template: {{trigger.event}}"},
                "operator": {
                    "type": "string",
                    "enum": ["equals", "not_equals", "contains", "not_contains", "is_empty", "is_not_empty"],
                },
                "right": {"type": "string", "description": "Giá trị so sánh"},
            }
        }
    
    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        left = self.resolve_template(config.get("left", ""), context)
        operator = config.get("operator", "equals")
        right = config.get("right", "")
        
        result = self._evaluate(left, operator, right)
        
        return ActionResult(
            success=True,
            output={"condition_result": result, "branch": "true" if result else "false"}
        )
    
    def _evaluate(self, left: str, operator: str, right: str) -> bool:
        if operator == "equals":
            return left == right
        elif operator == "not_equals":
            return left != right
        elif operator == "contains":
            return right in left
        elif operator == "not_contains":
            return right not in left
        elif operator == "is_empty":
            return not left
        elif operator == "is_not_empty":
            return bool(left)
        return False
```

---

# PHẦN B — PHASE 6: POLISH & TESTING

## B.1 Demo Scenarios — Cần test được 3 scenarios này

### Scenario 1: "Auto-summarize khi note mới"

```
Trigger: note.created
    ↓
Action: call_ai
  prompt: "Tóm tắt note này trong 2 câu: {{trigger.content}}"
  output_key: "summary"
    ↓
Action: send_notification
  title: "Note đã được tóm tắt"
  message: "{{steps.step2.summary}}"
```

**Test**: Tạo một note trong Cortex → 30 giây sau nhận được notification với summary.

### Scenario 2: "Reminder trước lịch 1 tiếng"

```
Trigger: schedule.due_soon (filter: minutes_before=60)
    ↓
Action: send_notification
  title: "Sắp đến lịch: {{trigger.schedule_title}}"
  message: "Còn 60 phút nữa — {{trigger.schedule_description}}"
```

**Test**: Tạo một schedule 61 phút từ bây giờ → 1 phút sau nhận notification.

> **Lưu ý implement**: `schedule.due_soon` trigger cần một scheduler chạy mỗi phút để check schedules sắp đến hạn. Implement bằng Temporal cron workflow:

```python
# workflow_service/app/temporal/workflows/schedule_checker.py

@workflow.defn(name="ScheduleCheckerWorkflow")
class ScheduleCheckerWorkflow:
    """Chạy mỗi phút, check schedules sắp đến hạn và publish events"""
    
    @workflow.run
    async def run(self):
        while True:
            await workflow.sleep(timedelta(minutes=1))
            await workflow.execute_activity(
                check_due_schedules,
                start_to_close_timeout=timedelta(seconds=30),
            )
```

### Scenario 3: "Webhook từ Google → tạo note"

```
Trigger: webhook
    ↓
Action: call_ai
  prompt: "Phân tích data này và tóm tắt: {{trigger.payload}}"
  output_key: "analysis"
    ↓
Action: create_note
  title: "Analysis từ webhook {{trigger.headers.X-Source}}"
  content: "{{steps.step2.analysis}}"
```

**Test**: `curl -X POST http://localhost:8001/api/v1/webhooks/{path} -d '{"data":"test"}'` → note được tạo trong Cortex.

---

## B.2 Execution History UI

**`frontend/src/pages/workflows/[id]/executions.tsx`**

```tsx
import React from 'react';
import { useParams } from 'react-router-dom';
import { useExecutions } from '../../../hooks/workflow/useExecutions';

const STATUS_COLORS = {
  pending: 'bg-gray-100 text-gray-600',
  running: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  cancelled: 'bg-yellow-100 text-yellow-700',
};

export function WorkflowExecutionsPage() {
  const { id } = useParams<{ id: string }>();
  const { instances, loading } = useExecutions(id!);
  
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold text-gray-900 mb-4">Lịch sử thực thi</h1>
      
      {loading ? (
        <div className="text-gray-500">Đang tải...</div>
      ) : instances.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <div className="text-4xl mb-2">📋</div>
          <div>Chưa có lần chạy nào</div>
        </div>
      ) : (
        <div className="space-y-3">
          {instances.map(instance => (
            <div key={instance.id} className="bg-white border border-gray-200 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[instance.status]}`}>
                  {instance.status}
                </span>
                <span className="text-xs text-gray-500">
                  {new Date(instance.created_at).toLocaleString('vi-VN')}
                </span>
              </div>
              
              {/* Step timeline */}
              <div className="space-y-1 mt-3">
                {instance.steps.map(step => (
                  <div key={step.id} className="flex items-center gap-2 text-xs">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                      step.status === 'completed' ? 'bg-green-500' :
                      step.status === 'failed' ? 'bg-red-500' :
                      step.status === 'running' ? 'bg-blue-500' : 'bg-gray-300'
                    }`} />
                    <span className="text-gray-600">{step.node_type}</span>
                    {step.error_message && (
                      <span className="text-red-500 truncate">{step.error_message}</span>
                    )}
                  </div>
                ))}
              </div>
              
              {/* Temporal link */}
              {instance.temporal_workflow_id && (
                <a
                  href={`http://localhost:8080/namespaces/default/workflows/${instance.temporal_workflow_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-500 hover:underline mt-2 inline-block"
                >
                  Xem trong Temporal UI →
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

---

## B.3 Testing Plan

### Unit Tests — workflow_service

```python
# workflow_service/tests/test_actions.py

import pytest
from app.actions.builtin.create_note import CreateNoteAction
from app.actions.base import ActionContext

@pytest.mark.asyncio
async def test_create_note_template_resolution():
    action = CreateNoteAction()
    
    context = ActionContext(
        user_id="user-123",
        workflow_id="wf-456",
        instance_id="inst-789",
        node_id="node-1",
        trigger_data={"event": "note.created", "title": "Test Note"},
        previous_outputs={},
    )
    
    config = {"title": "Copy of: {{trigger.title}}"}
    
    # Test template resolution
    resolved = action.resolve_template(config["title"], context)
    assert resolved == "Copy of: Test Note"

@pytest.mark.asyncio
async def test_action_registry():
    from app.actions.registry import action_registry
    from app.actions import *  # trigger registration
    
    assert action_registry.get("action.create_note") is not None
    assert action_registry.get("action.send_notification") is not None
    assert action_registry.get("action.call_ai") is not None

def test_topological_sort():
    from app.temporal.workflows.cortex_workflow import CortexWorkflow
    
    wf = CortexWorkflow()
    nodes = [
        {"id": "node-2", "type": "action.send_notification"},
        {"id": "node-1", "type": "action.create_note"},
    ]
    edges = [
        {"source": "trigger-1", "target": "node-1"},
        {"source": "node-1", "target": "node-2"},
    ]
    
    sorted_nodes = wf._topological_sort(nodes, edges)
    assert sorted_nodes[0]["id"] == "node-1"
    assert sorted_nodes[1]["id"] == "node-2"
```

### Integration Test — End-to-End

```bash
#!/bin/bash
# scripts/test_e2e.sh

BASE_URL="http://localhost:8001"
TOKEN="your-jwt-token-here"

echo "=== E2E Test: Manual Trigger ==="

# 1. Tạo workflow
WORKFLOW=$(curl -s -X POST "$BASE_URL/api/v1/workflows" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "E2E Test Workflow",
    "trigger_type": "manual",
    "trigger_config": {},
    "definition": {
      "nodes": [
        {
          "id": "trigger-1",
          "type": "triggerNode",
          "position": {"x": 100, "y": 100},
          "data": {"label": "Manual", "nodeType": "trigger.manual", "config": {}, "isConfigured": true}
        },
        {
          "id": "action-1",
          "type": "actionNode",
          "position": {"x": 100, "y": 250},
          "data": {"label": "Gửi notification", "nodeType": "action.send_notification", "config": {"title": "Test OK", "message": "E2E test passed"}, "isConfigured": true}
        }
      ],
      "edges": [{"id": "e1", "source": "trigger-1", "target": "action-1"}],
      "variables": {}
    }
  }')

WORKFLOW_ID=$(echo $WORKFLOW | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "Created workflow: $WORKFLOW_ID"

# 2. Activate
curl -s -X POST "$BASE_URL/api/v1/workflows/$WORKFLOW_ID/activate" \
  -H "Authorization: Bearer $TOKEN"
echo "Activated"

# 3. Trigger
curl -s -X POST "$BASE_URL/api/v1/workflows/$WORKFLOW_ID/trigger" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input_data": {}}'
echo "Triggered"

# 4. Wait và check
sleep 10
INSTANCES=$(curl -s "$BASE_URL/api/v1/workflows/$WORKFLOW_ID/executions" \
  -H "Authorization: Bearer $TOKEN")
echo "Executions: $INSTANCES"
```

---

## B.4 Monitoring — Prometheus Metrics

Thêm metrics vào workflow_service:

```python
# workflow_service/app/core/metrics.py

from prometheus_client import Counter, Histogram, Gauge

workflow_triggers_total = Counter(
    "workflow_triggers_total",
    "Total number of workflow triggers",
    ["trigger_type", "status"]
)

workflow_execution_duration = Histogram(
    "workflow_execution_duration_seconds",
    "Workflow execution duration in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300]
)

active_workflows_gauge = Gauge(
    "active_workflows_total",
    "Number of active workflows"
)

# Dùng trong code:
# workflow_triggers_total.labels(trigger_type="internal_event", status="success").inc()
```

---

## B.5 Final Checklist — Project Complete

### Infrastructure

- [ ] `docker-compose up` khởi động toàn bộ 14 services không error
- [ ] Temporal UI hiện tại `http://localhost:8080`
- [ ] workflow_service health check OK
- [ ] Tất cả migrations đã chạy

### Core Features

- [ ] Tạo, sửa, xóa workflow qua API
- [ ] Visual builder: kéo thả, connect nodes, config panel
- [ ] Save/Load definition từ API
- [ ] Activate/Pause workflow
- [ ] Internal event trigger hoạt động (note.created → workflow chạy)
- [ ] Webhook trigger hoạt động
- [ ] Manual trigger hoạt động
- [ ] Temporal chạy workflow, retry on failure
- [ ] Execution history hiển thị đúng status

### Actions

- [ ] `action.create_note` tạo được note trong Cortex
- [ ] `action.send_notification` gửi được notification realtime
- [ ] `action.call_ai` gọi được Gemini, trả về kết quả
- [ ] `action.wait` delay đúng thời gian
- [ ] Template variables resolve đúng (`{{trigger.xxx}}`, `{{steps.xxx.yyy}}`)

### Demo Scenarios

- [ ] Scenario 1: Note mới → AI summary → Notification
- [ ] Scenario 2: Schedule due → Reminder notification
- [ ] Scenario 3: Webhook → AI analysis → Create note

### Testing

- [ ] Unit tests pass: `pytest workflow_service/tests/`
- [ ] E2E test script chạy thành công
- [ ] Không có memory leak sau 1 giờ chạy

---

## B.6 Known Limitations (chấp nhận được cho graduation project)

Những điểm này **không cần fix** trong scope 2-3 tháng, nhưng nên ghi vào documentation:

1. **Worker trong cùng process**: Worker chạy cùng process với FastAPI (dùng `asyncio.ensure_future`). Production nên tách thành separate container.

2. **Không có branching phức tạp**: Condition node chỉ hỗ trợ true/false. Chưa hỗ trợ switch/case nhiều nhánh.

3. **Không có loop**: Chưa hỗ trợ vòng lặp trong workflow (retry logic là của Temporal, không phải workflow-level loop).

4. **Không có human approval**: Temporal hỗ trợ signal-based human approval nhưng chưa implement UI cho feature này.

5. **Single user context**: Workflow chạy trong context của workflow owner. Chưa hỗ trợ multi-user workflow.

6. **Rate limiting chưa có**: Nếu 1000 events cùng lúc → 1000 workflow instances start cùng lúc. Cần thêm queue/throttle cho production.
