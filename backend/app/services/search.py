from __future__ import annotations

import math

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models import Asset, Note, NoteEmbedding, Segment, SegmentContent, SegmentEmbedding
from app.schemas import SearchResultItem
from app.services.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    parse_embedding,
    tokenize_text,
    vectorize_text,
)


class SearchService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def search(
        self,
        user_id,
        query: str,
        types: list[str],
        limit: int,
        semantic: bool,
    ) -> list[SearchResultItem]:
        normalized = query.strip()
        if not normalized:
            return []

        like_pattern = f"%{normalized}%"
        query_vector = vectorize_text(normalized)
        results: list[SearchResultItem] = []

        include_notes = "notes" in types
        include_segments = "segments" in types

        if include_notes:
            note_query = (
                self.db.query(Note, NoteEmbedding.embedding)
                .outerjoin(
                    NoteEmbedding,
                    and_(
                        NoteEmbedding.note_id == Note.id,
                        NoteEmbedding.is_current.is_(True),
                        NoteEmbedding.model == DEFAULT_EMBEDDING_MODEL,
                    ),
                )
                .filter(Note.user_id == user_id, Note.is_deleted.is_(False))
                .order_by(Note.updated_at.desc())
            )
            if not semantic:
                note_query = note_query.filter(Note.content.ilike(like_pattern))

            notes = note_query.limit(limit * (3 if semantic else 1)).all()

            for note, embedding in notes:
                note_text = note.content or ""
                item_vector = self._resolve_item_vector(note_text, embedding)
                results.append(
                    SearchResultItem(
                        type="note",
                        id=note.id,
                        score=self._score_result(note_text, normalized, semantic, query_vector, item_vector),
                        snippet=self._snippet(note_text, normalized),
                        note_title=None,
                    )
                )

        if include_segments:
            segment_query = (
                self.db.query(
                    Segment,
                    Asset.title.label("asset_title"),
                    func.min(SegmentContent.content).label("content"),
                    SegmentEmbedding.embedding,
                )
                .join(SegmentContent, SegmentContent.segment_id == Segment.id)
                .join(Asset, and_(Asset.id == Segment.asset_id, Asset.deleted_at.is_(None)))
                .outerjoin(
                    SegmentEmbedding,
                    and_(
                        SegmentEmbedding.segment_id == Segment.id,
                        SegmentEmbedding.is_current.is_(True),
                        SegmentEmbedding.model == DEFAULT_EMBEDDING_MODEL,
                    ),
                )
                .filter(Segment.user_id == user_id, Segment.deleted_at.is_(None))
                .group_by(Segment.id, Segment.asset_id, Segment.start_ms, Segment.end_ms, Asset.title, SegmentEmbedding.embedding)
                .order_by(Segment.start_ms.asc())
            )
            if not semantic:
                segment_query = segment_query.filter(SegmentContent.content.ilike(like_pattern))

            segments = segment_query.limit(limit * (3 if semantic else 1)).all()

            for segment, asset_title, content, embedding in segments:
                content_text = content or ""
                item_vector = self._resolve_item_vector(content_text, embedding)
                results.append(
                    SearchResultItem(
                        type="segment",
                        id=segment.id,
                        score=self._score_result(content_text, normalized, semantic, query_vector, item_vector),
                        snippet=self._snippet(content_text, normalized),
                        asset_id=segment.asset_id,
                        asset_title=asset_title,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                    )
                )

        results.sort(key=lambda item: (item.score, item.type == "note"), reverse=True)
        return results[:limit]

    def _snippet(self, text: str, query: str, max_len: int = 180) -> str:
        content = text or ""
        if not content:
            return ""

        idx = content.lower().find(query.lower())
        if idx == -1:
            return content[:max_len]

        start = max(0, idx - 60)
        end = min(len(content), idx + max_len - 60)
        return content[start:end]

    def _score_result(
        self,
        text: str,
        query: str,
        semantic: bool,
        query_vector: list[float],
        item_vector: list[float],
    ) -> float:
        keyword_score = self._keyword_score(text, query)
        if not semantic:
            return keyword_score

        similarity = self._cosine_similarity(query_vector, item_vector)
        blended = (keyword_score * 0.35) + (similarity * 0.65)
        return round(min(1.0, blended), 4)

    def _keyword_score(self, text: str, query: str) -> float:
        content = (text or "").lower()
        q = (query or "").lower().strip()
        if not content or not q:
            return 0.0

        tokens = [token for token in tokenize_text(q) if len(token) > 1]
        if not tokens:
            return 0.0

        exact = 1.0 if q in content else 0.0
        overlap = len(set(tokens) & set(tokenize_text(content))) / max(1, len(set(tokens)))
        return round(min(1.0, (exact * 0.6) + (overlap * 0.4)), 4)

    def _resolve_item_vector(self, text: str, embedding: str | None) -> list[float]:
        parsed = parse_embedding(embedding)
        if parsed:
            return parsed
        return vectorize_text(text)

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0

        size = min(len(left), len(right))
        if size == 0:
            return 0.0

        dot = sum(left[index] * right[index] for index in range(size))
        left_norm = math.sqrt(sum(value * value for value in left[:size]))
        right_norm = math.sqrt(sum(value * value for value in right[:size]))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return round(dot / (left_norm * right_norm), 4)

