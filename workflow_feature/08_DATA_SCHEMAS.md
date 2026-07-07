# DATA SCHEMAS
## Toàn bộ Database Schema + Temporal Workflow Schema

---

## 1. PostgreSQL — Schema `workflow`

### 1.1 `workflow.workflow_definitions`

```sql
CREATE TABLE workflow.workflow_definitions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,          -- FK tới users.id của Cortex (không enforce FK để loose coupling)
    workspace_id    UUID,                   -- Optional: scope workflow vào workspace
    
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    status          VARCHAR(50) NOT NULL DEFAULT 'draft',
                    -- Values: draft | active | paused | archived
    version         INTEGER NOT NULL DEFAULT 1,  -- Tăng khi definition thay đổi lúc đang active
    
    trigger_type    VARCHAR(50) NOT NULL,
                    -- Values: internal_event | webhook | schedule | manual
    trigger_config  JSONB NOT NULL DEFAULT '{}',
    -- Ví dụ trigger_config:
    -- internal_event: {"event": "note.created", "filters": {"workspace_id": "xxx"}}
    -- webhook:        {} (webhook config ở bảng riêng)
    -- schedule:       {"cron": "0 9 * * MON", "timezone": "Asia/Ho_Chi_Minh"}
    -- manual:         {}
    
    definition      JSONB NOT NULL DEFAULT '{}',
    -- Cấu trúc:
    -- {
    --   "nodes": [
    --     {
    --       "id": "node-1",
    --       "type": "triggerNode",
    --       "position": {"x": 100, "y": 100},
    --       "data": {
    --         "label": "Cortex Event",
    --         "nodeType": "trigger.internal_event",
    --         "config": {"event": "note.created"},
    --         "isConfigured": true
    --       }
    --     },
    --     {
    --       "id": "node-2",
    --       "type": "actionNode",
    --       "position": {"x": 100, "y": 250},
    --       "data": {
    --         "label": "Gửi Notification",
    --         "nodeType": "action.send_notification",
    --         "config": {"title": "Note mới: {{trigger.title}}", "message": "..."},
    --         "isConfigured": true
    --       }
    --     }
    --   ],
    --   "edges": [
    --     {"id": "e1", "source": "node-1", "target": "node-2"}
    --   ],
    --   "variables": {}
    -- }
    
    webhook_secret  VARCHAR(255),           -- Raw secret cho webhook trigger (chỉ hiển thị 1 lần)
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
);

-- Indexes
CREATE INDEX idx_workflow_definitions_user_id ON workflow.workflow_definitions(user_id);
CREATE INDEX idx_workflow_definitions_workspace_id ON workflow.workflow_definitions(workspace_id) WHERE workspace_id IS NOT NULL;
CREATE INDEX idx_workflow_definitions_status ON workflow.workflow_definitions(status) WHERE is_deleted = FALSE;
CREATE INDEX idx_workflow_definitions_trigger_type ON workflow.workflow_definitions(trigger_type) WHERE status = 'active' AND is_deleted = FALSE;
```

### 1.2 `workflow.workflow_trigger_webhooks`

```sql
CREATE TABLE workflow.workflow_trigger_webhooks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL REFERENCES workflow.workflow_definitions(id) ON DELETE CASCADE,
    
    webhook_path    VARCHAR(255) NOT NULL UNIQUE,
    -- URL: POST /api/v1/webhooks/{webhook_path}
    -- Ví dụ: POST /api/v1/webhooks/a3f7b2c1d4e5f6g7h8i9j0
    
    secret_hash     VARCHAR(255) NOT NULL,  -- SHA256 hash của webhook secret
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_webhook_path ON workflow.workflow_trigger_webhooks(webhook_path) WHERE is_active = TRUE;
```

### 1.3 `workflow.workflow_instances`

