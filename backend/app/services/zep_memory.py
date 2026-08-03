"""
Zep integration for long-term semantic memory storage.

Handles:
- User creation in Zep
- Adding semantic memories to user graphs
- Searching semantic memories from user graphs

Dedupe strategy (Issue 2b):
1) In-process LRU keyed on (user_id, normalized_signature) — catches the
   common case of duplicate entries within the same batch / process
   without any DB or Zep round-trip.
2) Before inserting, query Zep with the content as the search query. If a
   result already has very high cross-encoder score (default ≥ 0.95) OR
   matches an existing entry exactly by content, the addition is skipped.
   Threshold is configurable via ZEP_DEDUPE_SCORE env override.
"""

import json
import logging
import os as _os
import re
import threading
from collections import OrderedDict
from uuid import UUID

import httpx
from zep_cloud.client import Zep
from zep_cloud.core import ApiError
from app.config import settings
from app.services.semantic_memory_provider import (
    SemanticMemoryProvider,
    SemanticMemoryResult,
    SemanticMemoryUnavailable,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# In-process dedupe cache: (user_id, normalized_signature) → True
# LRU-bounded to prevent unbounded growth across long-running processes.
# Each unique signature costs a few hundred bytes.
_DEDUPE_CACHE_LIMIT = 4096
_dedupe_cache: "OrderedDict[str, None]" = OrderedDict()
_dedupe_lock = threading.Lock()

# Score threshold above which a Zep search hit is treated as an existing
# duplicate (vs adding a new near-set). Tunable via env var.
ZEP_DEDUPE_SCORE = float(_os.environ.get("ZEP_DEDUPE_SCORE", "0.95"))

# Timeout (seconds) for Zep Cloud HTTP calls.
ZEP_CLIENT_TIMEOUT = float(_os.environ.get("ZEP_CLIENT_TIMEOUT", "10.0"))


def _normalize_content(content: str) -> str:
    """Lowercase + collapse whitespace + strip for dedupe signature."""
    if not content:
        return ""
    return re.sub(r"\s+", " ", content.strip().lower())


def _dedupe_signature(user_id: str, category: str, content: str) -> str:
    return f"{user_id}\x00{category}\x00{_normalize_content(content)}"


def _already_seen(user_id: str, category: str, content: str) -> bool:
    """In-process check: was this exact (user, category, normalized-content) added before?"""
    sig = _dedupe_signature(user_id, category, content)
    with _dedupe_lock:
        if sig in _dedupe_cache:
            _dedupe_cache.move_to_end(sig)
            return True
        return False


def _mark_seen(user_id: str, category: str, content: str) -> None:
    sig = _dedupe_signature(user_id, category, content)
    with _dedupe_lock:
        _dedupe_cache[sig] = None
        if len(_dedupe_cache) > _DEDUPE_CACHE_LIMIT:
            _dedupe_cache.popitem(last=False)


# ---------------------------------------------------------------------------
# ZepMemoryProvider class (single source of truth for Zep API logic)
# ---------------------------------------------------------------------------

class ZepMemoryProvider(SemanticMemoryProvider):

    def __init__(self) -> None:
        self._client: Zep | None = None

    def _get_client(self) -> Zep | None:
        return _get_client(timeout=ZEP_CLIENT_TIMEOUT)

    async def ensure_user(
        self,
        user_id: str,
        first_name: str = "",
        last_name: str = "",
        email: str = "",
    ) -> bool:
        client = self._get_client()
        if not client:
            raise SemanticMemoryUnavailable("ZEP_API_KEY not configured")

        try:
            client.user.add(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                email=email,
            )
            logger.info(f"Zep user created/updated: {user_id}")
            return True
        except (ApiError, httpx.HTTPError) as exc:
            exc_str = str(exc)
            if "already exists" in exc_str.lower():
                logger.debug(f"Zep user already exists: {user_id}")
                return True
            raise SemanticMemoryUnavailable(f"Failed to create Zep user {user_id}") from exc

    async def add_semantic_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        confidence: float,
        expected_lifetime: str,
    ) -> bool:
        client = self._get_client()
        if not client:
            raise SemanticMemoryUnavailable("ZEP_API_KEY not configured")

        # 1) cheap in-process check
        if _already_seen(user_id, category, content):
            logger.debug(
                "Zep dedupe (in-process) skipped: [%s] %s...",
                category, content[:80],
            )
            _mark_seen(user_id, category, content)
            return True

        # 2) Zep-graph similarity check
        if await self._check_zep_duplicate(user_id, content):
            logger.debug(
                "Zep dedupe (similarity) skipped: [%s] %s...",
                category, content[:80],
            )
            _mark_seen(user_id, category, content)
            return True

        try:
            memory_payload = {
                "category": category,
                "content": content,
                "confidence": confidence,
                "expected_lifetime": expected_lifetime,
                "extracted_at": __import__("datetime").datetime.now().isoformat(),
            }

            client.graph.add(
                user_id=user_id,
                type="json",
                data=json.dumps(memory_payload),
            )
            _mark_seen(user_id, category, content)
            logger.debug("Added semantic memory to Zep: [%s] %s...", category, content[:80])
            return True
        except (ApiError, httpx.HTTPError) as exc:
            raise SemanticMemoryUnavailable(
                f"Failed to add semantic memory to Zep: {exc}"
            ) from exc

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
        client = self._get_client()
        if not client:
            raise SemanticMemoryUnavailable("ZEP_API_KEY not configured")

        try:
            params = {
                "query": query,
                "user_id": user_id,
                "limit": min(limit, 50),
                "scope": "edges",
                "reranker": "cross_encoder",
            }
            if min_score is not None:
                params["min_score"] = min_score

            results = client.graph.search(**params)

            memories: list[SemanticMemoryResult] = []
            seen: set[str] = set()
            for edge in (results.edges or []):
                if not edge.fact:
                    continue
                if edge.fact in seen:
                    continue
                seen.add(edge.fact)

                result: SemanticMemoryResult = {
                    "id": edge.fact,
                    "content": "",
                    "category": "",
                    "score": edge.score or 0.0,
                }
                if edge.attributes:
                    attrs = edge.attributes
                    result["category"] = attrs.get("category", "")
                    result["content"] = attrs.get("content", edge.fact)
                else:
                    result["content"] = edge.fact
                memories.append(result)

            for node in (results.nodes or []):
                if node.name in seen or node.summary in seen:
                    continue
                if not node.summary:
                    continue
                seen.add(node.summary)
                memories.append({
                    "id": node.summary,
                    "content": node.summary,
                    "category": "entity",
                    "score": node.score or 0.0,
                })

            memories.sort(key=lambda m: -(m.get("score") or 0))

            logger.info(
                "Zep graph search: query=%r user=%s results=%d",
                query, user_id, len(memories),
            )
            return memories[:limit]

        except SemanticMemoryUnavailable:
            raise
        except (ApiError, httpx.HTTPError) as exc:
            raise SemanticMemoryUnavailable(
                f"Zep graph search failed: {exc}"
            ) from exc

    async def _check_zep_duplicate(self, user_id: str, content: str) -> bool:
        """Search Zep for a duplicate of `content`.

        Calls the module-level search_semantic_memories so that tests patching
        that function are intercepted. Raises SemanticMemoryUnavailable on
        Zep API failure.
        """
        try:
            results = await search_semantic_memories(
                user_id=user_id,
                query=content,
                limit=5,
                min_score=ZEP_DEDUPE_SCORE,
            )
        except SemanticMemoryUnavailable:
            raise
        except (ApiError, httpx.HTTPError) as exc:
            raise SemanticMemoryUnavailable(
                f"Zep dedupe-lookup failed: {exc}"
            ) from exc

        if not results:
            return False
        target_norm = _normalize_content(content)
        for mem in results:
            fact = mem.get("content", "")
            if _normalize_content(fact) == target_norm:
                return True
            score = mem.get("score") or 0.0
            if score >= ZEP_DEDUPE_SCORE:
                return True
        return False


