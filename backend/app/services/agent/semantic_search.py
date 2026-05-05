"""
Semantic search functionality for notes and knowledge units.

Uses pgvector for PostgreSQL-based vector similarity search.
Falls back to keyword search if embeddings are unavailable.
"""

import logging
import time
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Note
from app.services.agent.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


async def semantic_search_notes(
    query: str,
    user_id: UUID,
    db: AsyncSession,
    workspace_id: Optional[UUID] = None,
    limit: int = 10,
) -> dict:
    """
    Semantic search across user's notes using vector embeddings.
    
    Uses pgvector cosine similarity to find semantically relevant notes.
    Falls back to full-text keyword search if embeddings unavailable.
    
    Args:
        query: Search query string
        user_id: User ID to scope search
        db: AsyncSession for database access
        workspace_id: Optional workspace to scope search
        limit: Maximum results to return (capped at 20)
    
    Returns:
        {
            "count": int,
            "method": "semantic" | "keyword" | "none",
            "query_embedding_available": bool,
            "notes": [
                {"id", "content_preview", "similarity_score"}
            ]
        }
    """
    limit = min(limit, 20)  # Cap to prevent full-table scans
    start_time = time.time()
    
    # Get query embedding
    embedding_service = get_embedding_service()
    query_embedding = await embedding_service.embed_query(query)
    
    if query_embedding is None:
        logger.warning("semantic_search_notes_no_query_embedding")
        # Fallback to keyword search
        return await _keyword_search_notes(query, user_id, db, workspace_id, limit)
    
    # Build semantic search query using pgvector
    try:
        # Raw SQL for pgvector cosine similarity search
        # Note: embedding column stores JSON array, convert to proper vector type for search
        sql = """
            SELECT 
                n.id,
                n.content,
                (n.embedding::vector <-> :query_embedding::vector) as distance,
                (1 - (n.embedding::vector <-> :query_embedding::vector) / 2) as similarity_score
            FROM notes n
            WHERE 
                n.user_id = :user_id 
                AND n.is_deleted = FALSE
                AND n.embedding IS NOT NULL
        """
        
        if workspace_id:
            sql += " AND n.workspace_id = :workspace_id"
        
        sql += """
            ORDER BY distance ASC
            LIMIT :limit
        """
        
        # Convert embedding list to PostgreSQL vector format
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        
        params = {
            "query_embedding": embedding_str,
            "user_id": str(user_id),
            "limit": limit,
        }
        
        if workspace_id:
            params["workspace_id"] = str(workspace_id)
        
        result = await db.execute(text(sql), params)
        rows = result.fetchall()
        
        notes = []
        for row in rows:
            note_id, content, distance, similarity_score = row
            notes.append({
                "id": str(note_id),
                "content_preview": content[:200] if content else "",
                "similarity_score": float(similarity_score),
            })
        
        latency_ms = (time.time() - start_time) * 1000
        logger.info(
            "semantic_search_notes_success",
            extra={
                "results_count": len(notes),
                "latency_ms": latency_ms,
                "workspace_id": workspace_id,
            }
        )
        
        return {
            "count": len(notes),
            "method": "semantic",
            "query_embedding_available": True,
            "notes": notes,
        }
    
    except Exception as e:
        logger.warning(
            f"semantic_search_failed: {e}",
            extra={"user_id": str(user_id)},
            exc_info=True,
        )
        # Fallback to keyword search
        return await _keyword_search_notes(query, user_id, db, workspace_id, limit)


async def _keyword_search_notes(
    query: str,
    user_id: UUID,
    db: AsyncSession,
    workspace_id: Optional[UUID] = None,
    limit: int = 10,
) -> dict:
    """
    Fallback keyword search for notes.
    
    Uses PostgreSQL substring matching for simple keyword search.
    """
    try:
        from sqlalchemy import select
        
        stmt = (
            select(Note.id, Note.content)
            .where(
                Note.user_id == user_id,
                Note.is_deleted == False,
                Note.content.contains(query),  # Simple substring match
            )
            .limit(limit)
        )
        
        if workspace_id:
            stmt = stmt.where(Note.workspace_id == workspace_id)
        
        result = await db.execute(stmt)
        rows = result.fetchall()
        
        notes = []
        for row in rows:
            note_id, content = row
            notes.append({
                "id": str(note_id),
                "content_preview": content[:200] if content else "",
                "similarity_score": 0.5,  # Placeholder for keyword match
            })
        
        logger.info(
            "keyword_search_notes_fallback",
            extra={
                "results_count": len(notes),
                "workspace_id": workspace_id,
            }
        )
        
        return {
            "count": len(notes),
            "method": "keyword",
            "query_embedding_available": False,
            "notes": notes,
        }
    
    except Exception as e:
        logger.error(f"keyword_search_failed: {e}", exc_info=True)
        return {
            "count": 0,
            "method": "none",
            "query_embedding_available": False,
            "notes": [],
        }


async def semantic_search_knowledge(
    query: str,
    user_id: UUID,
    db: AsyncSession,
    asset_id: Optional[UUID] = None,
    limit: int = 10,
) -> dict:
    """
    Semantic search for knowledge units (MongoDB-backed).
    
    Phase 4 implementation note: This is a placeholder.
    Full implementation requires:
    - MongoDB Atlas Vector Search (recommended) OR
    - Chroma/FAISS sidecar for embedding similarity
    
    For now, returns placeholder indicating not yet implemented.
    Will be enhanced in Phase 4 Part 2.
    
    Args:
        query: Search query string
        user_id: User ID to scope search
        db: Database session (for permission checks)
        asset_id: Optional asset to scope search
        limit: Maximum results
    
    Returns:
        Placeholder response until full implementation
    """
    logger.info(
        "semantic_search_knowledge_placeholder",
        extra={
            "query": query[:100],
            "asset_id": asset_id,
        }
    )
    
    # TODO: Phase 4 Part 2 - MongoDB Atlas Vector Search or Chroma integration
    return {
        "count": 0,
        "method": "not_implemented",
        "units": [],
        "message": "Knowledge unit semantic search coming in Phase 4 Part 2",
    }
