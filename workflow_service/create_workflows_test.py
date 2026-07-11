"""
Create and test useful workflows for user.
Part 1: Setup and workflow definitions.
"""
import asyncio
import httpx
from datetime import datetime, timedelta, timezone

BASE_URL = "http://localhost:8001/api/v1"
JWT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODM1NzUyNTQsInN1YiI6IjljYjk1MDljLTQ5ZGUtNDE1Yi1hOTQ2LTQxZjAyY2JhMGMyZCIsInR5cGUiOiJhY2Nlc3MiLCJqdGkiOiJlM2FjZGUwYy1iYjJkLTQ0MTMtYTlkMC02NTZmOWJiYmU4NzUifQ.-_A5O4XlkgNUwym40JOauSr-Qcq9-ilNngJuAqu9PIg"
HEADERS = {"Authorization": f"Bearer {JWT_TOKEN}", "Content-Type": "application/json"}

async def create_workflow(client, name, description, definition, trigger_type="manual"):
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

async def execute_node(client, wf_id, node_id, config, trigger_data=None):
    payload = {
        "config": config,
        "trigger_data": trigger_data or {"event": "manual.trigger", "input": {}},
        "previous_outputs": {}
    }
    resp = await client.post(f"{BASE_URL}/workflows/{wf_id}/nodes/{node_id}/execute", 
                             headers=HEADERS, json=payload)
    return resp.status_code, resp.json()

def daily_summary_def():
    return {
        "nodes": [
            {"id": "tr1", "type": "trigger.manual", "position": {"x": 100, "y": 100},
             "data": {"label": "Start", "config": {}}},
            {"id": "ai1", "type": "action.call_ai", "position": {"x": 300, "y": 100},
             "data": {"label": "Generate Summary", "config": {
                 "prompt": "Write a brief motivational message for end of workday (under 50 words).",
                 "output_key": "message"}}},
            {"id": "note1", "type": "action.create_note", "position": {"x": 500, "y": 100},
             "data": {"label": "Save Note", "config": {
                 "title": "Daily Motivation - {{trigger.event}}",
                 "content": "{{steps.Generate Summary.message}}"}}},
            {"id": "notif1", "type": "action.send_notification", "position": {"x": 700, "y": 100},
             "data": {"label": "Notify", "config": {
                 "title": "Daily Summary Ready",
                 "body": "Check your notes!",
                 "type": "success"}}}
        ],
        "edges": [
            {"id": "e1", "source": "tr1", "target": "ai1"},
            {"id": "e2", "source": "ai1", "target": "note1"},
            {"id": "e3", "source": "note1", "target": "notif1"}
        ],
        "variables": {}
    }

def conditional_note_def():
    return {
        "nodes": [
            {"id": "tr2", "type": "trigger.manual", "position": {"x": 100, "y": 100},
             "data": {"label": "Manual Trigger", "config": {}}},
            {"id": "cond1", "type": "action.condition", "position": {"x": 300, "y": 100},
             "data": {"label": "Check Action", "config": {
                 "left": "{{trigger.input.action}}",
                 "operator": "equals",
                 "right": "update"}}},
            {"id": "update1", "type": "action.update_note", "position": {"x": 500, "y": 50},
             "data": {"label": "Update Note", "config": {
                 "note_id": "{{trigger.input.note_id}}",
                 "content": "Updated via workflow",
                 "append": True}}},
            {"id": "create1", "type": "action.create_note", "position": {"x": 500, "y": 150},
             "data": {"label": "Create Note", "config": {
                 "title": "New Note",
                 "content": "Created via workflow"}}}
        ],
        "edges": [
            {"id": "e1", "source": "tr2", "target": "cond1"},
            {"id": "e2", "source": "cond1", "target": "update1", "source_handle": "true"},
            {"id": "e3", "source": "cond1", "target": "create1", "source_handle": "false"}
        ],
        "variables": {}
    }

async def main():
    print("=" * 60)
    print("Creating Useful Workflows and Testing Nodes")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # List existing workflows
        print("\n1. Current workflows:")
        resp = await client.get(f"{BASE_URL}/workflows", headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            print(f"   Total: {data.get('total', 0)}")
            for wf in data.get("items", [])[:5]:
                print(f"   - {wf['name']} (status: {wf['status']})")
        
        # Create Workflow 1: Daily Summary
        print("\n2. Creating 'Daily Motivation' workflow...")
        wf1 = await create_workflow(
            client,
            "Daily Motivation Summary",
            "AI-generated motivational message saved to notes",
            daily_summary_def(),
            "manual"
        )
        print(f"   Created: {wf1['id']}")
        
        # Test nodes in workflow 1
        print("\n3. Testing nodes in 'Daily Motivation':")
        
        # Test AI node
        print("   a) Testing AI node...")
        status, result = await execute_node(
            client, wf1["id"], "ai1",
            {"prompt": "Say hello world", "output_key": "message"}
        )
        print(f"      Status: {status}, Success: {result.get('success')}")
        if result.get("output"):
            print(f"      Output keys: {list(result['output'].keys())}")
        
        # Test Create Note
        print("   b) Testing Create Note node...")
        status, result = await execute_node(
            client, wf1["id"], "note1",
            {"title": "Test Note", "content": "Test content"}
        )
        print(f"      Status: {status}, Success: {result.get('success')}")
        if result.get("error"):
            print(f"      Error: {result['error'][:100]}")
        
        # Test Notification
        print("   c) Testing Notification node...")
        status, result = await execute_node(
            client, wf1["id"], "notif1",
            {"title": "Test", "body": "Test body", "type": "info"}
        )
        print(f"      Status: {status}, Success: {result.get('success')}")
        
        # Create Workflow 2: Conditional Note
        print("\n4. Creating 'Conditional Note Manager' workflow...")
        wf2 = await create_workflow(
            client,
            "Conditional Note Manager",
            "Update or create notes based on input condition",
            conditional_note_def(),
            "manual"
        )
        print(f"   Created: {wf2['id']}")
        
        # Test condition node
        print("\n5. Testing condition node (true branch):")
        status, result = await execute_node(
            client, wf2["id"], "cond1",
            {"left": "update", "operator": "equals", "right": "update"},
            {"event": "manual.trigger", "input": {"action": "update"}}
        )
        print(f"   Status: {status}, Result: {result.get('output', {}).get('branch')}")
        
        print("\n6. Testing condition node (false branch):")
        status, result = await execute_node(
            client, wf2["id"], "cond1",
            {"left": "create", "operator": "equals", "right": "update"},
            {"event": "manual.trigger", "input": {"action": "create"}}
        )
        print(f"   Status: {status}, Result: {result.get('output', {}).get('branch')}")
        
        print("\n" + "=" * 60)
        print("Workflow Creation Complete!")
        print(f"Workflow 1: {wf1['id']} - Daily Motivation Summary")
        print(f"Workflow 2: {wf2['id']} - Conditional Note Manager")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
