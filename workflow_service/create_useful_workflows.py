"""
Create useful workflows for user and test all nodes end-to-end.
Uses real JWT token for actual user.
"""
import asyncio
import uuid
import httpx
from datetime import datetime, timezone, timedelta

BASE_URL = "http://localhost:8001/api/v1"
JWT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODM1NzUyNTQsInN1YiI6IjljYjk1MDljLTQ5ZGUtNDE1Yi1hOTQ2LTQxZjAyY2JhMGMyZCIsInR5cGUiOiJhY2Nlc3MiLCJqdGkiOiJlM2FjZGUwYy1iYjJkLTQ0MTMtYTlkMC02NTZmOWJiYmU4NzUifQ.-_A5O4XlkgNUwym40JOauSr-Qcq9-ilNngJuAqu9PIg"
HEADERS = {
    "Authorization": f"Bearer {JWT_TOKEN}",
    "Content-Type": "application/json"
}

async def create_workflow(client: httpx.AsyncClient, name: str, description: str, definition: dict, trigger_type: str = "manual"):
    """Create a workflow."""
    payload = {
        "name": name,
        "description": description,
        "trigger_type": trigger_type,
        "trigger_config": {},
        "definition": definition
    }
    resp = await client.post(f"{BASE_URL}/workflows", headers=HEADERS, json=payload)
    resp.raise_for_status()
    return resp.json()

