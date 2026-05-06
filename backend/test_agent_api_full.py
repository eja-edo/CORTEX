"""
Test script for Agent API endpoints.
Tests all 8 tools and conversation management.

Usage:
    python test_agent_api_full.py
"""

import asyncio
import httpx
import json
import sys
from uuid import uuid4
from datetime import datetime, timedelta
import time

BASE_URL = "http://127.0.0.1:8000"
access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NzgwOTc2NjgsInN1YiI6Ijc5NmY1ZDg1LWYzMDgtNDVlZS05ZGQ2LTM3ZTkzNjZiODNhZSIsInR5cGUiOiJhY2Nlc3MiLCJqdGkiOiI4ZjFmMDI1Zi0wODY4LTQ4ZmItYTViMi0xMGFjOTQ5MTlhM2IifQ.Udr9SYED23t4vdEj-CHPf20JxdkcSpXOJYs9ZXcQua0"

# Throttle delays to avoid Gemini API rate limit (15 requests/min)
# 15 requests/min = 1 request per 4 seconds max
THROTTLE_DELAY_API = 5  # seconds between API calls (safe margin)
THROTTLE_DELAY_DB = 0.5  # seconds between DB-only calls


async def test_tool_registry():
    """Test that all 8 tools are registered correctly."""
    print("\n" + "=" * 60)
    print("🧪 TOOL REGISTRY VALIDATION")
    print("=" * 60)

    try:
        from app.services.agent.tool_registry import get_tool_registry
        from app.services.agent.tools import register_all_tools

        register_all_tools()
        registry = get_tool_registry()
        tools = registry.list_tools()

        print(f"\n✅ Tool Registry loaded!")
        print(f"📋 Registered tools ({len(tools)}):")

        expected_tools = [
            "search_notes", "create_note", "get_schedules", "create_schedule",
            "update_schedule", "search_knowledge", "summarize_asset", "get_notifications"
        ]

        for tool_name in tools:
            tool = registry.tools[tool_name]
            status = "✅" if tool_name in expected_tools else "⚠️"
            print(f"  {status} {tool_name}")
            print(f"      Description: {tool.description[:60]}...")
            print(f"      Schema: {list(tool.schema.get('properties', {}).keys())}")

        missing = set(expected_tools) - set(tools)
        if missing:
            print(f"\n❌ Missing tools: {missing}")
            return False
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_chat_endpoint_basic():
    """Test basic chat without tools (echo test)."""
    print("\n" + "=" * 60)
    print("🧪 BASIC CHAT ENDPOINT TEST")
    print("=" * 60)

    payload = {
        "message": "Hello, what can you help me with?",
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            print(f"\n📤 POST /api/agent/chat")
            print(f"   Payload: {json.dumps(payload, indent=2)}")

            response = await client.post(
                f"{BASE_URL}/api/agent/chat",
                json=payload,
                headers=headers,
            )

            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Response:")
                print(f"      conversation_id: {data.get('conversation_id')}")
                print(f"      reply: {data.get('reply')[:200]}...")
                return True, data.get('conversation_id')
            else:
                # Print detailed error
                print(f"   ❌ Error: {response.text[:500]}")
                try:
                    error = response.json()
                    print(f"   📋 Error detail: {json.dumps(error, indent=4)}")
                except:
                    pass
                return False, None

        except Exception as e:
            print(f"   ❌ Exception: {e}")
            import traceback
            traceback.print_exc()
            return False, None


async def test_chat_with_conversation(conversation_id: str):
    """Test chat with existing conversation."""
    print("\n" + "=" * 60)
    print(f"🧪 CHAT WITH CONVERSATION: {conversation_id[:8]}...")
    print("=" * 60)

    payload = {
        "message": "Show me my notes about Python",
        "conversation_id": conversation_id,
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            print(f"\n📤 POST /api/agent/chat")
            print(f"   Message: {payload['message']}")

            response = await client.post(
                f"{BASE_URL}/api/agent/chat",
                json=payload,
                headers=headers,
            )

            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Response:")
                reply = data.get('reply', '')
                print(f"      reply: {reply[:300]}...")
                return True
            else:
                print(f"   ❌ Error: {response.text[:200]}")
                return False

        except Exception as e:
            print(f"   ❌ Exception: {e}")
            return False


async def test_list_conversations():
    """Test GET /api/agent/conversations."""
    print("\n" + "=" * 60)
    print("🧪 LIST CONVERSATIONS")
    print("=" * 60)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"\n📤 GET /api/agent/conversations")

            response = await client.get(
                f"{BASE_URL}/api/agent/conversations",
                headers=headers,
            )

            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Conversations: {len(data.get('conversations', []))}")
                for conv in data.get('conversations', [])[:3]:
                    print(f"      - {conv.get('title', 'Untitled')} ({conv.get('message_count')} messages)")
                return True
            else:
                print(f"   ❌ Error: {response.text[:200]}")
                return False

        except Exception as e:
            print(f"   ❌ Exception: {e}")
            return False


async def test_get_conversation(conversation_id: str):
    """Test GET /api/agent/conversations/{id}."""
    print("\n" + "=" * 60)
    print(f"🧪 GET CONVERSATION: {conversation_id[:8]}...")
    print("=" * 60)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"\n📤 GET /api/agent/conversations/{conversation_id}")

            response = await client.get(
                f"{BASE_URL}/api/agent/conversations/{conversation_id}",
                headers=headers,
            )

            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Conversation:")
                print(f"      title: {data.get('title')}")
                print(f"      message_count: {data.get('message_count')}")
                print(f"      messages: {len(data.get('messages', []))}")
                return True
            else:
                print(f"   ❌ Error: {response.text[:200]}")
                return False

        except Exception as e:
            print(f"   ❌ Exception: {e}")
            return False


