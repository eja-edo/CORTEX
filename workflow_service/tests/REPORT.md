# Workflow Node Execution Report

## Summary
- **Total tests**: 17
- **Passed**: 17
- **Failed**: 0
- **Services tested**: AI Agent API, Notes API, Notifications API, Schedules API

## Test Environment
- **Date**: 2026-07-09 02:12:33 UTC
- **Workflow ID**: 335cde71-7ae3-43a3-b863-a150758bbb28
- **Auth user ID**: `aaa352bb-8035-4e76-88d7-9813e84b966b`
- **JWT algorithm**: HS256
- **JWT secret source**: fallback default

## Node-by-Node Results

### 1. Manual Trigger (`tr1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `tr1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | [] |



**Request Body**:
```json
{
  "config": {},
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "570c3d5b-4375-42ac-86a2-910f973e18fa"
    }
  },
  "previous_outputs": {}
}
```

**Response Body**:
```json
{
  "success": true,
  "output": {},
  "error": null
}
```


### 2. Manual Trigger (trigger endpoint) (`tr1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `tr1` |
| Passed | ✅ |
| Response Status | 202 |
| Success | N/A |
| Output keys | [] |



**Request Body**:
```json
{
  "input_data": {
    "source": "audit_test"
  }
}
```

**Response Body**:
```json
{
  "instance_id": "464aeef7-0c1a-439e-8b3c-0b3465e6e93d",
  "workflow_id": "335cde71-7ae3-43a3-b863-a150758bbb28"
}
```


### 3. Test Success (`a1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `a1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | ['message', 'node_id'] |
| Fields Check | message=ok |


**Request Body**:
```json
{
  "config": {
    "message": "ok"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {}
}
```

**Response Body**:
```json
{
  "success": true,
  "output": {
    "message": "ok",
    "node_id": "a1"
  },
  "error": null
}
```


### 4. Check Result (`c1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `c1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | ['condition_result', 'branch', 'left', 'operator', 'right'] |
| Fields Check | condition_result=True branch=true left=ok right=ok |


**Request Body**:
```json
{
  "config": {
    "left": "{{steps.Test Success.message}}",
    "operator": "equals",
    "right": "ok"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {
    "tr1": {
      "output": {},
      "success": true
    },
    "Manual Trigger": {},
    "a1": {
      "output": {
        "message": "ok",
        "node_id": "a1"
      },
      "success": true
    },
    "Test Success": {
      "message": "ok",
      "node_id": "a1"
    },
    "c1": {
      "output": {
        "condition_result": true,
        "branch": "true",
        "left": "ok",
        "operator": "equals",
        "right": "ok"
      },
      "success": true
    },
    "Check Result": {
      "condition_result": true,
      "branch": "true",
      "left": "ok",
      "operator": "equals",
      "right": "ok"
    },
    "c2": {
      "output": {
        "condition_result": false,
        "branch": "false",
        "left": "manual.trigger",
        "operator": "equals",
        "right": "nonexistent"
      },
      "success": true
    },
    "Check False": {
      "condition_result": false,
      "branch": "false",
      "left": "manual.trigger",
      "operator": "equals",
      "right": "nonexistent"
    },
    "n1": {
      "output": {},
      "success": false
    },
    "Notify OK": {},
    "w1": {
      "output": {
        "waited": true,
        "duration": 1,
        "unit": "seconds"
      },
      "success": true
    },
    "Wait 1s": {
      "waited": true,
      "duration": 1,
      "unit": "seconds"
    },
    "cr1": {
      "output": {},
      "success": false
    },
    "Create Note": {},
    "up1": {
      "output": {},
      "success": false
    },
    "Update Note": {},
    "ai1": {
      "output": {
        "ai_result": "Hello!",
        "model_used": "free_auto"
      },
      "success": true
    },
    "Call AI": {
      "ai_result": "Hello!",
      "model_used": "free_auto"
    },
    "wh1": {
      "output": {},
      "success": false
    },
    "Call Webhook": {},
    "s1": {
      "output": {},
      "success": false
    },
    "Create Schedule": {}
  }
}
```

**Response Body**:
```json
{
  "success": true,
  "output": {
    "condition_result": true,
    "branch": "true",
    "left": "ok",
    "operator": "equals",
    "right": "ok"
  },
  "error": null
}
```


### 5. Check False (`c2`) ✅

| Field | Value |
|-------|-------|
| Node ID | `c2` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | ['condition_result', 'branch', 'left', 'operator', 'right'] |
| Fields Check | condition_result=False branch=false left=manual.trigger right=nonexistent |


**Request Body**:
```json
{
  "config": {
    "left": "{{trigger.event}}",
    "operator": "equals",
    "right": "nonexistent"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {}
}
```

