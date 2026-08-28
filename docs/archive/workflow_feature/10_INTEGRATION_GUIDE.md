# INTEGRATION GUIDE
## Kết nối workflow_service với Cortex Backend hiện tại

> **Mục đích**: Hướng dẫn cụ thể những thay đổi cần làm trong Cortex backend (code cũ) để workflow_service hoạt động.  
> **Nguyên tắc**: Thay đổi tối thiểu trong Cortex backend — chỉ thêm, không sửa logic hiện tại.

---

## 1. Tổng quan những gì cần thêm vào Cortex Backend

```
backend/app/
├── services/
│   └── redis/
│       └── event_publisher.py      ← File MỚI — publish events lên Redis
├── api/
│   └── notifications.py            ← THÊM endpoint /internal vào file hiện tại
├── core/
│   └── internal_auth.py            ← File MỚI — verify internal API key
└── __init__.py hoặc startup        ← THÊM Redis publisher init
```

```
frontend/src/
├── config/
│   └── api.ts                      ← THÊM WORKFLOW_API_URL constant
├── hooks/
│   └── useWorkflowApi.ts           ← File MỚI — API calls to workflow_service
└── App.tsx hoặc router
    └── routes                      ← THÊM /workflows routes
```

---

## 2. Cortex Backend — event_publisher.py

Tạo file mới. Không sửa bất kỳ file nào hiện tại ở bước này.

**`backend/app/services/redis/event_publisher.py`**

```python
"""
Event publisher: publish events lên Redis Pub/Sub để workflow_service nhận.
Gọi hàm publish_workflow_event() sau mỗi operation quan trọng.
"""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

WORKFLOW_EVENT_CHANNEL = "cortex:workflow:events"

async def publish_workflow_event(
    redis_client,
    event_type: str,
    user_id: str,
    data: dict,
    workspace_id: str | None = None,
) -> bool:
    """
    Publish một event lên Redis channel.
    
    Args:
        redis_client: Redis async client instance
        event_type: Loại event, ví dụ "note.created"
        user_id: UUID của user thực hiện hành động
        data: Dữ liệu cụ thể của event
        workspace_id: UUID của workspace (nếu có)
    
    Returns:
        True nếu publish thành công, False nếu có lỗi
    
    Example:
        await publish_workflow_event(
            redis,
            "note.created",
            str(note.user_id),
            {"note_id": str(note.id), "title": note.title, "content": note.content},
            workspace_id=str(note.workspace_id) if note.workspace_id else None,
        )
    """
    try:
        payload = json.dumps({
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "workspace_id": workspace_id,
            "data": data,
        }, ensure_ascii=False)
        
        await redis_client.publish(WORKFLOW_EVENT_CHANNEL, payload)
        logger.debug(f"[EventPublisher] Published {event_type} for user {user_id}")
        return True
    
    except Exception as e:
        # QUAN TRỌNG: Không raise exception — lỗi publish không được làm fail request chính
        logger.error(f"[EventPublisher] Failed to publish {event_type}: {e}")
        return False
```

---

## 3. Cortex Backend — Thêm publish vào từng Service

### 3.1 NoteService

Mở file `backend/app/services/note_service.py` (hoặc tên tương đương).

Tìm method `create_note` (hoặc tương đương), thêm publish SAU KHI note đã được commit vào DB:

```python
# Trong NoteService.create_note() — THÊM vào cuối, SAU await db.commit()

from app.services.redis.event_publisher import publish_workflow_event

# Đã có code tạo note và commit ở đây...
# await db.commit()  ← code cũ

# THÊM đoạn này sau commit:
try:
    # Lấy redis_client từ dependency injection hoặc global
    # (tùy theo cách Cortex hiện tại inject redis)
    await publish_workflow_event(
        redis_client=redis_client,
        event_type="note.created",
        user_id=str(note.user_id),
        data={
            "note_id": str(note.id),
            "title": note.title or "",
            "content": note.content or "",
            "created_at": note.created_at.isoformat() if note.created_at else None,
        },
        workspace_id=str(note.workspace_id) if note.workspace_id else None,
    )
except Exception:
    pass  # Không làm fail note creation nếu publish lỗi
```

Tương tự cho `update_note` và `delete_note`:

```python
# Sau update note commit → publish "note.updated"
await publish_workflow_event(
    redis_client, "note.updated", str(note.user_id),
    {"note_id": str(note.id), "title": note.title or "", "updated_fields": list(updated_data.keys())},
    workspace_id=str(note.workspace_id) if note.workspace_id else None,
)

# Sau delete note → publish "note.deleted"
await publish_workflow_event(
    redis_client, "note.deleted", str(note.user_id),
    {"note_id": str(note.id)},
)
```

### 3.2 ScheduleService

