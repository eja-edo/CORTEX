"""
SemanticMemoryProvider interface.

Abstract base class for semantic memory backends.
Current implementations:
- ZepMemoryService (via zep_memory.py)
- PgVectorMemoryProvider (pgvector fallback)

FallbackSemanticMemoryProvider wraps ZepMemoryProvider as primary
and PgVectorMemoryProvider as fallback when Zep is unavailable.
"""

import logging
from abc import ABC, abstractmethod
from typing import NotRequired, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SemanticMemoryUnavailable(Exception):
    """Raised when the semantic memory backend (e.g. Zep Cloud) is unreachable or errors."""



class SemanticMemoryResult(TypedDict):
    id: str
    content: str
    category: str
    confidence: NotRequired[float]
    score: float
    created_at: NotRequired[str]


class SemanticMemoryProvider(ABC):

    @abstractmethod
    async def ensure_user(self, user_id: str) -> bool:
        ...

    @abstractmethod
    async def add_semantic_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        confidence: float,
        expected_lifetime: str,
    ) -> bool:
        ...

    @abstractmethod
    async def add_semantic_memories_batch(
        self,
        user_id: str,
        memories: list[dict],
    ) -> int:
        ...

    @abstractmethod
    async def search_semantic_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        min_score: float | None = None,
    ) -> list[SemanticMemoryResult]:
        ...


class FallbackSemanticMemoryProvider(SemanticMemoryProvider):

    def __init__(
        self,
        db: AsyncSession,
        primary: SemanticMemoryProvider | None = None,
        fallback: SemanticMemoryProvider | None = None,
    ):
        if primary is None:
            from app.services.zep_memory import ZepMemoryProvider
            primary = ZepMemoryProvider()
        if fallback is None:
            from app.services.pgvector_memory_provider import PgVectorMemoryProvider
            fallback = PgVectorMemoryProvider(db=db)
        self._primary = primary
        self._fallback = fallback

    async def _try_fallback(self, method: str, *args, **kwargs):
        try:
            meth = getattr(self._primary, method)
            return await meth(*args, **kwargs)
        except SemanticMemoryUnavailable:
            logger.warning(
                "Zep %s failed — falling back to PgVector", method,
            )
            fallback_meth = getattr(self._fallback, method)
            return await fallback_meth(*args, **kwargs)

    async def ensure_user(self, user_id: str) -> bool:
        return await self._try_fallback("ensure_user", user_id=user_id)

    async def add_semantic_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        confidence: float,
        expected_lifetime: str,
    ) -> bool:
        return await self._try_fallback(
            "add_semantic_memory",
            user_id=user_id,
            category=category,
            content=content,
            confidence=confidence,
            expected_lifetime=expected_lifetime,
        )

    async def add_semantic_memories_batch(
        self,
        user_id: str,
        memories: list[dict],
    ) -> int:
        return await self._try_fallback(
            "add_semantic_memories_batch",
            user_id=user_id,
            memories=memories,
        )

    async def search_semantic_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        min_score: float | None = None,
    ) -> list[SemanticMemoryResult]:
        return await self._try_fallback(
            "search_semantic_memories",
            user_id=user_id,
            query=query,
            limit=limit,
            min_score=min_score,
        )


def get_semantic_memory_provider(db: AsyncSession) -> SemanticMemoryProvider:
    return FallbackSemanticMemoryProvider(db=db)