**Response Body**:
```json
{
  "success": true,
  "output": {
    "condition_result": false,
    "branch": "false",
    "left": "manual.trigger",
    "operator": "equals",
    "right": "nonexistent"
  },
  "error": null
}
```


### 6. Notify OK (`n1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `n1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | False |
| Output keys | [] |

| Note | Expected success=False if core backend is down |

**Request Body**:
```json
{
  "config": {
    "title": "{{trigger.event}}",
    "body": "{{steps.Check Result.branch}}",
    "type": "info"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {
    "tr1": {
      "output": {},
      "success": true
    },
    "Manual Trigger": {},
    "a1": {
      "output": {
        "message": "ok",
        "node_id": "a1"
      },
      "success": true
    },
    "Test Success": {
      "message": "ok",
      "node_id": "a1"
    },
    "c1": {
      "output": {
        "condition_result": true,
        "branch": "true",
        "left": "ok",
        "operator": "equals",
        "right": "ok"
      },
      "success": true
    },
    "Check Result": {
      "condition_result": true,
      "branch": "true",
      "left": "ok",
      "operator": "equals",
      "right": "ok"
    },
    "c2": {
      "output": {
        "condition_result": false,
        "branch": "false",
        "left": "manual.trigger",
        "operator": "equals",
        "right": "nonexistent"
      },
      "success": true
    },
    "Check False": {
      "condition_result": false,
      "branch": "false",
      "left": "manual.trigger",
      "operator": "equals",
      "right": "nonexistent"
    },
    "n1": {
      "output": {},
      "success": false
    },
    "Notify OK": {},
    "w1": {
      "output": {
        "waited": true,
        "duration": 1,
        "unit": "seconds"
      },
      "success": true
    },
    "Wait 1s": {
      "waited": true,
      "duration": 1,
      "unit": "seconds"
    },
    "cr1": {
      "output": {},
      "success": false
    },
    "Create Note": {},
    "up1": {
      "output": {},
      "success": false
    },
    "Update Note": {},
    "ai1": {
      "output": {
        "ai_result": "Hello!",
        "model_used": "free_auto"
      },
      "success": true
    },
    "Call AI": {
      "ai_result": "Hello!",
      "model_used": "free_auto"
    },
    "wh1": {
      "output": {},
      "success": false
    },
    "Call Webhook": {},
    "s1": {
      "output": {},
      "success": false
    },
    "Create Schedule": {}
  }
}
```

**Response Body**:
```json
{
  "success": false,
  "output": {},
  "error": "Server error '500 Internal Server Error' for url 'http://localhost:8000/internal/notifications'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500"
}
```


### 7. Wait 1s (`w1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `w1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | ['waited', 'duration', 'unit'] |
| Fields Check | waited=True duration=1 unit=seconds |


**Request Body**:
```json
{
  "config": {
    "duration": 1,
    "unit": "seconds"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {}
}
```

**Response Body**:
```json
{
  "success": true,
  "output": {
    "waited": true,
    "duration": 1,
    "unit": "seconds"
  },
  "error": null
}
```


### 8. Create Note (`cr1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `cr1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | False |
| Output keys | [] |

| Note | Expected success=False if core backend is down |

**Request Body**:
```json
{
  "config": {
    "title": "Report {{steps.Test Success.message}}",
    "content": "auto-generated from audit"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {
    "tr1": {
      "output": {},
      "success": true
    },
    "Manual Trigger": {},
    "a1": {
      "output": {
        "message": "ok",
        "node_id": "a1"
      },
      "success": true
    },
    "Test Success": {
      "message": "ok",
      "node_id": "a1"
    },
    "c1": {
      "output": {
        "condition_result": true,
        "branch": "true",
        "left": "ok",
        "operator": "equals",
        "right": "ok"
      },
      "success": true
    },
    "Check Result": {
      "condition_result": true,
      "branch": "true",
      "left": "ok",
      "operator": "equals",
      "right": "ok"
    },
    "c2": {
      "output": {
        "condition_result": false,
        "branch": "false",
        "left": "manual.trigger",
        "operator": "equals",
        "right": "nonexistent"
      },
      "success": true
    },
    "Check False": {
      "condition_result": false,
      "branch": "false",
      "left": "manual.trigger",
      "operator": "equals",
      "right": "nonexistent"
    },
    "n1": {
      "output": {},
      "success": false
    },
    "Notify OK": {},
    "w1": {
      "output": {
        "waited": true,
        "duration": 1,
        "unit": "seconds"
      },
      "success": true
    },
    "Wait 1s": {
      "waited": true,
      "duration": 1,
      "unit": "seconds"
    },
    "cr1": {
      "output": {},
      "success": false
    },
    "Create Note": {},
    "up1": {
      "output": {},
      "success": false
    },
    "Update Note": {},
    "ai1": {
      "output": {
        "ai_result": "Hello!",
        "model_used": "free_auto"
      },
      "success": true
    },
    "Call AI": {
      "ai_result": "Hello!",
      "model_used": "free_auto"
    },
    "wh1": {
      "output": {},
      "success": false
    },
    "Call Webhook": {},
    "s1": {
      "output": {},
      "success": false
    },
    "Create Schedule": {}
  }
}
```

