"""
Embedding Service for semantic search

Uses Gemini's text-embedding-004 model to generate 768-dimensional embeddings.
Caches results in Redis to avoid redundant API calls.
"""

import hashlib
import json
import logging
from typing import Optional

from google import genai
import redis.asyncio as redis
from app.config import Settings

logger = logging.getLogger(__name__)

settings = Settings()

# Create client
client = genai.Client(api_key=settings.GEMINI_API_KEY)
EMBEDDING_MODEL = "text-embedding-004"


class EmbeddingService:
    """
    Service for generating and caching text embeddings using Gemini.
    
    Features:
    - Token-efficient with proper task types (retrieval_document vs retrieval_query)
    - Redis caching with SHA256 key derivation
    - Async-first design
    - Graceful degradation on API failures
    """
    
    # Gemini embedding model (768-dimensional, free tier)
    MODEL = "models/text-embedding-004"
    DIMENSIONS = 768
    
    # Redis cache configuration
    EMBEDDING_CACHE_TTL = 86400 * 30  # 30 days
    CACHE_KEY_PREFIX = "embedding:v1:"
    
    def __init__(self):
        """Initialize embedding service with Gemini API."""
        # Gemini client configured at module level in agent_service
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
    
    async def embed_text(self, text: str, use_cache: bool = True) -> Optional[list[float]]:
        """
        Generate embedding for a document/content.
        
        Args:
            text: Text to embed
            use_cache: Whether to use Redis cache
        
        Returns:
            768-dimensional embedding vector, or None if failed
        """
        if not text or not text.strip():
            logger.warning("empty_text_embedding_skipped")
            return None
        
        cache_key = self._make_cache_key(text)
        
        # Try cache first
        if use_cache:
            try:
                client = await self._get_redis_client()
                cached = await client.get(cache_key)
                if cached:
                    logger.debug(f"embedding_cache_hit", extra={"key": cache_key})
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"embedding_cache_read_error: {e}")
                # Continue with API call on cache miss
        
        # Generate embedding via Gemini API
        try:
            logger.debug(f"generating_embedding", extra={"text_len": len(text)})
            
            result = await genai.embed_content_async(
                model=self.MODEL,
                content=text,
                task_type="retrieval_document",
            )
            
            embedding = result["embedding"]
            
            # Cache for future use
            if use_cache:
                try:
                    client = await self._get_redis_client()
                    await client.setex(
                        cache_key,
                        self.EMBEDDING_CACHE_TTL,
                        json.dumps(embedding),
                    )
                    logger.debug(f"embedding_cached", extra={"key": cache_key})
                except Exception as e:
                    logger.warning(f"embedding_cache_write_error: {e}")
            
            return embedding
        
        except Exception as e:
            logger.error(f"embedding_generation_failed: {e}", exc_info=True)
            return None
    
    async def embed_query(self, query: str, use_cache: bool = True) -> Optional[list[float]]:
        """
        Generate embedding for a search query.
        
        Uses special task_type for query embeddings to align with document embeddings.
        
        Args:
            query: Search query text
            use_cache: Whether to use Redis cache
        
        Returns:
            768-dimensional embedding vector, or None if failed
        """
        if not query or not query.strip():
            logger.warning("empty_query_embedding_skipped")
            return None
        
        cache_key = self._make_cache_key(query)
        
        # Try cache first
        if use_cache:
            try:
                client = await self._get_redis_client()
                cached = await client.get(cache_key)
                if cached:
                    logger.debug(f"query_embedding_cache_hit", extra={"key": cache_key})
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"embedding_cache_read_error: {e}")
        
        # Generate embedding via Gemini API
        try:
            logger.debug(f"generating_query_embedding", extra={"query_len": len(query)})
            
            result = await genai.embed_content_async(
                model=self.MODEL,
                content=query,
                task_type="retrieval_query",  # Different task type for queries
            )
            
            embedding = result["embedding"]
            
            # Cache for future use
            if use_cache:
                try:
                    client = await self._get_redis_client()
                    await client.setex(
                        cache_key,
                        self.EMBEDDING_CACHE_TTL,
                        json.dumps(embedding),
                    )
                    logger.debug(f"query_embedding_cached", extra={"key": cache_key})
                except Exception as e:
                    logger.warning(f"embedding_cache_write_error: {e}")
            
            return embedding
        
        except Exception as e:
            logger.error(f"query_embedding_failed: {e}", exc_info=True)
            return None
    
    async def embed_batch(self, texts: list[str], task_type: str = "retrieval_document") -> list[Optional[list[float]]]:
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
