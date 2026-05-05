"""Agent chat API endpoint for conversational AI interactions."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_active_user
from app.models import User
from app.schemas import (
    AgentChatRequest, 
    AgentChatResponse,
    AgentStreamingStartResponse
)
from app.services.agent.agent_service import AgentService
from app.api.sse.sse_manager import SSEManager
from app.api.sse.sse_base import event_generator, create_sse_response
from app.api.sse.channels.agent_events import AGENT_CHANNEL_TYPE
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse, status_code=status.HTTP_200_OK)
async def chat(
    payload: AgentChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> AgentChatResponse:
    """
    Send a message to the AI agent and get a response.
    
    Creates a new conversation if conversation_id is not provided.
    
    Args:
        payload: Chat request with message and optional conversation_id
        current_user: Authenticated user
        db: Async database session
        
    Returns:
        AgentChatResponse with conversation_id and reply text
        
    Raises:
        HTTPException: If agent service encounters an error
    """
    try:
        service = AgentService(user=current_user, db=db)
        result = await service.handle(
            message=payload.message,
            conversation_id=payload.conversation_id,
            workspace_id=payload.workspace_id,
        )
        
        return AgentChatResponse(
            conversation_id=UUID(result["conversation_id"]),
            reply=result["reply"],
        )
        
    except Exception as exc:
        logger.error(f"Error in agent chat: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process your message. Please try again.",
        ) from exc


@router.get("/stream")
async def stream_agent_events(
    current_user: User = Depends(get_current_active_user),
):
    """
    SSE endpoint for receiving agent events in real-time.
    
    Streams:
    - tool_start: Tool execution begins
    - tool_result: Tool execution completes
    - token: Streamed text tokens
    - done: Agent response complete
    - error: Error occurred
    
    Client should:
    1. Open SSE connection: const eventSource = new EventSource('/api/agent/stream')
    2. Send chat request: POST /api/agent/chat
    3. Listen for events: eventSource.addEventListener('token', ...)
    4. Close connection when done or on page unload
    
    Returns:
        StreamingResponse with SSE formatted events
    """
    try:
        manager = SSEManager()
        context_key = f"user:{current_user.id}"
        
        # Generate unique connection ID and register with manager
        connection_id = await manager.register_connection(
            channel_type=AGENT_CHANNEL_TYPE,
            context_key=context_key,
            appid=str(current_user.id),
        )
        
        # Disconnect any existing connection from this user to prevent duplicates
        await manager.disconnect_existing_appid(
            channel_type=AGENT_CHANNEL_TYPE,
            context_key=context_key,
            appid=str(current_user.id),
        )
        
        # Create queue for this connection
        connection_queue = await manager.create_connection_queue(
            channel_type=AGENT_CHANNEL_TYPE,
            context_key=context_key,
            connection_id=connection_id,
        )
        
        # Create event generator
        gen = event_generator(
            channel_type=AGENT_CHANNEL_TYPE,
            context_key=context_key,
            connection_id=connection_id,
            connection_queue=connection_queue,
            manager=manager,
            heartbeat_interval=30,
        )
        
        # Return SSE response
        return create_sse_response(gen)
        
    except Exception as exc:
        logger.error(f"Error in agent stream: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to establish streaming connection.",
        ) from exc


@router.post("/chat/stream", response_model=AgentStreamingStartResponse, status_code=status.HTTP_202_ACCEPTED)
async def chat_streaming(
    payload: AgentChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> AgentStreamingStartResponse:
    """
    Send a message to the AI agent and receive streaming response via SSE.
    
    This endpoint returns immediately (HTTP 202) and triggers background processing.
    The actual response is streamed via the /api/agent/stream endpoint.
    
    Client flow:
    1. Open SSE connection: new EventSource('/api/agent/stream')
    2. Send POST request to this endpoint
    3. Listen for events: token, tool_start, tool_result, done, error
    4. Close connection when done
    
    Args:
        payload: Chat request with message and optional conversation_id
        current_user: Authenticated user
        db: Async database session
        
    Returns:
        AgentStreamingStartResponse indicating streaming has started
        
    Raises:
        HTTPException: If background task cannot be started
    """
    try:
        # Create service
        service = AgentService(user=current_user, db=db)
        
        # Start background streaming task (non-blocking)
        asyncio.create_task(
            service.handle_streaming(payload)
        )
        
        logger.info(
            f"Started streaming agent task for user {current_user.id} | "
            f"conversation_id={payload.conversation_id}"
        )
        
        return AgentStreamingStartResponse(
            status="streaming_started",
            conversation_id=payload.conversation_id,
            message="Response will be streamed via /api/agent/stream"
        )
        
    except Exception as exc:
        logger.error(f"Error starting streaming agent task: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start streaming response processing.",
        ) from exc


# ============================================================================
# Conversation Management Endpoints (Memory and History)
# ============================================================================

@router.get("/conversations")
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    List all conversations for the authenticated user.
    
    Returns conversations ordered by most recently updated first.
    
    Query Parameters:
        limit: Maximum number of conversations to return (default: 50, max: 100)
        offset: Number of conversations to skip (default: 0)
    
    Returns:
        List of conversations with pagination info
    """
    from app.services.agent.conversation_store import ConversationStore
    
    # Validate limits
    limit = min(limit, 100)
    
    store = ConversationStore(db)
    conversations, total = await store.list_conversations(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    
    return {
        "conversations": [
            {
                "id": str(conv.id),
                "workspace_id": str(conv.workspace_id) if conv.workspace_id else None,
                "title": conv.title or "Untitled Conversation",
                "message_count": conv.message_count,
                "has_summary": bool(conv.summary),
                "updated_at": conv.updated_at.isoformat(),
                "created_at": conv.created_at.isoformat(),
            }
            for conv in conversations
        ],
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "remaining": max(0, total - (offset + limit)),
        },
    }


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Retrieve a specific conversation with its message history and summary.
    
    Args:
        conversation_id: UUID of the conversation
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Conversation details including messages and summary
        
    Raises:
        HTTPException: 404 if conversation not found or not owned by user
    """
    from app.services.agent.conversation_store import ConversationStore
    
    store = ConversationStore(db)
    conv = await store.get_conversation_by_id(conversation_id, current_user.id)
    
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    # Get all messages for this conversation
    from sqlalchemy import select
    from app.models import AgentMessage
    
    stmt = select(AgentMessage).where(
        AgentMessage.conversation_id == conversation_id
    ).order_by(AgentMessage.created_at.asc())
    
    result = await db.execute(stmt)
    messages = result.scalars().all()
    
    return {
        "id": str(conv.id),
        "workspace_id": str(conv.workspace_id) if conv.workspace_id else None,
        "title": conv.title,
        "summary": conv.summary,
        "message_count": conv.message_count,
        "total_tokens": conv.total_token_count,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": [
            {
                "id": str(msg.id),
                "role": msg.role,
                "content": msg.content if msg.role != "tool" else None,
                "tool_name": msg.tool_name if msg.role == "tool" else None,
                "tool_input": msg.tool_input if msg.role == "tool" else None,
                "tool_output": msg.tool_output if msg.role == "tool" else None,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ],
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Delete a conversation and all its messages (hard delete for privacy).
    
    This is a permanent operation that cannot be undone.
    
    Args:
        conversation_id: UUID of the conversation to delete
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Success confirmation
        
    Raises:
        HTTPException: 404 if conversation not found or not owned by user
    """
    from app.services.agent.conversation_store import ConversationStore
    
    store = ConversationStore(db)
    success = await store.delete_conversation(conversation_id, current_user.id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    await db.commit()
    
    logger.info(
        f"✅ Deleted conversation {conversation_id} for user {current_user.id} | "
        f"Hard delete for privacy"
    )
    
    return {
        "status": "deleted",
        "conversation_id": str(conversation_id),
        "message": "Conversation and all associated messages have been permanently deleted.",
    }
