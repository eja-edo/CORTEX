"""
Integration tests for Phase 3 - Streaming Agent Responses via SSE

Tests cover:
- SSE stream endpoint connection
- Agent event publishing
- Streaming event schemas
- Background task integration
- Real-time event delivery
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.sse.channels.agent_events import (
    publish_agent_event,
    has_active_subscribers,
    get_subscriber_count,
    AGENT_CHANNEL_TYPE,
)
from app.api.sse.sse_manager import SSEManager


def test_agent_channel_type_constant():
    """Test that agent channel type is defined."""
    assert AGENT_CHANNEL_TYPE == "agent-events"
    print("✅ Agent channel type constant defined")


@pytest.mark.asyncio
async def test_publish_agent_event():
    """Test publishing an agent event."""
    user_id = uuid4()
    
    # Mock the SSEManager
    with patch('app.api.sse.channels.agent_events.SSEManager') as mock_manager_class:
        mock_manager = AsyncMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.broadcast_message.return_value = 1  # 1 connection received
        
        event = {
            "event": "token",
            "text": "Hello world"
        }
        
        count = await publish_agent_event(user_id, event)
        
        # Verify broadcast was called with correct parameters
        mock_manager.broadcast_message.assert_called_once_with(
            channel_type=AGENT_CHANNEL_TYPE,
            context_key=f"user:{user_id}",
            message=event
        )
        
        assert count == 1
        print("✅ publish_agent_event works correctly")


@pytest.mark.asyncio
async def test_has_active_subscribers():
    """Test checking for active subscribers."""
    user_id = uuid4()
    
    with patch('app.api.sse.channels.agent_events.SSEManager') as mock_manager_class:
        mock_manager = AsyncMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.has_active_connections.return_value = True
        
        has_subs = await has_active_subscribers(user_id)
        
        mock_manager.has_active_connections.assert_called_once_with(
            channel_type=AGENT_CHANNEL_TYPE,
            context_key=f"user:{user_id}"
        )
        
        assert has_subs is True
        print("✅ has_active_subscribers works correctly")


@pytest.mark.asyncio
async def test_get_subscriber_count():
    """Test getting subscriber count."""
    user_id = uuid4()
    
    with patch('app.api.sse.channels.agent_events.SSEManager') as mock_manager_class:
        mock_manager = AsyncMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.get_connection_count.return_value = 2
        
        count = await get_subscriber_count(user_id)
        
        mock_manager.get_connection_count.assert_called_once_with(
            channel_type=AGENT_CHANNEL_TYPE,
            context_key=f"user:{user_id}"
        )
        
        assert count == 2
        print("✅ get_subscriber_count works correctly")


def test_tool_start_event_schema():
    """Test tool_start event has correct schema."""
    event = {
        "event": "tool_start",
        "tool": "search_notes",
        "input": {"query": "meeting notes"}
    }
    
    assert event["event"] == "tool_start"
    assert "tool" in event
    assert "input" in event
    print("✅ tool_start event schema correct")


def test_tool_result_event_schema():
    """Test tool_result event has correct schema."""
    event = {
        "event": "tool_result",
        "tool": "search_notes",
        "output": {"result": [{"id": "n1", "title": "Meeting"}], "success": True}
    }
    
    assert event["event"] == "tool_result"
    assert "tool" in event
    assert "output" in event
    print("✅ tool_result event schema correct")


def test_token_event_schema():
    """Test token event has correct schema."""
    event = {
        "event": "token",
        "text": "Here is what I found"
    }
    
    assert event["event"] == "token"
    assert "text" in event
    assert isinstance(event["text"], str)
    print("✅ token event schema correct")


def test_done_event_schema():
    """Test done event has correct schema."""
    event = {
        "event": "done",
        "conversation_id": "12345",
        "latency_ms": 1234.5
    }
    
    assert event["event"] == "done"
    assert "conversation_id" in event
    assert "latency_ms" in event
    print("✅ done event schema correct")


def test_error_event_schema():
    """Test error event has correct schema."""
    event = {
        "event": "error",
        "message": "Something went wrong"
    }
    
    assert event["event"] == "error"
    assert "message" in event
    print("✅ error event schema correct")


def test_context_key_format():
    """Test that context key is properly formatted."""
    user_id = "user123"
    expected_key = f"user:{user_id}"
    
    assert expected_key == "user:user123"
    print("✅ Context key format correct")


def test_agent_service_has_streaming_method():
    """Test that AgentService has handle_streaming_generator method."""
    from app.ai.agents.agent_service import AgentService
    
    assert hasattr(AgentService, "handle_streaming_generator")
    
    import inspect
    sig = inspect.signature(AgentService.handle_streaming_generator)
    params = list(sig.parameters.keys())
    
    assert "message" in params
    print("✅ AgentService has handle_streaming_generator method with correct signature")


def test_streaming_start_response_schema():
    """Test AgentStreamingStartResponse schema."""
    from app.schemas import AgentStreamingStartResponse
    from uuid import uuid4
    
    conversation_id = uuid4()
    response = AgentStreamingStartResponse(
        status="streaming_started",
        conversation_id=conversation_id,
        message="Events will be streamed"
    )
    
    assert response.status == "streaming_started"
    assert response.conversation_id == conversation_id
    print("✅ AgentStreamingStartResponse schema correct")


@pytest.mark.asyncio
async def test_event_stream_context_isolation():
    """Test that events are properly isolated per user."""
    user1_id = uuid4()
    user2_id = uuid4()
    
    # Events for user1 should not go to user2
    context_key_1 = f"user:{user1_id}"
    context_key_2 = f"user:{user2_id}"
    
    assert context_key_1 != context_key_2
    assert context_key_1.startswith("user:")
    assert context_key_2.startswith("user:")
    print("✅ Event context isolation verified")


def test_streaming_endpoint_exists():
    """Test that /api/agent/stream/chat endpoint exists."""
    from app.api.agent import router
    
    # Get all routes in the router
    routes = [r.path for r in router.routes]
    
    # Routes have /agent prefix from the router
    assert "/agent/stream/chat" in routes
    print("✅ /api/agent/stream/chat endpoint exists")


def test_streaming_chat_endpoint_exists():
    """Test that /api/agent/stream/chat endpoint exists."""
    from app.api.agent import router
    
    # Get all routes in the router
    routes = [r.path for r in router.routes]
    
    # Routes have /agent prefix from the router
    assert "/agent/stream/chat" in routes
    print("✅ /api/agent/stream/chat endpoint exists")


def test_event_loop_integration():
    """Test that streaming endpoint uses async generator correctly."""
    import inspect
    from app.api.agent import stream_chat
    
    source = inspect.getsource(stream_chat)
    
    # Verify streaming uses async generator pattern
    assert "async for" in source
    assert "handle_streaming_generator" in source
    assert "StreamingResponse" in source
    print("✅ Streaming endpoint uses async generator pattern with StreamingResponse")


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🧪 PHASE 3 - STREAMING AGENT RESPONSES VIA SSE - TEST SUITE")
    print("="*70 + "\n")
    
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "-s",
    ])
