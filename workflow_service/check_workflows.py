import asyncio
import httpx

BASE_URL = "http://localhost:8001/api/v1"
JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODM1NzUyNTQsInN1YiI6IjljYjk1MDljLTQ5ZGUtNDE1Yi1hOTQ2LTQxZjAyY2JhMGMyZCIsInR5cGUiOiJhY2Nlc3MiLCJqdGkiOiJlM2FjZGUwYy1iYjJkLTQ0MTMtYTlkMC02NTZmOWJiYmU4NzUifQ.-_A5O4XlkgNUwym40JOauSr-Qcq9-ilNngJuAqu9PIg"
HEADERS = {"Authorization": f"Bearer {JWT}"}

async def main():
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{BASE_URL}/workflows", headers=HEADERS)
        data = resp.json()
        print(f"Total workflows: {data.get('total')}")
        for wf in data.get("items", []):
            print(f"  - ID: {wf['id']}")
            print(f"    Name: {wf['name']}")
            print(f"    Status: {wf['status']}")
            print(f"    Workspace: {wf.get('workspace_id') or 'personal'}")
            print()

asyncio.run(main())