```sql
CREATE TABLE workflow.workflow_instances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL REFERENCES workflow.workflow_definitions(id),
    user_id         UUID NOT NULL,
    
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
                    -- Values: pending | running | waiting | completed | failed | cancelled | timed_out
    
    -- Temporal identifiers
    temporal_workflow_id    VARCHAR(255),   -- Format: "cortex-wf-{instance_id}"
    temporal_run_id         VARCHAR(255),   -- Temporal's internal run ID
    
    -- Data
    trigger_data    JSONB,
    -- Ví dụ:
    -- {"event": "note.created", "note_id": "xxx", "user_id": "yyy", "title": "My Note"}
    -- {"event": "webhook.received", "webhook_path": "...", "payload": {...}}
    -- {"event": "manual.triggered", "input": {}}
    
    output          JSONB,                  -- Final output của toàn bộ workflow
    error_message   TEXT,                   -- Error message khi failed
    
    -- Timestamps
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_workflow_instances_workflow_id ON workflow.workflow_instances(workflow_id);
CREATE INDEX idx_workflow_instances_user_id ON workflow.workflow_instances(user_id);
CREATE INDEX idx_workflow_instances_status ON workflow.workflow_instances(status);
CREATE INDEX idx_workflow_instances_created_at ON workflow.workflow_instances(created_at DESC);
```

### 1.4 `workflow.workflow_step_executions`

```sql
CREATE TABLE workflow.workflow_step_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id     UUID NOT NULL REFERENCES workflow.workflow_instances(id) ON DELETE CASCADE,
    
    node_id         VARCHAR(255) NOT NULL,  -- ID của node trong React Flow definition
    node_type       VARCHAR(100) NOT NULL,  -- Ví dụ: "action.create_note"
    
    status          VARCHAR(50) NOT NULL,
                    -- Values: running | completed | failed
    
    input_data      JSONB,   -- Config từ node + resolved templates
    output_data     JSONB,   -- Kết quả trả về từ action
    error_message   TEXT,
    
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_step_executions_instance_id ON workflow.workflow_step_executions(instance_id);
CREATE INDEX idx_step_executions_status ON workflow.workflow_step_executions(status);
```

---

## 2. Workflow Definition JSON Schema

