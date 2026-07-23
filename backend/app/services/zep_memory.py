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
import re
import threading
from collections import OrderedDict
from uuid import UUID
from zep_cloud.client import Zep
from app.config import settings
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
import os as _os
ZEP_DEDUPE_SCORE = float(_os.environ.get("ZEP_DEDUPE_SCORE", "0.95"))


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


async def _check_zep_duplicate(user_id: str, content: str) -> bool:
    """Best-effort Zep search for a duplicate of `content` already in the graph.

    Returns True when a search result has a cross-encoder score at or above
    `ZEP_DEDUPE_SCORE`, or when an exact normalized-content match is found.
    Returns False on API failure (graceful degradation — caller will still
    attempt the add, accepting that duplicate writes remain possible if
    Zep search is temporarily unavailable).
    """
    try:
        results = await search_semantic_memories(
            user_id=user_id,
            query=content,
            limit=5,
            min_score=ZEP_DEDUPE_SCORE,
        )
    except Exception as exc:
        logger.warning(f"Zep dedupe-lookup failed (proceeding with add): {exc}")
        return False
    if not results:
        return False
    target_norm = _normalize_content(content)
    for mem in results:
        fact = mem.get("fact") or mem.get("content") or ""
        if _normalize_content(fact) == target_norm:
            return True
        score = mem.get("score") or 0.0
        if score >= ZEP_DEDUPE_SCORE:
            return True
    return False

_zep_client = None


def _get_client():
    global _zep_client
    if _zep_client is None:
        if not settings.ZEP_API_KEY:
            logger.warning("ZEP_API_KEY not configured — Zep integration disabled")
            return None
        try:
            _zep_client = Zep(api_key=settings.ZEP_API_KEY)
            logger.info("Zep client initialized")
        except Exception as exc:
            logger.error(f"Failed to initialize Zep client: {exc}")
            return None
    return _zep_client


async def ensure_user(user_id: str, first_name: str = "", last_name: str = "", email: str = "") -> bool:
    """Create or ensure a Zep user exists. Returns True on success."""
    client = _get_client()
    if not client:
        return False

    try:
        client.user.add(
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
        )
        logger.info(f"Zep user created/updated: {user_id}")
        return True
    except Exception as exc:
        exc_str = str(exc)
        if "already exists" in exc_str.lower():
            logger.debug(f"Zep user already exists: {user_id}")
        else:
            logger.warning(f"Failed to create Zep user {user_id}: {exc}")
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
    client = _get_client()
    if not client:
        return False

    # 1) cheap in-process check
    if _already_seen(user_id, category, content):
        logger.debug(f"Dedupe (in-process) skipped Zep add: [{category}] {content[:80]}...")
        _mark_seen(user_id, category, content)
        return True

    # 2) Zep-graph similarity check
    if await _check_zep_duplicate(user_id, content):
        logger.debug(f"Dedupe (Zep hit) skipped Zep add: [{category}] {content[:80]}...")
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
        logger.debug(f"Added semantic memory to Zep: [{category}] {content[:80]}...")
        return True
    except Exception as exc:
        logger.warning(f"Failed to add semantic memory to Zep: {exc}")
        return False


async def add_semantic_memories_batch(
    user_id: str,
    memories: list[dict],
) -> int:
    """Add multiple semantic memories to the user's Zep graph.

    Each memory dict should have: category, content, confidence, expected_lifetime.

    Returns:
        Number of successfully stored memories.
    """
    count = 0
    for mem in memories:
        ok = await add_semantic_memory(
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
    client = _get_client()
    if not client:
        return []

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

        memories = []
        seen = set()
        for edge in (results.edges or []):
            if not edge.fact:
                continue
            if edge.fact in seen:
                continue
            seen.add(edge.fact)

            mem = {
                "fact": edge.fact,
                "name": edge.name or "",
                "score": edge.score,
            }
            # Parse JSON data from attributes if available
            if edge.attributes:
                attrs = edge.attributes
                mem["category"] = attrs.get("category", "")
                mem["content"] = attrs.get("content", edge.fact)

            memories.append(mem)

        # Also include node summaries
        for node in (results.nodes or []):
            if node.name in seen or node.summary in seen:
                continue
            if not node.summary:
                continue
            seen.add(node.summary)
            memories.append({
                "fact": node.summary,
                "name": node.name,
                "score": node.score,
                "category": "entity",
                "content": node.summary,
            })

        # Sort by score descending
        memories.sort(key=lambda m: -(m.get("score") or 0))

        logger.info(
            f"Zep graph search: query={query!r} user={user_id} "
            f"results={len(memories)}"
        )
        return memories[:limit]

    except Exception as exc:
        logger.warning(f"Zep graph search failed: {exc}")
        return []
