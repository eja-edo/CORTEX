"""
Test script to call agent chat API and debug schema errors.
Simulates frontend calling the API.
"""

import asyncio
import httpx
import json
from uuid import uuid4

BASE_URL = "http://127.0.0.1:8000"
API_KEY = "test_key"

async def test_agent_chat():
    """Test agent chat endpoint."""
    
    # Create test data
    workspace_id = str(uuid4())
    user_message = "Hello, I'm looking for my notes about Python"
    
    # Request payload
    payload = {
        "message": user_message,
        "workspace_id": workspace_id,
    }
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    
    # Call API
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"🔄 Calling POST {BASE_URL}/api/agent/chat")
            print(f"📤 Payload: {json.dumps(payload, indent=2)}")
            
            response = await client.post(
                f"{BASE_URL}/api/agent/chat",
                json=payload,
                headers=headers,
            )
            
            print(f"\n✅ Response Status: {response.status_code}")
            print(f"📥 Response Body: {response.text}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"\n✅ Success! Agent response:")
                print(f"  - Conversation ID: {data.get('conversation_id')}")
                print(f"  - Reply: {data.get('reply')}")
            else:
                print(f"\n❌ Error: {response.status_code}")
                try:
                    error = response.json()
                    print(f"  - Detail: {error.get('detail', 'No detail')}")
                except:
                    print(f"  - Body: {response.text}")
        
        except Exception as e:
            print(f"❌ Exception: {e}")


async def test_schema_validation():
    """Test that schemas can be loaded without errors."""
    print("\n" + "="*60)
    print("🧪 Testing Schema Validation")
    print("="*60 + "\n")
    
    try:
        from app.services.agent.tool_registry import get_tool_registry
        
        registry = get_tool_registry()
        tools = registry.list_tools()
        
        print(f"✅ Tool Registry loaded successfully!")
        print(f"📋 Registered tools: {tools}")
        
        for tool_name in tools:
            tool = registry.tools[tool_name]
            print(f"\n  Tool: {tool_name}")
            print(f"    - Name: {tool.name}")
            print(f"    - Description: {tool.description[:50]}...")
            
            schema = tool.schema
            print(f"    - Schema type: {schema.get('type', 'MISSING')}")
            print(f"    - Properties: {list(schema.get('properties', {}).keys())}")
            print(f"    - Required: {schema.get('required', [])}")
            
            # Try to convert to gemini format
            try:
                gemini_fmt = tool.to_gemini_format()
                print(f"    ✅ Gemini format OK")
            except Exception as e:
                print(f"    ❌ Gemini format error: {e}")
    
    except Exception as e:
        print(f"❌ Error loading schemas: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("="*60)
    print("🤖 Agent Chat API Test Script")
    print("="*60 + "\n")
    
    # First, test schemas offline
    await test_schema_validation()
    
    # Then try to call the API
    print("\n" + "="*60)
    print("🌐 Testing API Call")
    print("="*60 + "\n")
    
    await test_agent_chat()


if __name__ == "__main__":
    asyncio.run(main())
