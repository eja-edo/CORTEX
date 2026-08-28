# PHASE 6 — POLISH & TESTING
## Final QA + Monitoring + Demo Preparation

> **Thời gian**: Tuần 11–12 (10 ngày làm việc)  
> **Prerequisite**: Phase 3 + Phase 4 + Phase 5 hoàn thành  
> **Mục tiêu**: Workflow Runtime production-ready cho demo, có monitoring, có test coverage  
> **Output cuối phase**: Demo được 3 scenarios, tests pass, monitoring dashboard hoạt động

---

## 1. Tổng quan công việc Phase 6

```
Tuần 11                             Tuần 12
─────────────────────────────────── ───────────────────────────────────
Day 1-2: Unit tests                 Day 6-7: Demo scenario setup
Day 3:   Integration tests          Day 8:   Performance check
Day 4-5: UI polish + error states   Day 9-10: Documentation + final QA
```

---

## 2. Unit Tests — workflow_service

### 2.1 Setup pytest

```
workflow_service/
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_actions.py
    ├── test_trigger_engine.py
    ├── test_workflow_api.py
    └── test_temporal_workflow.py
```

**`tests/conftest.py`**

```python
import pytest
import asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.main import app
from app.database import Base, get_db
from app.config import settings

# Test database (dùng SQLite in-memory cho unit test)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="function")
async def test_db():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    TestingSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with TestingSessionLocal() as session:
        yield session
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()

@pytest.fixture
async def client(test_db):
    async def override_get_db():
        yield test_db
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()

# Mock JWT token cho test
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_EMAIL = "test@cortex.dev"

def make_test_token() -> str:
    from jose import jwt
    return jwt.encode(
        {"sub": TEST_USER_ID, "email": TEST_USER_EMAIL},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )

@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {make_test_token()}"}
```

### 2.2 `tests/test_actions.py`

```python
import pytest
from app.actions.builtin.create_note import CreateNoteAction
from app.actions.builtin.send_notification import SendNotificationAction
from app.actions.builtin.condition import ConditionAction
from app.actions.base import ActionContext
from app.actions.registry import action_registry
import app.actions  # trigger registration

def make_context(**kwargs) -> ActionContext:
    defaults = dict(
        user_id="user-123",
        workflow_id="wf-456",
        instance_id="inst-789",
        node_id="node-1",
        trigger_data={"event": "note.created", "title": "Test Note", "note_id": "note-abc"},
        previous_outputs={},
    )
    defaults.update(kwargs)
    return ActionContext(**defaults)

# --- Template Resolution ---
def test_template_resolve_trigger_field():
    action = CreateNoteAction()
    ctx = make_context()
    result = action.resolve_template("Created: {{trigger.title}}", ctx)
    assert result == "Created: Test Note"

def test_template_resolve_nested_field():
    action = CreateNoteAction()
    ctx = make_context(trigger_data={"event": "note.created", "user": {"name": "Alice"}})
    result = action.resolve_template("Hello {{trigger.user.name}}", ctx)
    assert result == "Hello Alice"

def test_template_resolve_previous_step():
    action = SendNotificationAction()
    ctx = make_context(previous_outputs={"node-ai": {"summary": "Key points..."}})
    result = action.resolve_template("Summary: {{steps.node-ai.summary}}", ctx)
    assert result == "Summary: Key points..."

def test_template_resolve_missing_var():
    action = CreateNoteAction()
    ctx = make_context()
    result = action.resolve_template("Hello {{trigger.nonexistent}}", ctx)
    assert result == "Hello "  # Missing var = empty string, no crash

# --- Action Registry ---
def test_action_registry_has_builtins():
    assert action_registry.get("action.create_note") is not None
    assert action_registry.get("action.send_notification") is not None
    assert action_registry.get("action.call_ai") is not None
    assert action_registry.get("action.wait") is not None
    assert action_registry.get("action.condition") is not None

def test_action_registry_list_all():
    actions = action_registry.list_all()
    action_types = [a["type"] for a in actions]
    assert "action.create_note" in action_types
    assert "action.send_notification" in action_types

# --- Condition Action ---
@pytest.mark.asyncio
async def test_condition_equals_true():
    action = ConditionAction()
    ctx = make_context(trigger_data={"event": "note.created"})
    result = await action.execute(
        {"left": "{{trigger.event}}", "operator": "equals", "right": "note.created"},
        ctx
    )
    assert result.success is True
    assert result.output["condition_result"] is True
    assert result.output["branch"] == "true"

@pytest.mark.asyncio
async def test_condition_equals_false():
    action = ConditionAction()
    ctx = make_context(trigger_data={"event": "note.updated"})
    result = await action.execute(
        {"left": "{{trigger.event}}", "operator": "equals", "right": "note.created"},
        ctx
    )
    assert result.output["condition_result"] is False
    assert result.output["branch"] == "false"

@pytest.mark.asyncio
async def test_condition_contains():
    action = ConditionAction()
    ctx = make_context(trigger_data={"title": "Meeting notes for Q4"})
    result = await action.execute(
        {"left": "{{trigger.title}}", "operator": "contains", "right": "Q4"},
        ctx
    )
    assert result.output["condition_result"] is True

@pytest.mark.asyncio
async def test_condition_is_empty():
    action = ConditionAction()
    ctx = make_context(trigger_data={"content": ""})
    result = await action.execute(
        {"left": "{{trigger.content}}", "operator": "is_empty"},
        ctx
    )
    assert result.output["condition_result"] is True
```

