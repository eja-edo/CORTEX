import httpx
import asyncio

async def test():
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test internal API key
        resp = await client.post(
            "http://localhost:8000/api/notes",
            json={"title": "Test Note", "content": "Test content"},
            headers={
                "X-Internal-API-Key": "cortex-internal-key-2024",
                "X-User-ID": "9cb9509c-49de-415b-a946-41f02cba0c2d"
            }
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text[:200]}")

asyncio.run(test())