```python
# Sau create schedule commit → publish "schedule.created"
await publish_workflow_event(
    redis_client, "schedule.created", str(schedule.user_id),
    {
        "schedule_id": str(schedule.id),
        "title": schedule.title or "",
        "start_time": schedule.start_time.isoformat() if schedule.start_time else None,
        "end_time": schedule.end_time.isoformat() if schedule.end_time else None,
        "type": schedule.schedule_type or "event",
    },
)

# Sau update schedule → publish "schedule.updated"
await publish_workflow_event(
    redis_client, "schedule.updated", str(schedule.user_id),
    {"schedule_id": str(schedule.id), "title": schedule.title or ""},
)

# Sau complete schedule → publish "schedule.completed"
await publish_workflow_event(
    redis_client, "schedule.completed", str(schedule.user_id),
    {"schedule_id": str(schedule.id), "title": schedule.title or "", "completed_at": datetime.utcnow().isoformat()},
)
```

### 3.3 AssetService (OCR/STT)

```python
# Sau upload asset → publish "asset.uploaded"
await publish_workflow_event(
    redis_client, "asset.uploaded", str(asset.user_id),
    {
        "asset_id": str(asset.id),
        "filename": asset.filename or "",
        "file_type": asset.file_type or "",
        "size_bytes": asset.size_bytes or 0,
    },
    workspace_id=str(asset.workspace_id) if asset.workspace_id else None,
)

# Sau OCR/STT processing done → publish "asset.processed"
await publish_workflow_event(
    redis_client, "asset.processed", str(asset.user_id),
    {
        "asset_id": str(asset.id),
        "processing_type": "ocr",  # hoặc "stt"
        "status": "completed",
    },
)
```

---

## 4. Cortex Backend — Internal Auth Middleware

Workflow_service gọi Cortex backend qua internal endpoints. Cần verify API key.

**`backend/app/core/internal_auth.py`** (file mới)

```python
from fastapi import Header, HTTPException, status
from app.config import settings  # hoặc tên config class của Cortex

async def verify_internal_api_key(
    x_internal_api_key: str = Header(..., alias="X-Internal-API-Key")
):
    """
    Dependency để protect internal endpoints.
    Chỉ workflow_service (và các services nội bộ khác) mới biết key này.
    """
    if x_internal_api_key != settings.internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key"
        )
```

Thêm vào `.env` của Cortex:

```env
INTERNAL_API_KEY=your-random-secret-key-here-min-32-chars
```

---

## 5. Cortex Backend — Internal Notification Endpoint

Workflow_service cần endpoint để gửi notification vào Cortex.

Mở file `backend/app/api/notifications.py` (hoặc tương đương), thêm route mới:

```python
# THÊM vào file notifications.py hiện tại

from app.core.internal_auth import verify_internal_api_key

@router.post("/internal", include_in_schema=False)
async def create_notification_internal(
    data: dict,
    db: AsyncSession = Depends(get_async_db),
    _: None = Depends(verify_internal_api_key),  # Auth check
):
    """
    Internal endpoint cho workflow_service gửi notification.
    Không expose trong Swagger docs (include_in_schema=False).
    """
    user_id = data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    
    # Tạo notification trong DB
    # (dùng model/schema hiện tại của Cortex)
    notification = Notification(
        user_id=user_id,
        title=data.get("title", ""),
        message=data.get("message", ""),
        type=data.get("type", "info"),
        is_read=False,
        source=data.get("source", "workflow"),
        source_id=data.get("source_id"),
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    
    # Push realtime qua SSE nếu Cortex có SSE manager
    # (uncomment nếu có sse_manager trong scope)
    # await sse_manager.send_to_user(str(user_id), {
    #     "type": "notification",
    #     "data": {"id": str(notification.id), "title": notification.title, ...}
    # })
    
    return {"id": str(notification.id), "status": "created"}
```

> **Note**: Endpoint path cuối cùng phụ thuộc vào router prefix của Cortex. Nếu notifications router có prefix `/api/notifications`, thì full path là `/api/notifications/internal`. Cập nhật `settings.cortex_backend_url` trong workflow_service cho đúng.

---

## 6. Cortex Backend — AI Completion Endpoint (cho action.call_ai)

Workflow_service cần endpoint để gọi AI mà không cần conversation context.

Thêm vào `backend/app/api/agent.py` hoặc tạo file mới:

