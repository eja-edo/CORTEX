import asyncio
import httpx

BASE_URL = "http://localhost:8001/api/v1"
JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODM1NzUyNTQsInN1YiI6IjljYjk1MDljLTQ5ZGUtNDE1Yi1hOTQ2LTQxZjAyY2JhMGMyZCIsInR5cGUiOiJhY2Nlc3MiLCJqdGkiOiJlM2FjZGUwYy1iYjJkLTQ0MTMtYTlkMC02NTZmOWJiYmU4NzUifQ.-_A5O4XlkgNUwym40JOauSr-Qcq9-ilNngJuAqu9PIg"
HEADERS = {"Authorization": f"Bearer {JWT}", "Content-Type": "application/json"}
WORKSPACE_ID = "ed991939-cf72-4fe9-9f24-2140333bf465"

async def create_workflow(client, name, description, definition, trigger_type="manual"):
    payload = {
        "name": name,
        "description": description,
        "workspace_id": WORKSPACE_ID,
        "trigger_type": trigger_type,
        "trigger_config": {},
        "definition": definition
    }
    resp = await client.post(f"{BASE_URL}/workflows", headers=HEADERS, json=payload)
    resp.raise_for_status()
    return resp.json()

async def activate_workflow(client, wf_id):
    resp = await client.post(f"{BASE_URL}/workflows/{wf_id}/activate", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

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
                 "content": "Updated via workflow at {{trigger.event}}",
                 "append": True}}},
            {"id": "create1", "type": "action.create_note", "position": {"x": 500, "y": 150},
             "data": {"label": "Create Note", "config": {
                 "title": "New Note via Workflow",
                 "content": "Created automatically"}}}
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
    print("Creating Workflows in Workspace")
    print(f"Workspace ID: {WORKSPACE_ID}")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create Workflow 1
        print("\n1. Creating 'Daily Motivation Summary'...")
        wf1 = await create_workflow(
            client, "Daily Motivation Summary",
            "AI-generated motivational message saved to notes",
            daily_summary_def(), "manual"
        )
        print(f"   Created: {wf1['id']}")
        
        # Activate Workflow 1
        print("   Activating...")
        wf1_active = await activate_workflow(client, wf1["id"])
        print(f"   Status: {wf1_active['status']}")
        
        # Create Workflow 2
        print("\n2. Creating 'Conditional Note Manager'...")
        wf2 = await create_workflow(
            client, "Conditional Note Manager",
            "Update or create notes based on input condition",
            conditional_note_def(), "manual"
        )
        print(f"   Created: {wf2['id']}")
        
        # Activate Workflow 2
        print("   Activating...")
        wf2_active = await activate_workflow(client, wf2["id"])
        print(f"   Status: {wf2_active['status']}")
        
        print("\n" + "=" * 60)
        print("Complete!")
        print(f"Workflow 1: {wf1['id']}")
        print(f"Workflow 2: {wf2['id']}")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