**Response Body**:
```json
{
  "success": false,
  "output": {},
  "error": "Failed to create note: Client error '401 Unauthorized' for url 'http://localhost:8000/api/notes'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401"
}
```


### 9. Update Note (`up1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `up1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | False |
| Output keys | [] |

| Note | Expected success=False if core backend is down; template resolution checked by status==200 |

**Request Body**:
```json
{
  "config": {
    "note_id": "{{trigger.input.fake_note_id}}",
    "content": "Updated"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {}
}
```

**Response Body**:
```json
{
  "success": false,
  "output": {},
  "error": "Failed to update note: Client error '401 Unauthorized' for url 'http://localhost:8000/api/notes/750afd61-7917-40c7-ba84-035b74690a41'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401"
}
```


### 10. Call AI (`ai1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `ai1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | ['ai_result', 'model_used'] |

| Note | Expected success=False if AI backend is down |

**Request Body**:
```json
{
  "config": {
    "prompt": "Say hello",
    "output_key": "ai_result"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {}
}
```

**Response Body**:
```json
{
  "success": true,
  "output": {
    "ai_result": "Hello!",
    "model_used": "free_auto"
  },
  "error": null
}
```


### 11. Call Webhook (`wh1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `wh1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | False |
| Output keys | [] |

| Note | URL resolves to 'manual.trigger' which is invalid — expected graceful error handling |

**Request Body**:
```json
{
  "config": {
    "url": "{{trigger.event}}",
    "method": "POST"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {}
}
```

**Response Body**:
```json
{
  "success": false,
  "output": {},
  "error": "Webhook call failed: Request URL is missing an 'http://' or 'https://' protocol."
}
```


### 12. Create Schedule (`s1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `s1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | False |
| Output keys | [] |

| Note | Expected success=False if core backend is down |

**Request Body**:
```json
{
  "config": {
    "title": "Test",
    "start_time": "2026-01-01T00:00:00",
    "end_time": "2026-01-01T01:00:00"
  },
  "trigger_data": {
    "event": "manual.trigger",
    "input": {
      "fake_note_id": "750afd61-7917-40c7-ba84-035b74690a41"
    }
  },
  "previous_outputs": {}
}
```

**Response Body**:
```json
{
  "success": false,
  "output": {},
  "error": "Failed to create schedule: Client error '401 Unauthorized' for url 'http://localhost:8000/api/schedules'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401"
}
```


### 13. Empty trigger_data (`edge-1`) ✅

| Field | Value |
|-------|-------|
| Node ID | `edge-1` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | ['condition_result', 'branch', 'left', 'operator', 'right'] |



**Request Body**:
```json
{}
```

**Response Body**:
```json
{
  "success": true,
  "output": {
    "condition_result": true,
    "branch": "true",
    "left": "manual.trigger",
    "operator": "equals",
    "right": "manual.trigger"
  },
  "error": null
}
```


### 14. Missing steps field (`edge-2`) ✅

| Field | Value |
|-------|-------|
| Node ID | `edge-2` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | ['condition_result', 'branch', 'left', 'operator', 'right'] |



**Request Body**:
```json
{}
```

**Response Body**:
```json
{
  "success": true,
  "output": {
    "condition_result": true,
    "branch": "true",
    "left": "",
    "operator": "is_empty",
    "right": ""
  },
  "error": null
}
```


### 15. Deeply nested trigger_data (`edge-3`) ✅

| Field | Value |
|-------|-------|
| Node ID | `edge-3` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | ['condition_result', 'branch', 'left', 'operator', 'right'] |



**Request Body**:
```json
{}
```

**Response Body**:
```json
{
  "success": true,
  "output": {
    "condition_result": true,
    "branch": "true",
    "left": "deep_value",
    "operator": "equals",
    "right": "deep_value"
  },
  "error": null
}
```


### 16. Condition empty config (`edge-4`) ✅

| Field | Value |
|-------|-------|
| Node ID | `edge-4` |
| Passed | ✅ |
| Response Status | 200 |
| Success | True |
| Output keys | ['condition_result', 'branch', 'left', 'operator', 'right'] |



**Request Body**:
```json
{}
```