```python
# THÊM endpoint này vào agent router

from app.core.internal_auth import verify_internal_api_key

@router.post("/complete", include_in_schema=False)
async def ai_complete_internal(
    data: dict,
    _: None = Depends(verify_internal_api_key),
    x_user_id: str = Header(..., alias="X-User-ID"),
):
    """
    Internal endpoint: one-shot AI completion không cần conversation context.
    Dùng bởi workflow_service cho action.call_ai.
    """
    prompt = data.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    
    # Dùng ModelClient hiện tại của Cortex
    # (điều chỉnh theo cách ModelClient được inject trong Cortex)
    model_client = ...  # lấy từ dependency injection
    
    try:
        response = await model_client.generate_content(
            prompt=prompt,
            stream=False,
        )
        return {
            "content": response.text,
            "model": response.model_used,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")
```

---

## 7. Frontend — Thêm Workflow Service URL

**`frontend/src/config/api.ts`** (hoặc nơi Cortex lưu API config)

```typescript
// Thêm constant này vào file config hiện tại
export const WORKFLOW_API_BASE = 
  import.meta.env.VITE_WORKFLOW_API_URL ?? "http://localhost:8001/api/v1";
```

**`frontend/.env`** (và `.env.example`):

```env
VITE_WORKFLOW_API_URL=http://localhost:8001/api/v1
```

---

## 8. Frontend — useWorkflowApi Hook

**`frontend/src/hooks/workflow/useWorkflowApi.ts`**

```typescript
import { WORKFLOW_API_BASE } from '../../config/api';
import type { Workflow, WorkflowListResponse, ActionDefinition } from '../../types/workflow';

/**
 * Hook cung cấp tất cả API calls đến workflow_service.
 * Tự động lấy auth token từ Cortex (localStorage hoặc Zustand auth store).
 */
export function useWorkflowApi() {
  
  // Lấy token từ Cortex auth store
  // Điều chỉnh theo cách Cortex lưu auth token
  const getToken = (): string => {
    // Ví dụ nếu Cortex lưu trong localStorage:
    return localStorage.getItem('access_token') ?? '';
    // Hoặc nếu dùng Zustand:
    // return useAuthStore.getState().accessToken ?? '';
  };
  
  const authHeaders = () => ({
    'Authorization': `Bearer ${getToken()}`,
    'Content-Type': 'application/json',
  });
  
  const handleResponse = async <T>(res: Response): Promise<T> => {
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    if (res.status === 204) return null as T;
    return res.json();
  };
  
  return {
    fetchWorkflows: async (page = 1, pageSize = 20): Promise<WorkflowListResponse | null> => {
      try {
        const res = await fetch(
          `${WORKFLOW_API_BASE}/workflows?page=${page}&page_size=${pageSize}`,
          { headers: authHeaders() }
        );
        return handleResponse<WorkflowListResponse>(res);
      } catch (e) {
        console.error('[WorkflowAPI] fetchWorkflows:', e);
        return null;
      }
    },
    
    fetchWorkflow: async (id: string): Promise<Workflow | null> => {
      try {
        const res = await fetch(`${WORKFLOW_API_BASE}/workflows/${id}`, { headers: authHeaders() });
        return handleResponse<Workflow>(res);
      } catch (e) {
        console.error('[WorkflowAPI] fetchWorkflow:', e);
        return null;
      }
    },
    
    createWorkflow: async (data: object): Promise<Workflow | null> => {
      try {
        const res = await fetch(`${WORKFLOW_API_BASE}/workflows`, {
          method: 'POST',
          headers: authHeaders(),
          body: JSON.stringify(data),
        });
        return handleResponse<Workflow>(res);
      } catch (e) {
        console.error('[WorkflowAPI] createWorkflow:', e);
        return null;
      }
    },
    
    saveWorkflow: async (id: string, definition: object): Promise<Workflow | null> => {
      try {
        const res = await fetch(`${WORKFLOW_API_BASE}/workflows/${id}`, {
          method: 'PATCH',
          headers: authHeaders(),
          body: JSON.stringify({ definition }),
        });
        return handleResponse<Workflow>(res);
      } catch (e) {
        console.error('[WorkflowAPI] saveWorkflow:', e);
        return null;
      }
    },
    
    activateWorkflow: async (id: string): Promise<Workflow | null> => {
      try {
        const res = await fetch(`${WORKFLOW_API_BASE}/workflows/${id}/activate`, {
          method: 'POST',
          headers: authHeaders(),
        });
        return handleResponse<Workflow>(res);
      } catch (e) {
        console.error('[WorkflowAPI] activateWorkflow:', e);
        return null;
      }
    },
    
    pauseWorkflow: async (id: string): Promise<Workflow | null> => {
      try {
        const res = await fetch(`${WORKFLOW_API_BASE}/workflows/${id}/pause`, {
          method: 'POST',
          headers: authHeaders(),
        });
        return handleResponse<Workflow>(res);
      } catch (e) {
        console.error('[WorkflowAPI] pauseWorkflow:', e);
        return null;
      }
    },
    
    triggerManual: async (id: string, inputData: object): Promise<{ status: string } | null> => {
      try {
        const res = await fetch(`${WORKFLOW_API_BASE}/workflows/${id}/trigger`, {
          method: 'POST',
          headers: authHeaders(),
          body: JSON.stringify({ input_data: inputData }),
        });
        return handleResponse<{ status: string }>(res);
      } catch (e) {
        console.error('[WorkflowAPI] triggerManual:', e);
        return null;
      }
    },
    
    fetchActions: async (): Promise<{ actions: ActionDefinition[]; triggers: ActionDefinition[] } | null> => {
      try {
        const res = await fetch(`${WORKFLOW_API_BASE}/actions`, { headers: authHeaders() });
        return handleResponse(res);
      } catch (e) {
        console.error('[WorkflowAPI] fetchActions:', e);
        return null;
      }
    },
    
    fetchExecutions: async (workflowId: string, page = 1) => {
      try {
        const res = await fetch(
          `${WORKFLOW_API_BASE}/workflows/${workflowId}/executions?page=${page}`,
          { headers: authHeaders() }
        );
        return handleResponse(res);
      } catch (e) {
        console.error('[WorkflowAPI] fetchExecutions:', e);
        return null;
      }
    },
  };
}
```

