"""
SSE channel for agent streaming events.

Handles real-time streaming of:
- Tool execution progress
- Token-by-token text generation
- Completion and error events
"""

from uuid import UUID
from app.api.sse.sse_manager import SSEManager
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Channel type identifier
AGENT_CHANNEL_TYPE = "agent-events"


async def publish_agent_event(user_id: UUID | str, event: dict) -> int:
    """
    Publish an agent event to a user's SSE stream.
    
    Args:
        user_id: UUID or string ID of the user
        event: Event dictionary with structure:
            {
                "event": "tool_start" | "tool_result" | "token" | "done" | "error",
                ... event-specific data
            }
    
    Returns:
        Number of connections that received the event
        
    Example:
        await publish_agent_event(user_id, {
            "event": "tool_start",
            "tool": "search_notes",
            "input": {"query": "meeting notes"}
        })
    """
    manager = SSEManager()
    context_key = f"user:{user_id}"
    
    # Broadcast to all connections for this user
    count = await manager.broadcast_message(
        channel_type=AGENT_CHANNEL_TYPE,
        context_key=context_key,
        message=event
    )
    
    if count > 0:
        logger.debug(
            f"Published agent event to {count} connection(s) | "
            f"user={user_id} | event={event.get('event')}"
        )
    
    return count


async def has_active_subscribers(user_id: UUID | str) -> bool:
    """
    Check if a user has any active SSE connections.
    
    Args:
        user_id: UUID or string ID of the user
    
    Returns:
        True if user has at least one active connection
    """
    manager = SSEManager()
    context_key = f"user:{user_id}"
    return await manager.has_active_connections(
        channel_type=AGENT_CHANNEL_TYPE,
        context_key=context_key
    )


async def get_subscriber_count(user_id: UUID | str) -> int:
    """
    Get number of active SSE connections for a user.
    
    Args:
        user_id: UUID or string ID of the user
    
    Returns:
        Number of active connections
    """
    manager = SSEManager()
    context_key = f"user:{user_id}"
    return await manager.get_connection_count(
        channel_type=AGENT_CHANNEL_TYPE,
        context_key=context_key
    )


# Event schemas for documentation

TOOL_START_EVENT = {
    "event": "tool_start",
    "tool": "search_notes",  # Tool name
    "input": {"query": "..."}  # Tool arguments
}

TOOL_RESULT_EVENT = {
    "event": "tool_result",
    "tool": "search_notes",  # Tool name
    "output": {...}  # Tool result
}

TOKEN_EVENT = {
    "event": "token",
    "text": "partial text chunk"  # Text to append
}

DONE_EVENT = {
    "event": "done",
    "conversation_id": "uuid-here"  # Completed conversation ID
}

ERROR_EVENT = {
    "event": "error",
    "message": "error description"  # Error message
}