# ---------------------------------------------------------------------------
# Module-level singleton instance
# ---------------------------------------------------------------------------

_zep_provider_instance: ZepMemoryProvider | None = None


def _get_provider() -> ZepMemoryProvider:
    global _zep_provider_instance
    if _zep_provider_instance is None:
        _zep_provider_instance = ZepMemoryProvider()
    return _zep_provider_instance


# ---------------------------------------------------------------------------
# Legacy module-level client accessor (kept for backward compat; not used by shims below)
# ---------------------------------------------------------------------------

_zep_client = None


def _get_client(timeout: float | None = None) -> Zep | None:
    """Return the shared Zep client, constructing it if necessary.

    Args:
        timeout: Request timeout in seconds. If None, uses ZEP_CLIENT_TIMEOUT.
    """
    global _zep_client
    if _zep_client is None:
        if not settings.ZEP_API_KEY:
            logger.warning("ZEP_API_KEY not configured — Zep integration disabled")
            return None
        try:
            _zep_client = Zep(
                api_key=settings.ZEP_API_KEY,
                timeout=timeout if timeout is not None else ZEP_CLIENT_TIMEOUT,
            )
            logger.info("Zep client initialized")
        except Exception as exc:
            logger.error(f"Failed to initialize Zep client: {exc}")
            return None
    return _zep_client


