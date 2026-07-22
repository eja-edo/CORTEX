"""Search notes tool with semantic search support."""

import logging
import time
from uuid import UUID
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.agents.tool_context import ToolContext
from app.ai.agents.semantic_search import semantic_search_notes
from app.services.workspace_permission import WorkspacePermission

logger = logging.getLogger(__name__)


class SearchNotesInput(BaseModel):
    """Validation model for search_notes tool."""
    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    limit: int = Field(default=10, ge=1, le=50, description="Max results")


async def search_notes_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Search user's notes using semantic similarity (with keyword fallback).
    
    Security:
    - Always filtered by ctx.user_id (from authenticated session)
    - Workspace filtering optional but user always enforced
    - Returns previews only, not full content
    
    Features:
    - Semantic search using Gemini embeddings (if available)
    - Automatic fallback to keyword search
    - Similarity scores for relevance ranking
    """
    query = args["query"]
    limit = args.get("limit", 10)

    workspace_id = ctx.workspace_id
    if workspace_id is None:
        raise ValueError("workspace_id is required but not available in context")

    # Check workspace membership
    with ctx.get_sync_db() as sync_db:
        WorkspacePermission.require_member(workspace_id, ctx.user_id, sync_db)

    try:
        start_time = time.time()
        
        # Use semantic search (with fallback to keyword)
        async with ctx.async_db() as db:
            search_result = await semantic_search_notes(
                query=query,
                user_id=ctx.user_id,
                db=db,
                workspace_id=workspace_id,
                limit=limit,
            )
        
        # Format response with similarity scores
        formatted_notes = []
        for note_info in search_result.get("notes", []):
            formatted_notes.append({
                "id": note_info["id"],
                "content_preview": note_info.get("content_preview", "")[:200],
                "similarity_score": note_info.get("similarity_score", 0.0),
            })
        
        latency_ms = (time.time() - start_time) * 1000
        
        return {
            "count": search_result["count"],
            "method": search_result.get("method", "unknown"),  # "semantic", "keyword", or "none"
            "notes": formatted_notes,
            "latency_ms": latency_ms,
        }

    except ValueError as exc:
        logger.error(f"search_notes validation error: {exc}")
        raise
    except Exception as exc:
        logger.error(f"search_notes failed: {exc}", exc_info=True)
        raise



SEARCH_NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query - can be keywords or natural language",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of notes to return",
        },
    },
    "required": ["query"],
}

SEARCH_NOTES_DEFINITION = {
    "name": "search_notes",
    "handler": search_notes_handler,
    "input_model": SearchNotesInput,
    "schema": SEARCH_NOTES_SCHEMA,
    "description": "Search notes in the current workspace by keyword. Returns matching notes with content preview.",
}
