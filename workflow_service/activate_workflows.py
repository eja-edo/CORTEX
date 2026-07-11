import asyncio
import httpx

BASE_URL = "http://localhost:8001/api/v1"
JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODM1NzUyNTQsInN1YiI6IjljYjk1MDljLTQ5ZGUtNDE1Yi1hOTQ2LTQxZjAyY2JhMGMyZCIsInR5cGUiOiJhY2Nlc3MiLCJqdGkiOiJlM2FjZGUwYy1iYjJkLTQ0MTMtYTlkMC02NTZmOWJiYmU4NzUifQ.-_A5O4XlkgNUwym40JOauSr-Qcq9-ilNngJuAqu9PIg"
HEADERS = {"Authorization": f"Bearer {JWT}"}

async def main():
    wf_ids = [
        "e26595af-00fb-427c-8199-5ca8213f82e5",  # Daily Motivation
        "382e9819-5293-4d91-af15-140f04d73f4e"   # Conditional Note Manager
    ]
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for wf_id in wf_ids:
            print(f"Activating workflow {wf_id}...")
            resp = await client.post(f"{BASE_URL}/workflows/{wf_id}/activate", headers=HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                print(f"  Success! Status: {data['status']}")
            else:
                print(f"  Failed: {resp.status_code}")
                print(f"     {resp.text[:200]}")

asyncio.run(main())
