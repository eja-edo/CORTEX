import asyncio
import httpx

JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI5Y2I5NTA5Yy00OWRlLTQxNWItYTk0Ni00MWYwMmNiYTBjMmQiLCJlbWFpbCI6ImR1eWFuaHNhZGdAZ21haWwuY29tIiwiZXhwIjoxNzg2MTg0MzE3LCJpYXQiOjE3ODM1OTIzMTcsInR5cGUiOiJhY2Nlc3MiLCJqdGkiOiI0NGYzZWIxYy03Yjc2LTQwMTktOWI3MC0wYzFmZmE2ZmM4OGMifQ.JfUhMEpV04usSqDwNZZe9uBE0wDGB9_1bWWl3hN6slA"
HEADERS = {"Authorization": f"Bearer {JWT}", "Content-Type": "application/json"}
WORKFLOW_ID = "060d749b-052a-468d-8966-1d049d8bf253"

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get workflow
        resp = await client.get(
            f"http://localhost:8001/api/v1/workflows/{WORKFLOW_ID}",
            headers=HEADERS
        )
        if resp.status_code == 200:
            wf = resp.json()
            print(f"Name: {wf['name']}")
            print(f"Status: {wf['status']}")
            print(f"Definition nodes:")
            for node in wf['definition']['nodes']:
                print(f"  - {node['id']}: {node['type']}")
                if 'config' in node.get('data', {}):
                    print(f"    config: {node['data']['config']}")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")

asyncio.run(main())
