# API CONTRACTS
## Toàn bộ API Endpoints với Request/Response Examples

> **Base URL**: `http://localhost:8001/api/v1`  
> **Auth**: Bearer JWT token (lấy từ Cortex login)  
> **Content-Type**: `application/json`

---

## 1. Workflows

### `POST /workflows` — Tạo workflow mới

**Request**
```http
POST /api/v1/workflows
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "name": "Auto Summarize Notes",
  "description": "Tóm tắt note mới bằng AI",
  "workspace_id": null,
  "trigger_type": "internal_event",
  "trigger_config": {
    "event": "note.created",
    "filters": {}
  },
  "definition": {
    "nodes": [
      {
        "id": "trigger-1",
        "type": "triggerNode",
        "position": { "x": 100, "y": 100 },
        "data": {
          "label": "Note Created",
          "nodeType": "trigger.internal_event",
          "config": { "event": "note.created" },
          "isConfigured": true
        }
      },
      {
        "id": "action-1",
        "type": "actionNode",
        "position": { "x": 100, "y": 280 },
        "data": {
          "label": "AI Summary",
          "nodeType": "action.call_ai",
          "config": {
            "prompt": "Tóm tắt note: {{trigger.title}}",
            "output_key": "summary"
          },
          "isConfigured": true
        }
      }
    ],
    "edges": [
      { "id": "e1", "source": "trigger-1", "target": "action-1" }
    ],
    "variables": {}
  }
}
```

**Response 201**
```json
{
  "id": "3f7b2c1d-4e5f-6g7h-8i9j-0k1l2m3n4o5p",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "workspace_id": null,
  "name": "Auto Summarize Notes",
  "description": "Tóm tắt note mới bằng AI",
  "status": "draft",
  "version": 1,
  "trigger_type": "internal_event",
  "trigger_config": { "event": "note.created", "filters": {} },
  "definition": { "nodes": [...], "edges": [...], "variables": {} },
  "webhook_url": null,
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:00:00Z"
}
```

**Errors**
- `400` — Validation error (name quá dài, trigger_type không hợp lệ)
- `401` — Thiếu hoặc JWT không hợp lệ

---

### `GET /workflows` — Danh sách workflows

**Request**
```http
GET /api/v1/workflows?page=1&page_size=20&status=active&workspace_id=xxx
Authorization: Bearer {jwt_token}
```

**Query Parameters**

| Param | Type | Default | Mô tả |
|-------|------|---------|-------|
| `page` | int | 1 | Trang hiện tại (bắt đầu từ 1) |
| `page_size` | int | 20 | Số items mỗi trang (max 100) |
| `status` | string | null | Filter: draft/active/paused/archived |
| `workspace_id` | UUID | null | Filter theo workspace |