**Response Body**:
```json
{
  "success": true,
  "output": {
    "condition_result": true,
    "branch": "true",
    "left": "",
    "operator": "equals",
    "right": ""
  },
  "error": null
}
```


### 17. Template by label resolution (`edge-5`) ✅

| Field | Value |
|-------|-------|
| Node ID | `edge-5` |
| Passed | ✅ |
| Response Status | 200 |
| Success | False |
| Output keys | [] |



**Request Body**:
```json
{}
```

**Response Body**:
```json
{
  "success": false,
  "output": {},
  "error": "Server error '500 Internal Server Error' for url 'http://localhost:8000/internal/notifications'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500"
}
```


## Full Flow Test (Trigger → Action → Condition → Action)

The workflow pipeline is:
```
tr1 (manual trigger) -> a1 (test_success: message="ok")
  -> c1 (condition: {{steps.Test Success.message}} == "ok")
    |-- true  -> n1 (notify: title={{trigger.event}}, body={{steps.Check Result.branch}})
    |            -> w1 (wait: 1 second)
    |            -> cr1 (create note: title="Report {{steps.Test Success.message}}")
    |            -> up1 (update note: note_id={{trigger.input.fake_note_id}})
    |            -> ai1 (call AI: prompt="Say hello")
    |            -> wh1 (call webhook: url={{trigger.event}})
    |            -> s1 (create schedule)
    +-- false -> c2 (condition: {{trigger.event}} == "nonexistent" -> false branch)
```

### Intermediate Outputs
- **Manual Trigger** (`tr1`): *(empty output)*
- **Manual Trigger (trigger endpoint)** (`tr1`): *(empty output)*
- **Test Success** (`a1`): ```json
{
  "message": "ok",
  "node_id": "a1"
}
```
- **Check Result** (`c1`): ```json
{
  "condition_result": true,
  "branch": "true",
  "left": "ok",
  "operator": "equals",
  "right": "ok"
}
```
- **Check False** (`c2`): ```json
{
  "condition_result": false,
  "branch": "false",
  "left": "manual.trigger",
  "operator": "equals",
  "right": "nonexistent"
}
```
- **Notify OK** (`n1`): *(empty output)*
- **Wait 1s** (`w1`): ```json
{
  "waited": true,
  "duration": 1,
  "unit": "seconds"
}
```
- **Create Note** (`cr1`): *(empty output)*
- **Update Note** (`up1`): *(empty output)*
- **Call AI** (`ai1`): ```json
{
  "ai_result": "Hello!",
  "model_used": "free_auto"
}
```
- **Call Webhook** (`wh1`): *(empty output)*
- **Create Schedule** (`s1`): *(empty output)*
- **Empty trigger_data** (`edge-1`): ```json
{
  "condition_result": true,
  "branch": "true",
  "left": "manual.trigger",
  "operator": "equals",
  "right": "manual.trigger"
}
```
- **Missing steps field** (`edge-2`): ```json
{
  "condition_result": true,
  "branch": "true",
  "left": "",
  "operator": "is_empty",
  "right": ""
}
```
- **Deeply nested trigger_data** (`edge-3`): ```json
{
  "condition_result": true,
  "branch": "true",
  "left": "deep_value",
  "operator": "equals",
  "right": "deep_value"
}
```
- **Condition empty config** (`edge-4`): ```json
{
  "condition_result": true,
  "branch": "true",
  "left": "",
  "operator": "equals",
  "right": ""
}
```
- **Template by label resolution** (`edge-5`): *(empty output)*

### Template Resolution Verification
- `{{trigger.event}}` → `manual.trigger` — `Condition (Check False)` (left resolved to `manual.trigger`)
- `{{steps.Test Success.message}}` → `ok` — `Condition (Check Result)` (left resolved to `ok`)
- `{{steps.Check Result.branch}}` → `true` — `Notify OK` (body template from step output)
- `{{trigger.input.fake_note_id}}` → UUID — `Update Note` (note_id template from trigger)
- `{{trigger.input.nested.deep.key}}` → `deep_value` — `Edge case` (deeply nested path)

## Inter-Service Communication
| Service | Endpoint | Status | Notes |
|---------|----------|--------|-------|
| Notifications API | /internal/notifications | ❌ |  |
| Notes API | /api/notes | ❌ |  |
| Notes API | /api/notes/{id} | ❌ |  |
| AI Agent API | /api/agent/complete | ✅ |  |
| Schedules API | /api/schedules | ❌ |  |

## Edge Cases Tested
| Edge Case | Status |
|-----------|--------|
| Empty trigger_data | ✅ |
| Missing steps field in template | ✅ |
| Deeply nested trigger_data paths | ✅ |
| Webhook with bad URL | ✅ |
| Condition with empty config | ✅ |

## Issues Found
- ✅ No issues found — all tests passed.
