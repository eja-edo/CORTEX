from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import NoteEmbedding, SegmentEmbedding


DEFAULT_EMBEDDING_MODEL = "search-hybrid-v1"
VECTOR_DIMENSIONS = 32
MIN_EMBED_CHARS = 40
MIN_EMBED_TOKENS = 6


def tokenize_text(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def should_embed_text(text: str) -> bool:
    normalized = (text or "").strip()
    if len(normalized) < MIN_EMBED_CHARS:
        return False
    return len(tokenize_text(normalized)) >= MIN_EMBED_TOKENS


    
        return [0.0] * VECTOR_DIMENSIONS

    counts = Counter(tokens)
    vector = [0.0] * VECTOR_DIMENSIONS
    for token, count in counts.items():
        index = _stable_hash(token) % VECTOR_DIMENSIONS
        vector[index] += float(count)

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def parse_embedding(embedding: object | None) -> list[float]:
    if embedding is None:
        return []

    if isinstance(embedding, (list, tuple)):
        values: list[float] = []
        for item in embedding:
            try:
                values.append(float(item))
            except (TypeError, ValueError):
                return []
        return values

    if isinstance(embedding, str):
        candidate = embedding.strip()
        if not candidate:
            return []

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, list):
            return parse_embedding(parsed)

        parts = [part.strip() for part in candidate.replace("|", ",").split(",") if part.strip()]
        if not parts:
            return []

        values: list[float] = []
        for part in parts:
            try:
                values.append(float(part))
            except ValueError:
                return []
        return values

    return []


def serialize_embedding(vector: list[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


async def upsert_note_embedding_async(
    session: AsyncSession,
    *,
    note_id: UUID,
    content: str,
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> None:
    if not should_embed_text(content):
        await session.execute(
            delete(NoteEmbedding).where(NoteEmbedding.note_id == note_id, NoteEmbedding.model == model)
        )
        return

    payload = serialize_embedding(vectorize_text(content))
    stmt = pg_insert(NoteEmbedding).values(
        note_id=note_id,
        model=model,
        embedding=payload,
        is_current=True,
        created_at=datetime.utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["note_id", "model"],
        set_={
            "embedding": payload,
            "is_current": True,
            "created_at": func.now(),
        },
    )
    await session.execute(stmt)


def upsert_segment_embedding_sync(
    session: Session,
    *,
    segment_id: UUID,
    content: str,
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> None:
    if not should_embed_text(content):
        session.execute(
            delete(SegmentEmbedding).where(SegmentEmbedding.segment_id == segment_id, SegmentEmbedding.model == model)
        )
        return

    payload = serialize_embedding(vectorize_text(content))
    stmt = pg_insert(SegmentEmbedding).values(
        segment_id=segment_id,
        model=model,
        embedding=payload,
        is_current=True,
        created_at=datetime.utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["segment_id", "model"],
        set_={
            "embedding": payload,
            "is_current": True,
            "created_at": func.now(),
        },
    )
    session.execute(stmt)


def build_segment_embedding_content(contents: list[str]) -> str:
    normalized = [item.strip() for item in contents if item and item.strip()]
    return "\n".join(normalized)


def _stable_hash(token: str) -> int:
    result = 0
    for char in token:
        result = (result * 33 + ord(char)) & 0xFFFFFFFF
    return result
