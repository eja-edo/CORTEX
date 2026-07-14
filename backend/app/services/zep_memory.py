"""
Zep integration for long-term semantic memory storage.

Handles:
- User creation in Zep
- Adding semantic memories to user graphs
- Searching semantic memories from user graphs
"""

import json
import logging
from uuid import UUID
from zep_cloud.client import Zep
from app.config import settings

logger = logging.getLogger(__name__)

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

    Args:
        user_id: The user ID in Zep.
        category: "project" | "preference" | "constraint" | "environment" | "decision_pattern"
        content: The memory text.
        confidence: 0.0-1.0
        expected_lifetime: "short" | "medium" | "long" | "permanent"

    Returns:
        True if the memory was stored successfully.
    """
    client = _get_client()
    if not client:
        return False

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
