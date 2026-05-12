"""Agent chat API endpoint for conversational AI interactions."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_active_user
from app.models import User
from app.schemas import (
    AgentChatRequest, 
    AgentChatResponse,
)
from app.services.agent.agent_service import AgentService
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


@router.post("/stream/chat")
async def stream_chat(
    payload: AgentChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Send a message to the AI agent and stream response as SSE.
    
    Streams events in SSE format:
    - data: {"event": "token", "text": "..."} - Text token from response
    - data: {"event": "done", "conversation_id": "..."} - Stream complete
    - data: {"event": "error", "message": "..."} - Error occurred
    
    Args:
        payload: Chat request with message and optional conversation_id
        current_user: Authenticated user
        db: Async database session
        
    Returns:
        StreamingResponse with SSE formatted events
    """
    async def stream_events():
        try:
            service = AgentService(user=current_user, db=db)
            
            # Process with streaming
            reply_text = ""
            result_conversation_id = None
            
            async for chunk in service.handle_streaming_generator(
                message=payload.message,
                conversation_id=payload.conversation_id,
                workspace_id=payload.workspace_id,
            ):
                if chunk.get("event") == "token" and chunk.get("text"):
                    reply_text += chunk["text"]
                    yield f'data: {json.dumps({"event": "token", "text": chunk["text"]})}\n\n'
                elif chunk.get("event") == "tool_start":
                    yield f'data: {json.dumps({"event": "tool_start", "tool_name": chunk.get("tool_name"), "tool_args": chunk.get("tool_args")})}\n\n'
                elif chunk.get("event") == "tool_result":
                    yield f'data: {json.dumps({"event": "tool_result", "tool_name": chunk.get("tool_name"), "result": chunk.get("result")})}\n\n'
                elif chunk.get("event") == "done":
                    result_conversation_id = chunk.get("conversation_id")
                    yield f'data: {json.dumps({"event": "done", "conversation_id": str(result_conversation_id)})}\n\n'
                elif chunk.get("event") == "error":
                    yield f'data: {json.dumps({"event": "error", "message": chunk.get("message")})}\n\n'
                    
        except Exception as exc:
            logger.error(f"Error in stream chat: {exc}", exc_info=True)
            yield f'data: {json.dumps({"event": "error", "message": str(exc)})}\n\n'
    
    return StreamingResponse(
        stream_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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
