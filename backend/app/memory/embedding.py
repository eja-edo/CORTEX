import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import text

from app.services.agent.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


class MemoryEmbeddingService:
    """
    Generates and stores embeddings for memory layers.
    Uses the existing EmbeddingService (Gemini text-embedding-004) for API calls.
    """

    def __init__(self):
        self._embedder = get_embedding_service()

    async def embed_and_store_knowledge(self, chunk_id: str, source: str, db):
        embedding = await self._embedder.embed_text(source)
        if embedding is None:
            return False

        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        await db.execute(
            text("""
                UPDATE knowledge_chunks
                SET embedding = :emb::vector, updated_at = NOW()
                WHERE id = :cid
            """),
            {"emb": embedding_str, "cid": chunk_id},
        )
        logger.info("Stored embedding for knowledge chunk %s", chunk_id)
        return True

    async def embed_and_store_memory(self, memory_type: str, memory_id: str,
                                      source_text: str, user_id: str, db):
        embedding = await self._embedder.embed_text(source_text)
        if embedding is None:
            return False

        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        await db.execute(
            text("""
                INSERT INTO memory_embeddings
                    (user_id, memory_type, memory_id, embedding, source_text)
                VALUES
                    (:uid, :mtype, :mid, :emb::vector, :text)
                ON CONFLICT (memory_type, memory_id)
                DO UPDATE SET
                    embedding = :emb2::vector,
                    source_text = :text2,
                    updated_at = NOW()
            """),
            {
                "uid": user_id,
                "mtype": memory_type,
                "mid": memory_id,
                "emb": embedding_str,
                "text": source_text,
                "emb2": embedding_str,
                "text2": source_text,
            },
        )
        logger.info("Stored embedding for %s memory %s", memory_type, memory_id)
        return True

    async def embed_batch_knowledge(self, chunks: List[dict], db):
        texts = [c["chunk_text"] for c in chunks]
        embeddings = await self._embedder.embed_batch(texts)

        for chunk, embedding in zip(chunks, embeddings):
            if embedding is None:
                continue
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            await db.execute(
                text("""
                    UPDATE knowledge_chunks
                    SET embedding = :emb::vector, updated_at = NOW()
                    WHERE id = :cid
                """),
                {"emb": embedding_str, "cid": chunk["id"]},
            )

        success_count = sum(1 for e in embeddings if e is not None)
        logger.info("Batch embedded %s/%s knowledge chunks", success_count, len(chunks))

    async def search_semantic(
        self, query: str, user_id: str, db, limit: int = 10
    ) -> List[dict]:
        query_emb = await self._embedder.embed_query(query)
        if query_emb is None:
            return []

        embedding_str = "[" + ",".join(str(x) for x in query_emb) + "]"
        result = await db.execute(
            text("""
                SELECT
                    me.id,
                    me.memory_type,
                    me.memory_id,
                    me.source_text,
                    (me.embedding <-> :qemb::vector) as distance,
                    (1 - (me.embedding <-> :qemb::vector) / 2) as similarity_score
                FROM memory_embeddings me
                WHERE me.user_id = :uid
                ORDER BY distance ASC
                LIMIT :lim
            """),
            {"qemb": embedding_str, "uid": user_id, "lim": limit},
        )
        rows = await result.fetchall()
        return [
            {
                "id": str(r[0]),
                "memory_type": r[1],
                "memory_id": str(r[2]),
                "text": r[3],
                "similarity_score": float(r[5]),
            }
            for r in rows
        ]

    async def search_knowledge(
        self, query: str, user_id: str, db, limit: int = 10
    ) -> List[dict]:
        query_emb = await self._embedder.embed_query(query)
        if query_emb is None:
            return []

        embedding_str = "[" + ",".join(str(x) for x in query_emb) + "]"
        result = await db.execute(
            text("""
                SELECT
                    kc.id,
                    kc.chunk_text,
                    kc.source_type,
                    kc.source_id,
                    (kc.embedding <-> :qemb::vector) as distance,
                    (1 - (kc.embedding <-> :qemb::vector) / 2) as similarity_score
                FROM knowledge_chunks kc
                WHERE kc.user_id = :uid
                  AND kc.embedding IS NOT NULL
                  AND kc.is_active = TRUE
                ORDER BY distance ASC
                LIMIT :lim
            """),
            {"qemb": embedding_str, "uid": user_id, "lim": limit},
        )
        rows = await result.fetchall()
        return [
            {
                "id": str(r[0]),
                "text": r[1],
                "source_type": r[2],
                "source_id": str(r[3]) if r[3] else None,
                "similarity_score": float(r[5]),
            }
            for r in rows
        ]
