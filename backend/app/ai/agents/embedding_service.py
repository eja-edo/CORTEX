"""
Embedding Service for semantic search

Routes embedding requests to the configured embedding model via OpenAI-compatible API.
Caches results in Redis to avoid redundant API calls.
"""

import hashlib
import json
import logging
from typing import Optional

from openai import AsyncOpenAI
import redis.asyncio as redis
from app.config import Settings

logger = logging.getLogger(__name__)

settings = Settings()

_embedding_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
    return _embedding_client


class EmbeddingService:
    """
    Service for generating and caching text embeddings via OpenAI-compatible API.

    Uses /v1/embeddings endpoint with the configured embedding model.
    Features:
    - Redis caching with SHA256 key derivation
    - Async-first design
    - Graceful degradation on API failures
    """

    MODEL = settings.EMBEDDING_MODEL

    # Redis cache configuration
    EMBEDDING_CACHE_TTL = 86400 * 30  # 30 days
    CACHE_KEY_PREFIX = "embedding:v1:"

    def __init__(self):
        """Initialize embedding service."""
        pass

    @staticmethod
    def _make_cache_key(text: str) -> str:
        """Generate Redis cache key from text using SHA256."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"{EmbeddingService.CACHE_KEY_PREFIX}{text_hash}"

    @staticmethod
    async def _get_redis_client() -> redis.Redis:
        """Get or create Redis async client."""
        return redis.from_url(settings.REDIS_URL, decode_responses=False)

    async def _embed(self, text: str, use_cache: bool = True) -> Optional[list[float]]:
        """
        Core embedding method.
        """
        if not text or not text.strip():
            logger.warning("empty_text_embedding_skipped")
            return None

        cache_key = self._make_cache_key(text)

        if use_cache:
            try:
                redis_client = await self._get_redis_client()
                cached = await redis_client.get(cache_key)
                if cached:
                    logger.debug("embedding_cache_hit", extra={"key": cache_key})
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"embedding_cache_read_error: {e}")

        try:
            logger.debug("generating_embedding", extra={"text_len": len(text)})

            client = _get_client()
            response = await client.embeddings.create(
                model=self.MODEL,
                input=text,
                dimensions=settings.EMBEDDING_DIMENSIONS,
            )

            embedding = response.data[0].embedding

            if use_cache:
                try:
                    redis_client = await self._get_redis_client()
                    await redis_client.setex(
                        cache_key,
                        self.EMBEDDING_CACHE_TTL,
                        json.dumps(embedding),
                    )
                    logger.debug("embedding_cached", extra={"key": cache_key})
                except Exception as e:
                    logger.warning(f"embedding_cache_write_error: {e}")

            return embedding

        except Exception as e:
            logger.error(f"embedding_generation_failed: {e}", exc_info=True)
            return None

    async def embed_text(self, text: str, use_cache: bool = True) -> Optional[list[float]]:
        return await self._embed(text, use_cache=use_cache)

    async def embed_query(self, query: str, use_cache: bool = True) -> Optional[list[float]]:
        return await self._embed(query, use_cache=use_cache)

    async def embed_batch(
        self, texts: list[str], task_type: str = "retrieval_document"
    ) -> list[Optional[list[float]]]:
        """
        Generate embeddings for multiple texts in parallel.

        Args:
            texts: List of texts to embed
            task_type: "retrieval_document" or "retrieval_query"

        Returns:
            List of embeddings (None for failed items)
        """
        results = []
        for text in texts:
            if task_type == "retrieval_query":
                embedding = await self.embed_query(text)
            else:
                embedding = await self.embed_text(text)
            results.append(embedding)
        return results


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the singleton EmbeddingService instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service