### 2.3 `tests/test_workflow_api.py`

```python
import pytest

SAMPLE_DEFINITION = {
    "nodes": [
        {
            "id": "trigger-1",
            "type": "triggerNode",
            "position": {"x": 100, "y": 100},
            "data": {
                "label": "Manual",
                "nodeType": "trigger.manual",
                "config": {},
                "isConfigured": True
            }
        },
        {
            "id": "action-1",
            "type": "actionNode",
            "position": {"x": 100, "y": 250},
            "data": {
                "label": "Send Notification",
                "nodeType": "action.send_notification",
                "config": {"title": "Test", "message": "Hello"},
                "isConfigured": True
            }
        }
    ],
    "edges": [{"id": "e1", "source": "trigger-1", "target": "action-1"}],
    "variables": {}
}

@pytest.mark.asyncio
async def test_create_workflow(client, auth_headers):
    response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "Test Workflow",
            "trigger_type": "manual",
            "trigger_config": {},
            "definition": SAMPLE_DEFINITION,
        },
        headers=auth_headers
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Workflow"
    assert data["status"] == "draft"
    assert data["version"] == 1

@pytest.mark.asyncio
async def test_get_workflow(client, auth_headers):
    # Create first
    create_resp = await client.post(
        "/api/v1/workflows",
        json={"name": "WF", "trigger_type": "manual", "trigger_config": {}, "definition": SAMPLE_DEFINITION},
        headers=auth_headers
    )
    wf_id = create_resp.json()["id"]
    
    # Get
    get_resp = await client.get(f"/api/v1/workflows/{wf_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == wf_id

@pytest.mark.asyncio
async def test_list_workflows_pagination(client, auth_headers):
    # Create 3 workflows
    for i in range(3):
        await client.post(
            "/api/v1/workflows",
            json={"name": f"WF {i}", "trigger_type": "manual", "trigger_config": {}, "definition": SAMPLE_DEFINITION},
            headers=auth_headers
        )
    
    resp = await client.get("/api/v1/workflows?page=1&page_size=2", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] >= 3

@pytest.mark.asyncio
async def test_activate_workflow_without_trigger_node_fails(client, auth_headers):
    # Workflow chỉ có action node, không có trigger → activate phải fail
    create_resp = await client.post(
        "/api/v1/workflows",
        json={
            "name": "No Trigger WF",
            "trigger_type": "manual",
            "trigger_config": {},
            "definition": {
                "nodes": [{"id": "a-1", "type": "actionNode", "position": {"x": 0, "y": 0}, "data": {"label": "X", "nodeType": "action.send_notification", "config": {}, "isConfigured": True}}],
                "edges": [],
                "variables": {}
            }
        },
        headers=auth_headers
    )
    wf_id = create_resp.json()["id"]
    
    activate_resp = await client.post(f"/api/v1/workflows/{wf_id}/activate", headers=auth_headers)
    assert activate_resp.status_code == 400

@pytest.mark.asyncio
async def test_cannot_access_other_user_workflow(client, auth_headers):
    # Create với user A
    create_resp = await client.post(
        "/api/v1/workflows",
        json={"name": "Private WF", "trigger_type": "manual", "trigger_config": {}, "definition": SAMPLE_DEFINITION},
        headers=auth_headers
    )
    wf_id = create_resp.json()["id"]
    
    # User B dùng token khác → phải nhận 404
    from jose import jwt
    from app.config import settings
    other_token = jwt.encode({"sub": "other-user-id", "email": "other@test.com"}, settings.jwt_secret_key)
    other_headers = {"Authorization": f"Bearer {other_token}"}
    
    resp = await client.get(f"/api/v1/workflows/{wf_id}", headers=other_headers)
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_delete_workflow_soft_deletes(client, auth_headers):
    create_resp = await client.post(
        "/api/v1/workflows",
        json={"name": "To Delete", "trigger_type": "manual", "trigger_config": {}, "definition": SAMPLE_DEFINITION},
        headers=auth_headers
    )
    wf_id = create_resp.json()["id"]
    
    # Delete
    del_resp = await client.delete(f"/api/v1/workflows/{wf_id}", headers=auth_headers)
    assert del_resp.status_code == 204
    
    # Get sau khi delete → 404
    get_resp = await client.get(f"/api/v1/workflows/{wf_id}", headers=auth_headers)
    assert get_resp.status_code == 404
```