**Response 200**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Auto Summarize Notes",
      "status": "active",
      "trigger_type": "internal_event",
      "version": 1,
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20
}
```

---

### `GET /workflows/{id}` — Chi tiết workflow

**Request**
```http
GET /api/v1/workflows/3f7b2c1d-4e5f-6g7h-8i9j-0k1l2m3n4o5p
Authorization: Bearer {jwt_token}
```

**Response 200** — Giống WorkflowResponse đầy đủ (xem POST response)

**Errors**
- `404` — Workflow không tồn tại hoặc không thuộc user này

---

### `PATCH /workflows/{id}` — Cập nhật workflow

Chỉ truyền những field muốn update (partial update).

**Request**
```http
PATCH /api/v1/workflows/uuid
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "name": "Auto Summarize Notes v2",
  "definition": {
    "nodes": [...updated nodes...],
    "edges": [...],
    "variables": {}
  }
}
```

**Response 200** — WorkflowResponse đã được update

**Note**: Nếu workflow đang ACTIVE và thay đổi `definition`, `version` sẽ tự động tăng lên.

---

### `DELETE /workflows/{id}` — Xóa workflow

Soft delete — workflow bị đánh dấu `is_deleted=true`, không thực sự xóa khỏi DB.

**Request**
```http
DELETE /api/v1/workflows/uuid
Authorization: Bearer {jwt_token}
```

**Response 204** — No content

---

### `POST /workflows/{id}/activate` — Kích hoạt workflow

**Validation trước khi activate**:
- Phải có ít nhất 1 trigger node
- Phải có ít nhất 1 action node
- Tất cả nodes phải được kết nối (không có orphan nodes)

**Request**
```http
POST /api/v1/workflows/uuid/activate
Authorization: Bearer {jwt_token}
```

**Response 200** — WorkflowResponse với `status: "active"`

**Errors**
- `400` — Validation fail (thiếu trigger node, thiếu action node, v.v.)

---

### `POST /workflows/{id}/pause` — Tạm dừng workflow

Workflow pause sẽ không nhận triggers mới. Instances đang chạy vẫn tiếp tục.

**Request**
```http
POST /api/v1/workflows/uuid/pause
Authorization: Bearer {jwt_token}
```

**Response 200** — WorkflowResponse với `status: "paused"`

---

### `POST /workflows/{id}/trigger` — Trigger thủ công

Chỉ hoạt động với workflow đang ở status `active`.

**Request**
```http
POST /api/v1/workflows/uuid/trigger
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "input_data": {
    "custom_key": "custom_value"
  }
}
```

**Response 201**
```json
{
  "status": "triggered",
  "instance_id": "uuid-của-instance-mới"
}
```

**Errors**
- `409` — Workflow không ở trạng thái active

---

## 2. Executions

### `GET /workflows/{id}/executions` — Execution history của workflow

**Request**
```http
GET /api/v1/workflows/uuid/executions?page=1&page_size=20
Authorization: Bearer {jwt_token}
```

**Response 200**
```json
{
  "items": [
    {
      "id": "inst-uuid",
      "workflow_id": "wf-uuid",
      "status": "completed",
      "temporal_workflow_id": "cortex-wf-inst-uuid",
      "trigger_data": {
        "event": "note.created",
        "note_id": "note-uuid",
        "title": "My Note"
      },
      "output": {
        "action-1": { "summary": "Tóm tắt ngắn..." }
      },
      "error_message": null,
      "started_at": "2024-01-15T10:30:01Z",
      "completed_at": "2024-01-15T10:30:08Z",
      "created_at": "2024-01-15T10:30:00Z",
      "steps": []
    }
  ],
  "page": 1
}
```

---

### `GET /executions/{instance_id}` — Chi tiết một execution

Trả về đầy đủ thông tin bao gồm step-by-step logs.

**Request**
```http
GET /api/v1/executions/inst-uuid
Authorization: Bearer {jwt_token}
```

**Response 200**
```json
{
  "id": "inst-uuid",
  "workflow_id": "wf-uuid",
  "status": "completed",
  "temporal_workflow_id": "cortex-wf-inst-uuid",
  "trigger_data": {
    "event": "note.created",
    "note_id": "note-uuid",
    "title": "My Note",
    "content": "Nội dung note..."
  },
  "output": {
    "action-1": { "summary": "Đây là tóm tắt ngắn gọn." },
    "action-2": { "sent": true }
  },
  "error_message": null,
  "started_at": "2024-01-15T10:30:01Z",
  "completed_at": "2024-01-15T10:30:08Z",
  "created_at": "2024-01-15T10:30:00Z",
  "steps": [
    {
      "id": "step-uuid-1",
      "node_id": "action-1",
      "node_type": "action.call_ai",
      "status": "completed",
      "input_data": {
        "prompt": "Tóm tắt note: My Note",
        "output_key": "summary"
      },
      "output_data": { "summary": "Đây là tóm tắt ngắn gọn.", "model_used": "gemini-1.5-flash" },
      "error_message": null,
      "started_at": "2024-01-15T10:30:02Z",
      "completed_at": "2024-01-15T10:30:06Z"
    },
    {
      "id": "step-uuid-2",
      "node_id": "action-2",
      "node_type": "action.send_notification",
      "status": "completed",
      "input_data": { "title": "Note đã được tóm tắt: My Note", "message": "Đây là tóm tắt ngắn gọn.", "type": "success" },
      "output_data": { "sent": true },
      "error_message": null,
      "started_at": "2024-01-15T10:30:06Z",
      "completed_at": "2024-01-15T10:30:07Z"
    }
  ]
}
```

---

### `POST /executions/{instance_id}/cancel` — Hủy execution đang chạy

**Request**
```http
POST /api/v1/executions/inst-uuid/cancel
Authorization: Bearer {jwt_token}
```

**Response 200**
```json
{
  "status": "cancelled"
}
```

**Errors**
- `404` — Instance không tồn tại hoặc chưa start Temporal workflow
- `409` — Instance đã completed hoặc failed

---

## 3. Webhooks

### `POST /webhooks/{webhook_path}` — Nhận webhook từ external

**KHÔNG cần auth header** — dùng webhook secret thay thế.

**Request**
```http
POST /api/v1/webhooks/a3f7b2c1d4e5f6g7h8i9j0k1l2m3n4o5
X-Webhook-Secret: your-secret-here
Content-Type: application/json

