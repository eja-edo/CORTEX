import logging
from typing import List, Dict, Any, Optional

from sqlalchemy import text

from app.memory.models.schemas import RetrievalResult
from app.memory.scorer import compute_retrieval_score
from app.memory.embedding import MemoryEmbeddingService

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """
    Queries the relevant memory layers based on intent.
    Uses vector search when embeddings available, falls back to ILIKE.
    """

    def __init__(self):
        self._mem_embedding = MemoryEmbeddingService()

    async def retrieve(self, query: str, user_id: str, db, use_embedding=True) -> RetrievalResult:
        result = RetrievalResult(query_type=self._classify_query(query))

        result.working_memory = []
        result.conversation_summaries = await self._get_conversation_summaries(user_id, db)

        if use_embedding:
            result.semantic_memories = await self._search_semantic_with_fallback(query, user_id, db)
        else:
            result.semantic_memories = await self._get_semantic_memories_ilike(query, user_id, db)

        result.preferences = await self._get_preferences(user_id, db)

        if use_embedding:
            result.episodic_memories = await self._search_episodic_with_fallback(query, user_id, db)
        else:
            result.episodic_memories = await self._get_episodic_memories_recent(user_id, db)

        if use_embedding:
            result.knowledge_chunks = await self._search_knowledge_with_fallback(query, user_id, db)
        else:
            result.knowledge_chunks = await self._get_knowledge_chunks_ilike(query, user_id, db)

        return result

    def _classify_query(self, query: str) -> str:
        q = query.lower()
        if any(kw in q for kw in ["project", "dự án", "what am i building", "repo", "codebase", "repository", "what are you working on"]):
            return "project_context"
        if any(kw in q for kw in ["my", "my preferred", "my favorite", "thích", "prefer", "tôi hay dùng", "what do i use", "what's my"]):
            return "preference"
        if any(kw in q for kw in ["who am i", "what do i do", "what is my role", "tôi là", "nghề của tôi", "my job", "my role"]):
            return "identity"
        if any(kw in q for kw in ["remember", "what about", "what did i say", "nhớ", "gì về", "lúc trước"]):
            return "semantic_fact"
        if any(kw in q for kw in ["recent", "vừa rồi", "gần đây", "just happened", "what happened", "last time"]):
            return "recent_episodic"
        return "general"

    async def _get_conversation_summaries(self, user_id: str, db) -> List[str]:
        result = await db.execute(text("""
            SELECT summary_text
            FROM conversation_summaries
            WHERE user_id = :uid AND summary_version = (
                SELECT MAX(summary_version)
                FROM conversation_summaries c2
                WHERE c2.conversation_id = conversation_summaries.conversation_id
            )
            ORDER BY created_at DESC
            LIMIT 5
        """), {"uid": user_id})
        return [r[0] for r in result.fetchall()]

    async def _search_semantic_with_fallback(self, query: str, user_id: str,
                                              db) -> List[Dict[str, Any]]:
        try:
            vector_results = await self._mem_embedding.search_semantic(query, user_id, db, limit=15)
            if vector_results:
                memory_ids = [(r["memory_type"], r["memory_id"]) for r in vector_results]
                rows = []
                for mtype, mid in memory_ids:
                    r = await db.execute(text("""
                        SELECT * FROM semantic_memories
                        WHERE id = :mid AND is_active = TRUE
                        AND (expires_at IS NULL OR expires_at > NOW())
                    """), {"mid": mid})
                    row = r.fetchone()
                    if row:
                        rows.append(dict(row._mapping))
                return rows
        except Exception as e:
            logger.warning("Vector semantic search failed, falling back to ILIKE: %s", e)

        return await self._get_semantic_memories_ilike(query, user_id, db)

    async def _get_semantic_memories_ilike(self, query: str, user_id: str,
                                            db) -> List[Dict[str, Any]]:
        result = await db.execute(text("""
            SELECT * FROM semantic_memories
            WHERE user_id = :uid AND is_active = TRUE
              AND (expires_at IS NULL OR expires_at > NOW())
              AND (value ILIKE :q OR subject ILIKE :q)
            ORDER BY importance_score DESC, confidence_score DESC
            LIMIT 15
        """), {"uid": user_id, "q": f"%{query[:100]}%"})
        return [dict(r._mapping) for r in result.fetchall()]

    async def _get_preferences(self, user_id: str, db) -> Dict[str, Any]:
        result = await db.execute(text("""
            SELECT category, key, value, confidence_score
            FROM preference_memories
            WHERE user_id = :uid AND is_active = TRUE
            ORDER BY confidence_score DESC
            LIMIT 30
        """), {"uid": user_id})
        prefs: Dict[str, Any] = {}
        for r in result.fetchall():
            cat = r[0]
            if cat not in prefs:
                prefs[cat] = {}
            prefs[cat][r[1]] = {"value": r[2], "confidence": r[3]}
        return prefs

    async def _search_episodic_with_fallback(self, query: str, user_id: str,
                                              db) -> List[Dict[str, Any]]:
        try:
            vector_results = await self._mem_embedding.search_semantic(query, user_id, db, limit=10)
            if vector_results:
                memory_ids = [(r["memory_type"], r["memory_id"]) for r in vector_results
                              if r["memory_type"] == "episodic"]
                rows = []
                for _, mid in memory_ids:
                    r = await db.execute(text("""
                        SELECT * FROM episodic_memories
                        WHERE id = :mid AND is_active = TRUE
                    """), {"mid": mid})
                    row = r.fetchone()
                    if row:
                        rows.append(dict(row._mapping))
                return rows
        except Exception as e:
            logger.warning("Vector episodic search failed, falling back: %s", e)

        return await self._get_episodic_memories_recent(user_id, db)

    async def _get_episodic_memories_recent(self, user_id: str, db) -> List[Dict[str, Any]]:
        result = await db.execute(text("""
            SELECT * FROM episodic_memories
            WHERE user_id = :uid AND is_active = TRUE
            ORDER BY importance_score DESC, last_seen_at DESC
            LIMIT 10
        """), {"uid": user_id})
        return [dict(r._mapping) for r in result.fetchall()]

    async def _search_knowledge_with_fallback(self, query: str, user_id: str,
                                               db) -> List[Dict[str, Any]]:
        try:
            vector_results = await self._mem_embedding.search_knowledge(query, user_id, db, limit=10)
            if vector_results:
                return vector_results
        except Exception as e:
            logger.warning("Vector knowledge search failed, falling back: %s", e)

        return await self._get_knowledge_chunks_ilike(query, user_id, db)

    async def _get_knowledge_chunks_ilike(self, query: str, user_id: str,
                                           db) -> List[Dict[str, Any]]:
        result = await db.execute(text("""
            SELECT * FROM knowledge_chunks
            WHERE user_id = :uid AND is_active = TRUE
              AND chunk_text ILIKE :q
            ORDER BY chunk_index ASC
            LIMIT 10
        """), {"uid": user_id, "q": f"%{query[:100]}%"})
        return [dict(r._mapping) for r in result.fetchall()]