### 2.4 `tests/test_trigger_engine.py`

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.triggers.internal_event_listener import _matches_filters, _handle_event

def test_matches_filters_empty():
    assert _matches_filters({"event": "note.created"}, {}) is True

def test_matches_filters_match():
    assert _matches_filters(
        {"event": "note.created", "workspace_id": "ws-123"},
        {"workspace_id": "ws-123"}
    ) is True

def test_matches_filters_no_match():
    assert _matches_filters(
        {"event": "note.created", "workspace_id": "ws-999"},
        {"workspace_id": "ws-123"}
    ) is False

def test_matches_filters_missing_key():
    assert _matches_filters(
        {"event": "note.created"},
        {"workspace_id": "ws-123"}
    ) is False
```

---

## 3. Frontend — Error States & Loading UI

### 3.1 Empty States

```tsx
// frontend/src/pages/workflows/index.tsx — Empty state
{workflows.length === 0 && !loading && (
  <div className="flex flex-col items-center justify-center py-24 text-center">
    <div className="w-16 h-16 bg-gray-100 rounded-2xl flex items-center justify-center mb-4">
      <Workflow className="w-8 h-8 text-gray-400" />
    </div>
    <h3 className="font-semibold text-gray-900 mb-1">Chưa có workflow nào</h3>
    <p className="text-sm text-gray-500 mb-6 max-w-xs">
      Tạo workflow đầu tiên để tự động hóa các tác vụ trong Cortex
    </p>
    <button
      onClick={() => navigate('/workflows/new')}
      className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
    >
      Tạo workflow đầu tiên
    </button>
  </div>
)}
```

### 3.2 Node Validation — Hiển thị lỗi trên Canvas

```tsx
// Thêm vào WorkflowToolbar — validate trước khi activate
const validateWorkflow = () => {
  const errors: string[] = [];
  const triggerNodes = nodes.filter(n => n.type === 'triggerNode');
  const actionNodes = nodes.filter(n => n.type === 'actionNode');
  const unconfiguredNodes = nodes.filter(n => !n.data.isConfigured);
  
  if (triggerNodes.length === 0) errors.push("Cần ít nhất 1 trigger node");
  if (actionNodes.length === 0) errors.push("Cần ít nhất 1 action node");
  if (unconfiguredNodes.length > 0) {
    errors.push(`${unconfiguredNodes.length} node chưa được cấu hình`);
  }
  
  // Check disconnected nodes
  const connectedNodeIds = new Set([
    ...edges.map(e => e.source),
    ...edges.map(e => e.target),
  ]);
  const disconnected = nodes.filter(n => !connectedNodeIds.has(n.id));
  if (disconnected.length > 0) {
    errors.push(`${disconnected.length} node chưa được kết nối`);
  }
  
  return errors;
};
```

### 3.3 Execution Status — Realtime via SSE

Nếu Cortex đã có SSE infrastructure, có thể kết nối để nhận realtime execution updates:

```tsx
// hooks/workflow/useExecutionRealtime.ts
export function useExecutionRealtime(instanceId: string) {
  const [status, setStatus] = useState<ExecutionStatus>('pending');
  
  useEffect(() => {
    // Kết nối vào SSE stream của Cortex
    const es = new EventSource(
      `${WORKFLOW_SERVICE_URL}/api/v1/executions/${instanceId}/stream`,
      { withCredentials: true }
    );
    
    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === 'execution_status') {
        setStatus(data.status);
      }
    };
    
    return () => es.close();
  }, [instanceId]);
  
  return status;
}
```

---

## 4. Monitoring Setup

### 4.1 Prometheus Metrics Endpoint

```python
# workflow_service/app/main.py — thêm metrics endpoint