{
  "event_type": "push",
  "repository": "my-repo",
  "ref": "refs/heads/main"
}
```

**Response 202**
```json
{
  "status": "accepted",
  "workflow_id": "wf-uuid"
}
```

**Errors**
- `404` — webhook_path không tồn tại hoặc không active
- `401` — X-Webhook-Secret không hợp lệ (chỉ check nếu secret được config)
- `409` — Workflow không ở trạng thái active

**Note về payload**: Toàn bộ body JSON sẽ được accessible trong workflow qua `{{trigger.payload.xxx}}`. Headers accessible qua `{{trigger.headers.xxx}}`.

---

## 4. Actions Catalog

### `GET /actions` — Danh sách tất cả actions và triggers

Dùng để frontend biết có những node types nào để hiển thị trong Node Palette.

**Request**
```http
GET /api/v1/actions
Authorization: Bearer {jwt_token}
```

**Response 200**
```json
{
  "triggers": [
    {
      "type": "trigger.internal_event",
      "display_name": "Cortex Event",
      "description": "Trigger khi có sự kiện trong Cortex",
      "config_schema": {
        "type": "object",
        "required": ["event"],
        "properties": {
          "event": {
            "type": "string",
            "enum": [
              "note.created", "note.updated", "note.deleted",
              "schedule.created", "schedule.updated", "schedule.completed",
              "asset.uploaded", "asset.processed"
            ]
          },
          "filters": { "type": "object" }
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
  ],
  "actions": [
    {
      "type": "action.create_note",
      "display_name": "Tạo Note",
      "description": "Tạo một note mới trong Cortex",
      "config_schema": {
        "type": "object",
        "required": ["title"],
        "properties": {
          "title": { "type": "string", "title": "Tiêu đề" },
          "content": { "type": "string", "title": "Nội dung" },
          "workspace_id": { "type": "string", "title": "Workspace ID" }
        }
      }
    },
    {
      "type": "action.send_notification",
      "display_name": "Gửi Notification",
      "description": "Gửi thông báo đến user trong Cortex",
      "config_schema": {
        "type": "object",
        "required": ["title", "message"],
        "properties": {
          "title": { "type": "string" },
          "message": { "type": "string" },
          "type": {
            "type": "string",
            "enum": ["info", "success", "warning", "error"],
            "default": "info"
          }
        }
      }
    },
    {
      "type": "action.call_ai",
      "display_name": "Gọi AI",
      "description": "Gọi Gemini với prompt tùy chỉnh",
      "config_schema": {
        "type": "object",
        "required": ["prompt"],
        "properties": {
          "prompt": { "type": "string" },
          "output_key": { "type": "string", "default": "ai_result" }
        }
      }
    },
    {
      "type": "action.wait",
      "display_name": "Chờ",
      "description": "Dừng workflow một khoảng thời gian rồi tiếp tục",
      "config_schema": {
        "type": "object",
        "required": ["duration", "unit"],
        "properties": {
          "duration": { "type": "number", "minimum": 1 },
          "unit": { "type": "string", "enum": ["seconds", "minutes", "hours"] }
        }
      }
    },
    {
      "type": "action.condition",
      "display_name": "Điều kiện",
      "description": "Rẽ nhánh workflow dựa vào điều kiện",
      "config_schema": {
        "type": "object",
        "required": ["left", "operator"],
        "properties": {
          "left": { "type": "string" },
          "operator": { "type": "string", "enum": ["equals","not_equals","contains","not_contains","is_empty","is_not_empty"] },
          "right": { "type": "string" }
        }
      }
    }
  ]
}
```

---

## 5. Health Check

### `GET /health` — Service health

```http
GET /health
```

**Response 200**
```json
{
  "status": "ok",
  "service": "workflow_service",
  "temporal_connected": true,
  "redis_connected": true,
  "db_connected": true
}
```

---

## 6. Internal API (Cortex Backend → workflow_service)

> Dùng header `X-Internal-API-Key` thay vì JWT.

### `POST /internal/events` — Publish event từ Cortex Backend

Endpoint này dùng cho Cortex backend publish events trực tiếp qua HTTP thay vì Redis (alternative). Ưu tiên Redis Pub/Sub, endpoint này là fallback.

```http
POST /api/v1/internal/events
X-Internal-API-Key: {internal_api_key}
Content-Type: application/json

{
  "event": "note.created",
  "user_id": "uuid",
  "workspace_id": "uuid",
  "data": {
    "note_id": "uuid",
    "title": "My Note",
    "content": "..."
  }
}
```

**Response 202**
```json
{ "status": "accepted", "matched_workflows": 2 }
```

---

## 7. Error Response Format

Tất cả lỗi đều trả về format chuẩn:

```json
{
  "detail": "Mô tả lỗi bằng tiếng Anh hoặc tiếng Việt",
  "code": "ERROR_CODE",
  "field": "tên_field_nếu_validation_error"
}
```

**HTTP Status Codes**

| Code | Ý nghĩa |
|------|---------|
| 200 | Success (GET, PATCH) |
| 201 | Created (POST tạo mới) |
| 202 | Accepted (async operations) |
| 204 | No Content (DELETE) |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (thiếu hoặc invalid token) |
| 403 | Forbidden (có token nhưng không có quyền) |
| 404 | Not Found |
| 409 | Conflict (workflow không active, v.v.) |
| 422 | Unprocessable Entity (Pydantic validation) |
| 500 | Internal Server Error |

---

## 8. Template Variable Reference

Dùng trong action config fields. Format: `{{scope.path.to.value}}`

### Scopes

```
{{trigger.*}}
  Dữ liệu từ trigger event.
  Ví dụ: {{trigger.note_id}}, {{trigger.title}}, {{trigger.event}}

{{steps.NODE_ID.*}}
  Output của node có id = NODE_ID.
  Ví dụ: {{steps.action-1.summary}}, {{steps.action-1.note_id}}
  NODE_ID phải là id thực của node trong definition.

{{workflow.*}}
  Metadata của workflow đang chạy.
  {{workflow.id}}, {{workflow.name}}, {{workflow.version}}

{{user.*}}
  Thông tin user.
  {{user.id}}, {{user.email}}
```

### Ví dụ thực tế

```
Action: create_note
  title: "Summary của: {{trigger.title}}"
  content: "{{steps.ai-step.summary}}\n\nNguồn: {{trigger.note_id}}"

Action: send_notification
  title: "{{trigger.event}} lúc {{workflow.name}}"
  message: "Kết quả AI: {{steps.ai-step.ai_result}}"
```

---

## 9. Workflow Service vs Cortex Backend — API Routing

Frontend cần biết gọi vào đâu:

```typescript
// frontend/src/config/api.ts
export const CORTEX_API = "http://localhost:8000/api"        // Cortex backend
export const WORKFLOW_API = "http://localhost:8001/api/v1"   // Workflow service

// Ví dụ:
// GET notes:     CORTEX_API + "/notes"
// GET workflows: WORKFLOW_API + "/workflows"
// POST trigger:  WORKFLOW_API + "/workflows/{id}/trigger"
```