---

## 9. Docker Compose — File đầy đủ với integration

Thêm vào `.env` root của Cortex project:

```env
# --- Workflow Service ---
WORKFLOW_SERVICE_PORT=8001
INTERNAL_API_KEY=change-me-to-random-32-char-secret

# --- Temporal ---
TEMPORAL_PORT=7233
TEMPORAL_UI_PORT=8080
```

Trong `docker-compose.yml`, đảm bảo workflow_service được thêm vào cùng network với Cortex backend:

```yaml
# Kiểm tra tên network hiện tại của Cortex, thêm workflow services vào đó
# Nếu Cortex dùng network tên "cortex-network":

services:
  workflow_service:
    networks:
      - cortex-network   # ← Phải cùng network với backend và redis
  
  temporal:
    networks:
      - cortex-network
  
  temporal-postgresql:
    networks:
      - cortex-network
  
  temporal-ui:
    networks:
      - cortex-network
```

---

## 10. Environment Variables — Tổng hợp

### workflow_service `.env`

```env
# Database (dùng chung với Cortex)
DATABASE_URL=postgresql+asyncpg://cortex_user:cortex_pass@cortex-postgres:5432/cortex_db

# Temporal
TEMPORAL_HOST=temporal:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=cortex-workflow-queue

# Cortex Backend
CORTEX_BACKEND_URL=http://backend:8000
CORTEX_INTERNAL_API_KEY=change-me-to-random-32-char-secret

# Redis (dùng chung với Cortex)
REDIS_URL=redis://redis:6379

# Security (PHẢI giống hệt với Cortex backend)
JWT_SECRET_KEY=same-as-cortex-backend-jwt-secret
JWT_ALGORITHM=HS256

# Service
SERVICE_PORT=8001
DEBUG=false
```

### Cortex backend `.env` — thêm vào

```env
# Thêm vào .env hiện tại của Cortex:
INTERNAL_API_KEY=change-me-to-random-32-char-secret
```

---

## 11. Verification — Integration Checklist

### Step 1: Cortex backend publish events

```bash
# Kiểm tra event được publish khi tạo note
# Terminal 1: Subscribe Redis channel
redis-cli subscribe cortex:workflow:events

# Terminal 2: Tạo note qua Cortex API
curl -X POST http://localhost:8000/api/notes \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Test note", "content": "Hello world"}'

# Kỳ vọng: Terminal 1 hiện message JSON với event="note.created"
```

### Step 2: workflow_service nhận event

```bash
# Kiểm tra workflow_service log
docker logs workflow_service | grep "TriggerEngine"

# Kỳ vọng: "[TriggerEngine] Listening on Redis channel: cortex:workflow:events"
# Sau khi tạo note: "[TriggerEngine] Triggered workflow ... for event note.created"
```

### Step 3: Internal notification

```bash
# Gọi trực tiếp endpoint internal
curl -X POST http://localhost:8000/api/notifications/internal \
  -H "X-Internal-API-Key: your-internal-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "your-user-uuid",
    "title": "Test từ workflow",
    "message": "Integration test OK",
    "type": "success"
  }'

# Kỳ vọng: 200 OK với notification ID
# Kiểm tra trong Cortex UI: notification xuất hiện
```

### Step 4: End-to-end

```bash
# 1. Tạo workflow với trigger note.created + action send_notification
# 2. Activate workflow
# 3. Tạo note mới trong Cortex
# 4. Chờ ~3-5 giây
# 5. Kiểm tra notification xuất hiện trong Cortex

# Kỳ vọng: Notification xuất hiện trong vòng 5 giây sau khi tạo note
```