from prometheus_client import make_asgi_app, Counter, Histogram, Gauge

# Define metrics
workflow_triggers = Counter(
    "workflow_triggers_total",
    "Total workflow trigger events",
    ["trigger_type", "status"]
)

execution_duration = Histogram(
    "workflow_execution_seconds",
    "Workflow execution duration",
    buckets=[1, 5, 10, 30, 60, 300]
)

active_instances = Gauge(
    "workflow_active_instances",
    "Currently running workflow instances"
)

# Mount metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

### 4.2 Structured Logging

```python
# workflow_service/app/core/logging.py

import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "service": "workflow_service",
            "message": record.getMessage(),
            "module": record.module,
        }
        if hasattr(record, "workflow_id"):
            log_data["workflow_id"] = record.workflow_id
        if hasattr(record, "instance_id"):
            log_data["instance_id"] = record.instance_id
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)

def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)
```

---

## 5. Demo Preparation

### 5.1 Demo Script — Scenario 1: Auto-summarize Note

```bash
# Bước 1: Tạo workflow qua API
curl -X POST http://localhost:8001/api/v1/workflows \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Auto Summarize Notes",
    "trigger_type": "internal_event",
    "trigger_config": {"event": "note.created"},
    "definition": {
      "nodes": [
        {"id": "t1", "type": "triggerNode", "position": {"x":100,"y":50},
         "data": {"label":"Note Created","nodeType":"trigger.internal_event",
                  "config":{"event":"note.created"},"isConfigured":true}},
        {"id": "a1", "type": "actionNode", "position": {"x":100,"y":200},
         "data": {"label":"AI Summary","nodeType":"action.call_ai",
                  "config":{"prompt":"Tóm tắt note này trong 2 câu ngắn gọn:\n\nTiêu đề: {{trigger.title}}\nNội dung: {{trigger.content}}","output_key":"summary"},
                  "isConfigured":true}},
        {"id": "a2", "type": "actionNode", "position": {"x":100,"y":350},
         "data": {"label":"Notify","nodeType":"action.send_notification",
                  "config":{"title":"Note đã được tóm tắt: {{trigger.title}}",
                            "message":"{{steps.a1.summary}}","type":"success"},
                  "isConfigured":true}}
      ],
      "edges": [
        {"id":"e1","source":"t1","target":"a1"},
        {"id":"e2","source":"a1","target":"a2"}
      ],
      "variables": {}
    }
  }'
```

### 5.2 Demo Checklist

Trước khi demo, kiểm tra:

