"""
Test Create Note and Update Note với workspace_id
"""
import asyncio
import httpx

BASE_URL = "http://localhost:8001/api/v1"
JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODM1NzUyNTQsInN1YiI6IjljYjk1MDljLTQ5ZGUtNDE1Yi1hOTQ2LTQxZjAyY2JhMGMyZCIsInR5cGUiOiJhY2Nlc3MiLCJqdGkiOiJlM2FjZGUwYy1iYjJkLTQ0MTMtYTlkMC02NTZmOWJiYmU4NzUifQ.-_A5O4XlkgNUwym40JOauSr-Qcq9-ilNngJuAqu9PIg"
HEADERS = {"Authorization": f"Bearer {JWT}", "Content-Type": "application/json"}
WORKSPACE_ID = "ed991939-cf72-4fe9-9f24-2140333bf465"
WORKFLOW_ID = "060d749b-052a-468d-8966-1d049d8bf253"

async def execute_node(client, wf_id, node_id, config, trigger_data=None):
    payload = {
        "config": config,
        "trigger_data": trigger_data or {"event": "manual.trigger", "input": {}},
        "previous_outputs": {}
    }
    resp = await client.post(
        f"{BASE_URL}/workflows/{wf_id}/nodes/{node_id}/execute",
        headers=HEADERS, json=payload
    )
    return resp.status_code, resp.json()

async def main():
    print("=" * 60)
    print("Testing Create Note with workspace_id")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Test 1: Create note WITH workspace_id
        print("\n1. Create Note WITH workspace_id:")
        status, result = await execute_node(
            client, WORKFLOW_ID, "note1",
            {
                "title": "Test Note in Workspace",
                "content": "This should appear in workspace",
                "workspace_id": WORKSPACE_ID
            }
        )
        print(f"   Status: {status}")
        print(f"   Success: {result.get('success')}")
        if result.get('output'):
            print(f"   Note ID: {result['output'].get('note_id')}")
            print(f"   Title: {result['output'].get('title')}")
        if result.get('error'):
            print(f"   Error: {result['error'][:100]}")
        
        # Test 2: Create note WITHOUT workspace_id (personal)
        print("\n2. Create Note WITHOUT workspace_id (personal):")
        status, result = await execute_node(
            client, WORKFLOW_ID, "note1",
            {
                "title": "Test Note Personal",
                "content": "This goes to personal workspace"
            }
        )
        print(f"   Status: {status}")
        print(f"   Success: {result.get('success')}")
        if result.get('output'):
            print(f"   Note ID: {result['output'].get('note_id')}")
        
        # Test 3: List notes from backend to verify
        print("\n3. Listing notes from backend:")
        backend_resp = await client.get(
            "http://localhost:8000/api/notes",
            headers={"Authorization": f"Bearer {JWT}"}
        )
        if backend_resp.status_code == 200:
            notes = backend_resp.json()
            print(f"   Total notes: {len(notes)}")
            for note in notes[:3]:
                print(f"   - {note['title']} (workspace: {note.get('workspace_id') or 'personal'})")
        else:
            print(f"   Backend error: {backend_resp.status_code}")
        
        print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
