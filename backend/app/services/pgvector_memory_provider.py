"""
PgVectorMemoryProvider — pgvector fallback for SemanticMemoryProvider.

Stores semantic memories in a local `semantic_memories` table using
pgvector for similarity search. Mirrors the ZepMemoryService interface
so it can be swapped in when Zep Cloud is unavailable.

TRANSACTION OWNERSHIP: The caller owns the transaction. This provider
never calls commit() or rollback() on the injected AsyncSession —
the caller decides when to commit. On error the provider logs and
returns False; the caller may rollback or continue.

Dedup strategy (mirrors zep_memory.py):
1) In-process LRU keyed on (user_id, normalized_signature) — catches
   duplicates within the same batch / process without a DB round-trip.
2) Before inserting, query pgvector with the content embedding. If a
   result already has cosine similarity >= PGVECTOR_DEDUPE_SCORE, the
   addition is skipped.
"""

import logging
import os as _os
import re
import threading
from collections import OrderedDict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.embedding_service import EmbeddingService, get_embedding_service
from app.services.semantic_memory_provider import (
    SemanticMemoryProvider,
    SemanticMemoryResult,
)

logger = logging.getLogger(__name__)

# In-process dedupe cache — same strategy as zep_memory.py
_DEDUPE_CACHE_LIMIT = 4096
_dedupe_cache: OrderedDict[str, None] = OrderedDict()
_dedupe_lock = threading.Lock()

# Cosine similarity threshold for pgvector dedup.
# NOTE: This is NOT directly comparable to ZEP_DEDUPE_SCORE (0.95).
# Zep uses cross-encoder reranking which is much more semantically precise.
# Cosine similarity is looser — tune empirically if needed.
PGVECTOR_DEDUPE_SCORE = float(_os.environ.get("PGVECTOR_DEDUPE_SCORE", "0.90"))


def _normalize_content(content: str) -> str:
    if not content:
        return ""
    return re.sub(r"\s+", " ", content.strip().lower())


def _dedupe_signature(user_id: str, content: str) -> str:
    return f"{user_id}\x00{_normalize_content(content)}"


def _already_seen(user_id: str, content: str) -> bool:
    sig = _dedupe_signature(user_id, content)
    with _dedupe_lock:
        return sig in _dedupe_cache


def _mark_seen(user_id: str, content: str) -> None:
    sig = _dedupe_signature(user_id, content)
    with _dedupe_lock:
        _dedupe_cache[sig] = None
        while len(_dedupe_cache) > _DEDUPE_CACHE_LIMIT:
            _dedupe_cache.popitem(last=False)


def _reset_dedupe_cache() -> None:
    with _dedupe_lock:
        _dedupe_cache.clear()


def _serialize_embedding(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


class PgVectorMemoryProvider(SemanticMemoryProvider):

    def __init__(
        self,
        db: AsyncSession,
        embedding_service: EmbeddingService | None = None,
    ):
        self._db = db
        self._embedding_service = embedding_service or get_embedding_service()

    async def ensure_user(self, user_id: str) -> bool:
        return True

    async def add_semantic_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        confidence: float,
        expected_lifetime: str,
    ) -> bool:
        if not content:
            return False

        if _already_seen(user_id, content):
            logger.debug(
                "PgVector dedupe (in-process) skipped: [%s] %s...",
                category, content[:80],
            )
            return True

        embedding = await self._embedding_service.embed_text(content)
        if embedding is None:
            logger.warning(
                "PgVector skip memory (no embedding): [%s] %s...",
                category, content[:80],
            )
            return False

        duplicate = await self._check_pgvector_duplicate(user_id, content, embedding)
        if duplicate:
            logger.debug(
                "PgVector dedupe (similarity) skipped: [%s] %s...",
                category, content[:80],
            )
            _mark_seen(user_id, content)
            return True

        try:
            embedding_str = _serialize_embedding(embedding)
            stmt = text("""
                INSERT INTO semantic_memories
                    (user_id, category, content, embedding, confidence, expected_lifetime)
                VALUES
                    (:user_id, :category, :content, CAST(:embedding AS vector), :confidence, :expected_lifetime)
            """)
            await self._db.execute(stmt, {
                "user_id": user_id,
                "category": category,
                "content": content,
                "embedding": embedding_str,
                "confidence": confidence,
                "expected_lifetime": expected_lifetime,
            })
            _mark_seen(user_id, content)
            logger.debug(
                "PgVector added memory: [%s] %s...",
                category, content[:80],
            )
            return True
        except Exception as exc:
            logger.error("PgVector add_semantic_memory failed: %s", exc)
            return False

    async def add_semantic_memories_batch(
        self,
        user_id: str,
        memories: list[dict],
    ) -> int:
        count = 0
        for mem in memories:
            ok = await self.add_semantic_memory(
                user_id=user_id,
                category=mem.get("category", "unknown"),
                content=mem.get("content", ""),
                confidence=mem.get("confidence", 0.0),
                expected_lifetime=mem.get("expected_lifetime", "medium"),
            )
            if ok:
                count += 1
        return count

    async def search_semantic_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        min_score: float | None = None,
    ) -> list[SemanticMemoryResult]:
        if not query:
            return []

        query_embedding = await self._embedding_service.embed_query(query)
        if query_embedding is None:
            logger.warning("PgVector search: no query embedding available")
            return []

        limit = min(limit, 50)

        try:
            embedding_str = _serialize_embedding(query_embedding)
            score_filter = ""
            params: dict[str, Any] = {
                "user_id": user_id,
                "query_embedding": embedding_str,
                "limit": limit,
            }
            if min_score is not None:
                score_filter = " AND (1 - (m.embedding <-> CAST(:query_embedding AS vector)) / 2) >= :min_score"
                params["min_score"] = min_score

            stmt = text(f"""
                SELECT
                    m.id::text,
                    m.content,
                    m.category,
                    m.confidence,
                    (1 - (m.embedding <-> CAST(:query_embedding AS vector)) / 2) as score,
                    m.created_at::text as created_at
                FROM semantic_memories m
                WHERE
                    m.user_id = :user_id
                    AND m.embedding IS NOT NULL
                    {score_filter}
                ORDER BY score DESC
                LIMIT :limit
            """)
            result = await self._db.execute(stmt, params)
            rows = result.fetchall()

            return [
                SemanticMemoryResult(
                    id=row[0],
                    content=row[1],
                    category=row[2],
                    confidence=row[3],
                    score=float(row[4]),
                    created_at=row[5],
                )
                for row in rows
            ]
        except Exception as exc:
            logger.error("PgVector search_semantic_memories failed: %s", exc)
            return []

    async def _check_pgvector_duplicate(
        self,
        user_id: str,
        content: str,
        embedding: list[float],
    ) -> bool:
        try:
            embedding_str = _serialize_embedding(embedding)
            stmt = text("""
                SELECT (1 - (m.embedding <-> CAST(:embedding AS vector)) / 2) as sim
                FROM semantic_memories m
                WHERE
                    m.user_id = :user_id
                    AND m.embedding IS NOT NULL
                ORDER BY sim DESC
                LIMIT 1
            """)
            result = await self._db.execute(stmt, {
                "user_id": user_id,
                "embedding": embedding_str,
            })
            row = result.fetchone()
            if row and row[0] is not None and float(row[0]) >= PGVECTOR_DEDUPE_SCORE:
                return True
            return False
        except Exception as exc:
            logger.warning("PgVector dedup check failed: %s", exc)
            return False
