"""Search knowledge tool with semantic search support."""

import logging
import time
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.services.agent.tool_context import ToolContext
from app.services.agent.semantic_search import semantic_search_knowledge

logger = logging.getLogger(__name__)


class SearchKnowledgeInput(BaseModel):
    """Validation model for search_knowledge tool."""
    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    asset_id: Optional[str] = Field(None, description="Optional asset UUID to scope search")
    unit_type: Optional[str] = Field(
        None,
        pattern="^(fact|error|code_pattern|command|explanation|decision)?$",
        description="Optional knowledge unit type filter"
    )
    limit: int = Field(default=10, ge=1, le=50, description="Max results")


async def search_knowledge_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Search knowledge units extracted from assets using semantic similarity.
    
    Features:
    - Semantic vector search via MongoDB Atlas Vector Search (Phase 4 Part 2)
    - Automatic fallback to keyword search
    - Unit type filtering
    
    Security:
    - Always filtered by ctx.user_id (from authenticated session)
    - Asset permissions enforced via existing API
    """
    query = args["query"]
    asset_id_str = args.get("asset_id")
    unit_type = args.get("unit_type")
    limit = args.get("limit", 10)
    
    asset_id = None
    if asset_id_str:
        try:
            asset_id = UUID(asset_id_str)
        except ValueError as exc:
            raise ValueError(f"Invalid asset_id format: {exc}")

    try:
        start_time = time.time()
        
        # Use semantic search
        async with ctx.async_db() as db:
            search_result = await semantic_search_knowledge(
                query=query,
                user_id=ctx.user_id,
                db=db,
                asset_id=asset_id,
                limit=limit,
            )
        
        latency_ms = (time.time() - start_time) * 1000
        
        return {
            "count": search_result.get("count", 0),
            "method": search_result.get("method", "not_implemented"),
            "units": search_result.get("units", []),
            "latency_ms": latency_ms,
        }

    except ValueError as exc:
        logger.error(f"search_knowledge validation error: {exc}")
        raise
    except Exception as exc:
        logger.error(f"search_knowledge failed: {exc}", exc_info=True)
        raise



SEARCH_KNOWLEDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query for knowledge units",
        },
        "asset_id": {
            "type": "string",
            "description": "Optional asset UUID to limit search",
        },
        "unit_type": {
            "type": "string",
            "enum": ["fact", "error", "code_pattern", "command", "explanation", "decision"],
            "description": "Optional knowledge unit type",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum results",
        },
    },
    "required": ["query"],
}

SEARCH_KNOWLEDGE_DEFINITION = {
    "name": "search_knowledge",
    "handler": search_knowledge_handler,
    "input_model": SearchKnowledgeInput,
    "schema": SEARCH_KNOWLEDGE_SCHEMA,
    "description": "Search knowledge units from recorded assets. Returns facts, errors, code patterns, etc.",
}
