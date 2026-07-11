import asyncio
import httpx

WORKFLOW_ID = "060d749b-052a-468d-8966-1d049d8bf253"
JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODM1OTE5MTgsInN1YiI6IjljYjk1MDljLTQ5ZGUtNDE1Yi1hOTQ2LTQxZjAyY2JhMGMyZCIsInR5cGUiOiJhY2Nlc3MiLCJqdGkiOiJkYmIwMWE4NC0yYTdhLTQxNTYtODVmNC1kNmY5N2FhNDc1YmUifQ.eNFDjAR59nTnamicbLdj-vArK3Psban_7IY3iwGcmaY"
HEADERS = {"Authorization": f"Bearer {JWT}", "Content-Type": "application/json"}

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Call execute_node endpoint
        payload = {
            "config": {
                "title": "Test Note from Node",
                "content": "Test content from execute_node",
                "workspace_id": "ed991939-cf72-4fe9-9f24-2140333bf465"
            },
            "trigger_data": {"event": "manual.trigger", "input": {}},
            "previous_outputs": {}
        }
        print(f"Sending to: http://localhost:8001/api/v1/workflows/{WORKFLOW_ID}/nodes/note1/execute")
        print(f"Payload: {payload}")
        resp = await client.post(
            f"http://localhost:8001/api/v1/workflows/{WORKFLOW_ID}/nodes/note1/execute",
            headers=HEADERS, json=payload
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")

asyncio.run(main())
