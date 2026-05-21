"""Search notes tool with semantic search support."""

import logging
import time
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.tool_context import ToolContext
from app.services.agent.semantic_search import semantic_search_notes

logger = logging.getLogger(__name__)


class SearchNotesInput(BaseModel):
    """Validation model for search_notes tool."""
    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    workspace_id: Optional[str] = Field(None, description="Optional workspace ID to scope search")
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
    workspace_id_str = args.get("workspace_id")
    
    workspace_id = None
    if workspace_id_str:
        try:
            workspace_id = UUID(workspace_id_str)
        except ValueError as exc:
            raise ValueError(f"Invalid workspace_id format: {exc}")

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
        "workspace_id": {
            "type": "string",
            "description": "Optional UUID of workspace to scope search to",
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
    "description": "Search user's notes by keyword. Returns matching notes with content preview.",
}