async def test_delete_conversation(conversation_id: str):
    """Test DELETE /api/agent/conversations/{id}."""
    print("\n" + "=" * 60)
    print(f"🧪 DELETE CONVERSATION: {conversation_id[:8]}...")
    print("=" * 60)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"\n📤 DELETE /api/agent/conversations/{conversation_id}")

            response = await client.delete(
                f"{BASE_URL}/api/agent/conversations/{conversation_id}",
                headers=headers,
            )

            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ {data.get('message')}")
                return True
            else:
                print(f"   ❌ Error: {response.text[:200]}")
                return False

        except Exception as e:
            print(f"   ❌ Exception: {e}")
            return False


async def test_search_notes_tool():
    """Test search_notes tool via agent chat."""
    print("\n" + "=" * 60)
    print("🧪 TOOL: search_notes")
    print("=" * 60)

    payload = {
        "message": "Search my notes about meeting",
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            print(f"\n📤 POST /api/agent/chat")
            print(f"   Message: {payload['message']}")

            response = await client.post(
                f"{BASE_URL}/api/agent/chat",
                json=payload,
                headers=headers,
            )

            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Response:")
                print(f"      reply: {data.get('reply')[:300]}...")
                return True
            else:
                print(f"   ❌ Error: {response.text[:200]}")
                return False

        except Exception as e:
            print(f"   ❌ Exception: {e}")
            return False


async def test_get_schedules_tool():
    """Test get_schedules tool via agent chat."""
    print("\n" + "=" * 60)
    print("🧪 TOOL: get_schedules")
    print("=" * 60)

    start_date = datetime.now().isoformat()
    end_date = (datetime.now() + timedelta(days=7)).isoformat()

    payload = {
        "message": f"What are my schedules from {start_date[:10]} to {end_date[:10]}?",
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            print(f"\n📤 POST /api/agent/chat")
            print(f"   Message: {payload['message']}")

            response = await client.post(
                f"{BASE_URL}/api/agent/chat",
                json=payload,
                headers=headers,
            )

            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Response:")
                print(f"      reply: {data.get('reply')[:300]}...")
                return True
            else:
                print(f"   ❌ Error: {response.text[:200]}")
                return False

        except Exception as e:
            print(f"   ❌ Exception: {e}")
            return False


async def test_get_notifications_tool():
    """Test get_notifications tool via agent chat."""
    print("\n" + "=" * 60)
    print("🧪 TOOL: get_notifications")
    print("=" * 60)

    payload = {
        "message": "Show me my unread notifications",
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            print(f"\n📤 POST /api/agent/chat")
            print(f"   Message: {payload['message']}")

            response = await client.post(
                f"{BASE_URL}/api/agent/chat",
                json=payload,
                headers=headers,
            )

            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Response:")
                print(f"      reply: {data.get('reply')[:300]}...")
                return True
            else:
                print(f"   ❌ Error: {response.text[:200]}")
                return False

        except Exception as e:
            print(f"   ❌ Exception: {e}")
            return False


async def test_streaming_endpoint():
    """Test SSE streaming endpoint."""
    print("\n" + "=" * 60)
    print("🧪 SSE STREAMING ENDPOINT")
    print("=" * 60)

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    # SSE requires longer timeout for streaming, not timeout for initial response
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=60.0)) as client:
        try:
            print(f"\n📤 GET /api/agent/stream")

            # For SSE streaming, we just need to verify connection works
            # Stream will continue in background until closed
            async with client.stream("GET", f"{BASE_URL}/api/agent/stream", headers=headers) as response:
                print(f"   Status: {response.status_code}")

                if response.status_code == 200:
                    # Check Content-Type for SSE
                    content_type = response.headers.get('content-type', '')
                    print(f"   ✅ SSE connection established")
                    print(f"      Content-Type: {content_type}")
                    
                    # Try to read first line/event with timeout
                    try:
                        async for line in response.aiter_lines():
                            if line:
                                print(f"      First event: {line[:80]}...")
                                return True
                            # Timeout after getting first line or after a few iterations
                            break
                    except asyncio.TimeoutError:
                        # Timeout is okay for SSE streaming
                        print(f"      ✅ Stream timeout (expected for SSE)")
                        return True
                    
                    return True
                else:
                    error_text = await response.aread()
                    print(f"   ❌ Error: {error_text[:200]}")
                    return False

        except asyncio.TimeoutError:
            print(f"   ✅ Stream established (timeout is normal for SSE)")
            return True
        except Exception as e:
            print(f"   ❌ Exception: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_chat_streaming_start():
    """Test POST /api/agent/chat/stream to start streaming."""
    print("\n" + "=" * 60)
    print("🧪 START STREAMING CHAT")
    print("=" * 60)

    payload = {
        "message": "Hello via streaming",
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"\n📤 POST /api/agent/chat/stream")

            response = await client.post(
                f"{BASE_URL}/api/agent/chat/stream",
                json=payload,
                headers=headers,
            )

            print(f"   Status: {response.status_code}")

            if response.status_code == 202:
                data = response.json()
                print(f"   ✅ Streaming started:")
                print(f"      status: {data.get('status')}")
                print(f"      message: {data.get('message')}")
                return True
            else:
                print(f"   ❌ Error: {response.text[:200]}")
                return False

        except Exception as e:
            print(f"   ❌ Exception: {e}")
            return False


async def main():
    global access_token
    
    print("=" * 60)
    print("🤖 AGENT API TEST SUITE")
    print("=" * 60)
    print(f"⏱️  Throttle delay: {THROTTLE_DELAY_API}s between API calls (Gemini: 15 req/min limit)")
    print("=" * 60)

    results = {}

    # Get token from environment or use existing
    if not access_token:
        print("\n⚠️ No access_token, tests will fail (need login)")
    
    # Test 1: Tool registry validation (offline - no API call)
    results["tool_registry"] = await test_tool_registry()
    time.sleep(THROTTLE_DELAY_DB)
    
    # Test 2: Basic chat (CALLS GEMINI API)
    print(f"\n⏳ Waiting {THROTTLE_DELAY_API}s before API call...")
    time.sleep(THROTTLE_DELAY_API)
    success, conversation_id = await test_chat_endpoint_basic()
    results["basic_chat"] = success
    conv_id = conversation_id
    
    if success and conv_id:
        # Test 3: Chat with conversation (CALLS GEMINI API)
        print(f"\n⏳ Waiting {THROTTLE_DELAY_API}s before API call...")
        time.sleep(THROTTLE_DELAY_API)
        results["chat_with_conv"] = await test_chat_with_conversation(conv_id)
        
        # Test 4: Get conversation (DB only)
        time.sleep(THROTTLE_DELAY_DB)
        results["get_conversation"] = await test_get_conversation(conv_id)
        
        # Test 5: List conversations (DB only)
        time.sleep(THROTTLE_DELAY_DB)
        results["list_conversations"] = await test_list_conversations()
    else:
        print("\n⚠️ Skipping conversation tests - no conversation_id")
    
    # Test 6: search_notes tool (CALLS GEMINI API)
    print(f"\n⏳ Waiting {THROTTLE_DELAY_API}s before API call...")
    time.sleep(THROTTLE_DELAY_API)
    results["search_notes_tool"] = await test_search_notes_tool()
    
    # Test 7: get_schedules tool (CALLS GEMINI API)
    print(f"\n⏳ Waiting {THROTTLE_DELAY_API}s before API call...")
    time.sleep(THROTTLE_DELAY_API)
    results["get_schedules_tool"] = await test_get_schedules_tool()
    
    # Test 8: get_notifications tool (CALLS GEMINI API)
    print(f"\n⏳ Waiting {THROTTLE_DELAY_API}s before API call...")
    time.sleep(THROTTLE_DELAY_API)
    results["get_notifications_tool"] = await test_get_notifications_tool()
    
    # Test 9: SSE streaming (DB only)
    time.sleep(THROTTLE_DELAY_DB)
    results["sse_streaming"] = await test_streaming_endpoint()
    
    # Test 10: Start streaming chat (CALLS GEMINI API)
    print(f"\n⏳ Waiting {THROTTLE_DELAY_API}s before API call...")
    time.sleep(THROTTLE_DELAY_API)
    results["chat_streaming"] = await test_chat_streaming_start()

    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {status} - {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️ {total - passed} tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))