# ---------------------------------------------------------------------------
# Legacy shims — behaviour-identical wrappers for existing callers.
# Each catches SemanticMemoryUnavailable and returns the same sentinel the
# original function returned.
# ---------------------------------------------------------------------------

async def _check_zep_duplicate(user_id: str, content: str) -> bool:
    """Legacy shim. Returns False on Zep failure (original contract)."""
    try:
        return await _get_provider()._check_zep_duplicate(user_id, content)
    except SemanticMemoryUnavailable:
        return False


async def ensure_user(
    user_id: str,
    first_name: str = "",
    last_name: str = "",
    email: str = "",
) -> bool:
    """Ensure a Zep user exists. Returns True on success/already-exists, False on error."""
    try:
        return await _get_provider().ensure_user(user_id, first_name, last_name, email)
    except SemanticMemoryUnavailable:
        return False


async def add_semantic_memory(
    user_id: str,
    category: str,
    content: str,
    confidence: float,
    expected_lifetime: str,
) -> bool:
    """Add a semantic memory candidate to the user's Zep graph.

    Dedupe is performed before insertion (Issue 2b):
        - in-process LRU check keyed on (user_id, category, normalized content)
        - Zep search hit with score >= ZEP_DEDUPE_SCORE OR exact content match

    When dedupe skips the insert, True is still returned (semantically the
    memory IS already stored), and the local cache is updated so subsequent
    calls within this process treat it as present.

    Args:
        user_id: The user ID in Zep.
        category: "project" | "preference" | "constraint" | "environment" | "decision_pattern"
        content: The memory text.
        confidence: 0.0-1.0
        expected_lifetime: "short" | "medium" | "long" | "permanent"

    Returns:
        True if the memory was stored (or already existed).
    """
    try:
        return await _get_provider().add_semantic_memory(
            user_id, category, content, confidence, expected_lifetime,
        )
    except SemanticMemoryUnavailable:
        return False


async def add_semantic_memories_batch(user_id: str, memories: list[dict]) -> int:
    """Add multiple semantic memories. Returns number successfully stored."""
    try:
        return await _get_provider().add_semantic_memories_batch(user_id, memories)
    except SemanticMemoryUnavailable:
        return 0


async def search_semantic_memories(
    user_id: str,
    query: str,
    limit: int = 10,
    min_score: float | None = None,
) -> list[dict]:
    """Search semantic memories in the user's Zep graph.

    Args:
        user_id: The workspace/user ID in Zep.
        query: Natural language search query.
        limit: Max results (default 10, max 50).
        min_score: Minimum relevance score filter (0.0-1.0).

    Returns:
        List of memory dicts with keys: content, category, score, fact, name
    """
    try:
        return [
            {
                "fact": r["content"],
                "name": "",
                "score": r["score"],
                "category": r.get("category", ""),
                "content": r["content"],
            }
            for r in await _get_provider().search_semantic_memories(
                user_id, query, limit, min_score,
            )
        ]
    except SemanticMemoryUnavailable:
        return []