- [ ] `docker-compose up` không có error, tất cả services healthy
- [ ] Temporal UI accessible: `http://localhost:8080`
- [ ] workflow_service docs: `http://localhost:8001/docs`
- [ ] Cortex frontend: `http://localhost:3000`
- [ ] 3 demo workflows đã được tạo sẵn (draft, chưa activate — activate live trong demo)
- [ ] Redis đang chạy và pub/sub hoạt động
- [ ] Test token còn hạn (JWT không expired)

### 5.3 Demo Flow (10 phút)

```
1. (1 phút) Mở Cortex → sidebar → click "Workflows"
   → Hiện danh sách workflows

2. (2 phút) Click "Tạo mới" → Workflow Builder mở ra
   → Kéo "Cortex Event" trigger từ palette
   → Kéo "Gọi AI" action
   → Kéo "Gửi Notification" action
   → Connect nodes
   → Configure từng node

3. (1 phút) Click "Lưu" → Click "Activate"
   → Status badge chuyển sang "active"

4. (3 phút) Switch tab → Cortex Notes → Tạo note mới
   → Quay lại Cortex → Notification xuất hiện với AI summary
   → Mở Temporal UI → Hiện execution history chi tiết

5. (2 phút) Mở Execution History trong Workflow UI
   → Click vào execution → Hiện step-by-step timeline
   → Click "Xem trong Temporal UI" → Hiện full event history

6. (1 phút) Q&A
```

---

## 6. Performance Benchmarks

Trước khi demo, chạy quick performance check:

```bash
# Đo thời gian từ trigger → completion cho manual workflow đơn giản
for i in {1..5}; do
  START=$(date +%s%N)
  curl -s -X POST "http://localhost:8001/api/v1/workflows/$WF_ID/trigger" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}' > /dev/null
  # Chờ completion bằng polling
  sleep 5
  END=$(date +%s%N)
  echo "Run $i: $(( (END - START) / 1000000 ))ms"
done
```

**Kỳ vọng**:
- Manual trigger → completion (send_notification): < 3 giây
- Manual trigger → completion (call_ai + send_notification): < 15 giây
- Internal event trigger lag (Redis pub/sub → workflow start): < 500ms

---

## 7. Known Issues & Workarounds

### Issue 1: Temporal worker crash không tự restart

**Triệu chứng**: Workflow trigger nhưng không có execution nào được tạo.

**Kiểm tra**: `docker logs workflow_service | grep "TemporalWorker"`

**Workaround**: `docker restart workflow_service`

**Fix dài hạn**: Tách worker thành container riêng với `restart: always`.

### Issue 2: Redis Pub/Sub miss events khi workflow_service restart

**Triệu chứng**: Events published trong khi service down không được process.

**Kiểm tra**: Check timestamps của events vs service restart time.

**Workaround**: Không có workaround đơn giản. Accept as known limitation.

**Fix dài hạn**: Migrate sang Redis Streams với consumer group + ACK.

### Issue 3: React Flow performance với nhiều nodes

**Triệu chứng**: Canvas lag khi có > 20 nodes.

**Workaround**: Dùng `<ReactFlow nodesDraggable={false}>` khi đang preview.

---

## 8. Final Verification Checklist

### Code Quality

- [ ] Không có `print()` statement trong production code (chỉ dùng `logging`)
- [ ] Không có hardcoded secrets trong code
- [ ] Tất cả API endpoints có authentication
- [ ] Error messages không expose internal implementation details

### Tests

- [ ] `pytest workflow_service/tests/ -v` — tất cả pass
- [ ] Coverage > 60% cho `app/actions/` và `app/api/`

### Infrastructure

- [ ] `docker-compose up` từ fresh start — không error
- [ ] `docker-compose down && docker-compose up` — state được restore đúng

### Demo Scenarios

- [ ] Scenario 1 (Note → AI → Notification): End-to-end < 15s
- [ ] Scenario 2 (Webhook → Create Note): End-to-end < 5s
- [ ] Scenario 3 (Manual → Multi-step): End-to-end < 10s

### Documentation

- [ ] README.md trong `workflow_service/` với quick start guide
- [ ] Tất cả env variables được document trong `.env.example`
