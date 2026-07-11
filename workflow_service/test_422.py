"""Test backend Notes API với payload validation"""
import httpx
import asyncio

async def test():
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test với full payload
        payload = {
            "title": "Test Note",
            "content": "Test content",
            "workspace_id": "ed991939-cf72-4fe9-9f24-2140333bf465"
        }
        resp = await client.post(
            "http://localhost:8000/api/notes",
            json=payload,
            headers={
                "X-Internal-API-Key": "cortex-internal-key-2024",
                "X-User-ID": "9cb9509c-49de-415b-a946-41f02cba0c2d"
            }
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")

asyncio.run(test())