Full JSON Schema cho field `definition` trong `workflow_definitions`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "WorkflowDefinition",
  "type": "object",
  "required": ["nodes", "edges"],
  "properties": {
    "nodes": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/WorkflowNode"
      }
    },
    "edges": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/WorkflowEdge"
      }
    },
    "variables": {
      "type": "object",
      "description": "Global variables accessible via {{workflow.variables.xxx}}"
    }
  },
  "definitions": {
    "WorkflowNode": {
      "type": "object",
      "required": ["id", "type", "position", "data"],
      "properties": {
        "id": {
          "type": "string",
          "description": "Unique node ID (React Flow format)",
          "example": "node-1"
        },
        "type": {
          "type": "string",
          "enum": ["triggerNode", "actionNode", "conditionNode"],
          "description": "React Flow node type — determines which React component renders"
        },
        "position": {
          "type": "object",
          "required": ["x", "y"],
          "properties": {
            "x": { "type": "number" },
            "y": { "type": "number" }
          }
        },
        "data": {
          "$ref": "#/definitions/NodeData"
        }
      }
    },
    "NodeData": {
      "type": "object",
      "required": ["label", "nodeType", "config", "isConfigured"],
      "properties": {
        "label": {
          "type": "string",
          "description": "Display label trong React Flow node"
        },
        "nodeType": {
          "type": "string",
          "description": "Business logic type",
          "examples": [
            "trigger.internal_event",
            "trigger.webhook",
            "trigger.manual",
            "action.create_note",
            "action.update_note",
            "action.send_notification",
            "action.create_schedule",
            "action.call_ai",
            "action.call_webhook",
            "action.wait",
            "action.condition"
          ]
        },
        "config": {
          "type": "object",
          "description": "Cấu hình cụ thể của node — schema khác nhau theo nodeType"
        },
        "isConfigured": {
          "type": "boolean",
          "description": "true khi user đã điền đủ required fields"
        }
      }
    },
    "WorkflowEdge": {
      "type": "object",
      "required": ["id", "source", "target"],
      "properties": {
        "id": { "type": "string" },
        "source": { "type": "string", "description": "Node ID của nguồn" },
        "target": { "type": "string", "description": "Node ID của đích" },
        "sourceHandle": {
          "type": "string",
          "description": "Handle ID của nguồn — dùng cho condition node (true/false)"
        },
        "targetHandle": { "type": "string" }
      }
    }
  }
}
```

---

## 3. Config Schemas theo từng Node Type

### 3.1 Trigger Configs

```json
{
  "trigger.internal_event": {
    "type": "object",
    "required": ["event"],
    "properties": {
      "event": {
        "type": "string",
        "enum": [
          "note.created", "note.updated", "note.deleted",
          "schedule.created", "schedule.updated", "schedule.completed",
          "schedule.due_soon",
          "asset.uploaded", "asset.processed"
        ]
      },
      "filters": {
        "type": "object",
        "properties": {
          "workspace_id": { "type": "string" },
          "user_id": { "type": "string" }
        }
      }
    }
  },

  "trigger.webhook": {},

  "trigger.manual": {},

  "trigger.schedule": {
    "type": "object",
    "required": ["cron"],
    "properties": {
      "cron": {
        "type": "string",
        "description": "Cron expression. Ví dụ: '0 9 * * MON' = 9AM mỗi thứ Hai"
      },
      "timezone": {
        "type": "string",
        "default": "Asia/Ho_Chi_Minh"
      }
    }
  }
}
```

### 3.2 Action Configs

```json
{
  "action.create_note": {
    "required": ["title"],
    "properties": {
      "title": {
        "type": "string",
        "description": "Hỗ trợ template. Ví dụ: 'Summary: {{trigger.note_title}}'"
      },
      "content": { "type": "string" },
      "workspace_id": { "type": "string" }
    }
  },

  "action.update_note": {
    "required": ["note_id"],
    "properties": {
      "note_id": { "type": "string", "description": "Có thể dùng template: {{trigger.note_id}}" },
      "content": { "type": "string" },
      "append": { "type": "boolean", "description": "true = thêm vào cuối, false = ghi đè" }
    }
  },

  "action.send_notification": {
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
  },

  "action.call_ai": {
    "required": ["prompt"],
    "properties": {
      "prompt": { "type": "string" },
      "output_key": {
        "type": "string",
        "default": "ai_result",
        "description": "Tên key để steps sau tham chiếu qua {{steps.NODE_ID.output_key}}"
      }
    }
  },

  "action.call_webhook": {
    "required": ["url", "method"],
    "properties": {
      "url": { "type": "string" },
      "method": { "type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"] },
      "headers": { "type": "object" },
      "body": { "type": "string", "description": "JSON string, hỗ trợ template" }
    }
  },

  "action.wait": {
    "required": ["duration", "unit"],
    "properties": {
      "duration": { "type": "number", "minimum": 1 },
      "unit": { "type": "string", "enum": ["seconds", "minutes", "hours"] }
    }
  },

  "action.condition": {
    "required": ["left", "operator"],
    "properties": {
      "left": { "type": "string", "description": "Template expression. Ví dụ: {{trigger.event}}" },
      "operator": {
        "type": "string",
        "enum": ["equals", "not_equals", "contains", "not_contains", "is_empty", "is_not_empty"]
      },
      "right": { "type": "string" }
    }
  }
}
```

---

## 4. Redis Pub/Sub — Event Format

Channel: `cortex:workflow:events`

### Format chuẩn cho mọi event

```json
{
  "event": "note.created",
  "timestamp": "2024-01-15T10:30:00Z",
  "user_id": "uuid-của-user",
  "workspace_id": "uuid-của-workspace-hoặc-null",
  "data": {
    "note_id": "uuid",
    "title": "Tên note",
    "content": "Nội dung...",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Tất cả event types và payload

```
note.created
├── user_id
├── workspace_id
└── data: {note_id, title, content, created_at}

note.updated
├── user_id
├── workspace_id
└── data: {note_id, title, updated_fields: [...]}

note.deleted
├── user_id
└── data: {note_id}

schedule.created
├── user_id
└── data: {schedule_id, title, start_time, end_time, type}

schedule.updated
├── user_id
└── data: {schedule_id, title, updated_fields: [...]}

schedule.completed
├── user_id
└── data: {schedule_id, title, completed_at}

schedule.due_soon
├── user_id
└── data: {schedule_id, title, start_time, minutes_until_due}

asset.uploaded
├── user_id
├── workspace_id
└── data: {asset_id, filename, file_type, size_bytes}

asset.processed
├── user_id
└── data: {asset_id, processing_type: "ocr"|"stt", status: "completed"|"failed"}
```

---

## 5. Temporal Workflow — Input/Output Schemas

### CortexWorkflow Input

```python
@dataclass
class CortexWorkflowInput:
    instance_id: str      # UUID của WorkflowInstance trong DB
    workflow_id: str      # UUID của WorkflowDefinition
    user_id: str          # UUID của user
    definition: dict      # Toàn bộ workflow definition JSON
    trigger_data: dict    # Event data từ trigger
```

### Temporal Workflow ID Format

```
cortex-wf-{instance_id}
```

Ví dụ: `cortex-wf-a3f7b2c1-d4e5-f6g7-h8i9-j0k1l2m3n4o5`

Query trong Temporal UI: filter by workflow ID prefix `cortex-wf-`

### Activity Input/Output

```python
# execute_action
Input:  ExecuteActionInput(action_type, config, user_id, workflow_id, instance_id, node_id, trigger_data, previous_outputs)
Output: dict  (action output — khác nhau theo action type)

# update_step_status
Input:  UpdateStepStatusInput(instance_id, node_id, node_type, status, input_data?, output_data?, error_message?)
Output: None

# update_instance_status
Input:  UpdateInstanceStatusInput(instance_id, status, temporal_workflow_id?, temporal_run_id?, output?, error_message?)
Output: None
```

---

## 6. API Response Schemas

### WorkflowResponse (đầy đủ)

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "workspace_id": "uuid-hoặc-null",
  "name": "My Workflow",
  "description": "Mô tả...",
  "status": "active",
  "version": 1,
  "trigger_type": "internal_event",
  "trigger_config": {
    "event": "note.created",
    "filters": {}
  },
  "definition": {
    "nodes": [...],
    "edges": [...],
    "variables": {}
  },
  "webhook_url": null,
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

### ExecutionResponse (đầy đủ)

```json
{
  "id": "uuid",
  "workflow_id": "uuid",
  "status": "completed",
  "temporal_workflow_id": "cortex-wf-uuid",
  "trigger_data": {
    "event": "note.created",
    "note_id": "uuid",
    "title": "Test Note"
  },
  "output": {
    "node-2": {"sent": true},
    "node-3": {"note_id": "uuid", "title": "Summary: Test Note"}
  },
  "error_message": null,
  "started_at": "2024-01-15T10:30:01Z",
  "completed_at": "2024-01-15T10:30:05Z",
  "created_at": "2024-01-15T10:30:00Z",
  "steps": [
    {
      "id": "uuid",
      "node_id": "node-2",
      "node_type": "action.send_notification",
      "status": "completed",
      "input_data": {"title": "Note mới!", "message": "..."},
      "output_data": {"sent": true},
      "error_message": null,
      "started_at": "2024-01-15T10:30:01Z",
      "completed_at": "2024-01-15T10:30:02Z"
    }
  ]
}
```