async def activate_workflow(client: httpx.AsyncClient, workflow_id: str):
    """Activate a workflow."""
    resp = await client.post(f"{BASE_URL}/workflows/{workflow_id}/activate", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

async def trigger_workflow(client: httpx.AsyncClient, workflow_id: str, input_data: dict = None):
    """Trigger a workflow manually."""
    payload = {"input_data": input_data or {}}
    resp = await client.post(f"{BASE_URL}/workflows/{workflow_id}/trigger", headers=HEADERS, json=payload)
    resp.raise_for_status()
    return resp.json()

async def execute_node(client: httpx.AsyncClient, workflow_id: str, node_id: str, config: dict, trigger_data: dict = None, previous_outputs: dict = None):
    """Execute a single node."""
    payload = {
        "config": config,
        "trigger_data": trigger_data or {},
        "previous_outputs": previous_outputs or {}
    }
    resp = await client.post(f"{BASE_URL}/workflows/{workflow_id}/nodes/{node_id}/execute", headers=HEADERS, json=payload)
    resp.raise_for_status()
    return resp.json()


# ========================================
# WORKFLOW 1: Daily Summary with AI
# ========================================
def create_daily_summary_workflow():
    """Create a workflow that generates daily summary with AI."""
    return {
        "nodes": [
            {
                "id": "trigger1",
                "type": "trigger.schedule",
                "position": {"x": 100, "y": 100},
                "data": {
                    "label": "Daily Trigger",
                    "config": {
                        "cron": "0 18 * * *",  # 6 PM daily
                        "timezone": "Asia/Ho_Chi_Minh"
                    }
                }
            },
            {
                "id": "ai1",
                "type": "action.call_ai",
                "position": {"x": 300, "y": 100},
                "data": {
                    "label": "Generate Summary",
                    "config": {
                        "prompt": "Generate a brief motivational message for end of workday. Keep it under 100 words.",
                        "output_key": "daily_message"
                    }
                }
            },
            {
                "id": "note1",
                "type": "action.create_note",
                "position": {"x": 500, "y": 100},
                "data": {
                    "label": "Save to Note",
                    "config": {
                        "title": "Daily Summary - {{trigger.timestamp}}",
                        "content": "{{steps.Generate Summary.daily_message}}"
                    }
                }
            },
            {
                "id": "notif1",
                "type": "action.send_notification",
                "position": {"x": 700, "y": 100},
                "data": {
                    "label": "Notify User",
                    "config": {
                        "title": "Daily Summary Ready",
                        "body": "Your daily summary has been created",
                        "type": "success"
                    }
                }
            }
        ],
        "edges": [
            {"id": "e1", "source": "trigger1", "target": "ai1"},
            {"id": "e2", "source": "ai1", "target": "note1"},
            {"id": "e3", "source": "note1", "target": "notif1"}
        ],
        "variables": {}
    }


# ========================================
# WORKFLOW 2: Note Update with Condition
# ========================================
def create_note_update_workflow():
    """Workflow to update notes based on conditions."""
    return {
        "nodes": [
            {
                "id": "trigger2",
                "type": "trigger.manual",
                "position": {"x": 100, "y": 100},
                "data": {
                    "label": "Manual Start",
                    "config": {}
                }
            },
            {
                "id": "cond1",
                "type": "action.condition",
                "position": {"x": 300, "y": 100},
                "data": {
                    "label": "Check Input",
                    "config": {
                        "left": "{{trigger.input.action}}",
                        "operator": "equals",
                        "right": "update"
                    }
                }
            },
            {
                "id": "update1",
                "type": "action.update_note",
                "position": {"x": 500, "y": 50},
                "data": {
                    "label": "Update Note",
                    "config": {
                        "note_id": "{{trigger.input.note_id}}",
                        "content": "Updated at {{trigger.input.timestamp}}",
                        "append": True
                    }
                }
            },
            {
                "id": "create1",
                "type": "action.create_note",
                "position": {"x": 500, "y": 150},
                "data": {
                    "label": "Create New Note",
                    "config": {
                        "title": "New Note - {{trigger.input.timestamp}}",
                        "content": "Created via workflow"
                    }
                }
            }
        ],
        "edges": [
            {"id": "e1", "source": "trigger2", "target": "cond1"},
            {"id": "e2", "source": "cond1", "target": "update1", "source_handle": "true"},
            {"id": "e3", "source": "cond1", "target": "create1", "source_handle": "false"}
        ],
        "variables": {}
    }


# ========================================
# WORKFLOW 3: Webhook Integration
# ========================================
def create_webhook_workflow():
    """Workflow triggered by webhook with AI processing."""
    return {
        "nodes": [
            {
                "id": "trigger3",
                "type": "trigger.webhook",
                "position": {"x": 100, "y": 100},
                "data": {
                    "label": "Webhook Trigger",
                    "config": {}
                }
            },
            {
                "id": "ai2",
                "type": "action.call_ai",
                "position": {"x": 300, "y": 100},
                "data": {
                    "label": "Process Data",
                    "config": {
                        "prompt": "Summarize this: {{trigger.payload.text}}",
                        "output_key": "summary"
                    }
                }
            },
            {
                "id": "webhook1",
                "type": "action.call_webhook",
                "position": {"x": 500, "y": 100},
                "data": {
                    "label": "Send Response",
                    "config": {
                        "url": "{{trigger.payload.callback_url}}",
                        "method": "POST",
                        "body": "{\"summary\": \"{{steps.Process Data.summary}}\"}"
                    }
                }
            }
        ],
        "edges": [
            {"id": "e1", "source": "trigger3", "target": "ai2"},
            {"id": "e2", "source": "ai2", "target": "webhook1"}
        ],
        "variables": {}
    }


# ========================================
# WORKFLOW 4: Schedule Management
# ========================================
def create_schedule_workflow():
    """Workflow to create calendar events."""
    future_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    future_end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()
    
    return {
        "nodes": [
            {
                "id": "trigger4",
                "type": "trigger.manual",
                "position": {"x": 100, "y": 100},
                "data": {
                    "label": "Start",
                    "config": {}
                }
            },
            {
                "id": "sched1",
                "type": "action.schedule",
                "position": {"x": 300, "y": 100},
                "data": {
                    "label": "Create Meeting",
                    "config": {
                        "title": "{{trigger.input.title}}",
                        "start_time": future_time,
                        "end_time": future_end,
                        "description": "Auto-created via workflow"
                    }
                }
            },
            {
                "id": "notif2",
                "type": "action.send_notification",
                "position": {"x": 500, "y": 100},
                "data": {
                    "label": "Confirm",
                    "config": {
                        "title": "Schedule Created",
                        "body": "Event '{{trigger.input.title}}' has been scheduled",
                        "type": "info"
                    }
                }
            }
        ],
        "edges": [
            {"id": "e1", "source": "trigger4", "target": "sched1"},
            {"id": "e2", "source": "sched1", "target": "notif2"}
        ],
        "variables": {}
    }
