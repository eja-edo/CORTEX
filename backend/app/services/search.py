from sqlalchemy import and_, cast, func, or_, String
from sqlalchemy.orm import Session

from app.models import Asset, Note, Segment, SegmentContent
from app.schemas import SearchResultItem


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
        like_pattern = f"%{normalized}%"
        results: list[SearchResultItem] = []

        include_notes = "notes" in types
        include_segments = "segments" in types

        if include_notes:
            notes = self.db.query(Note).filter(
                Note.user_id == user_id,
                Note.is_deleted.is_(False),
                Note.content.ilike(like_pattern),
            ).order_by(Note.updated_at.desc()).limit(limit).all()

            for note in notes:
                results.append(
                    SearchResultItem(
                        type="note",
                        id=note.id,
                        score=self._score_text(note.content, normalized, semantic),
                        snippet=self._snippet(note.content, normalized),
                        note_title=None,
                    )
                )

        if include_segments:
            segments = self.db.query(
                Segment.id,
                Segment.asset_id,
                Segment.start_ms,
                Segment.end_ms,
                Asset.title.label("asset_title"),
                func.min(SegmentContent.content).label("content"),
            ).join(
                SegmentContent,
                SegmentContent.segment_id == Segment.id,
            ).join(
                Asset,
                and_(Asset.id == Segment.asset_id, Asset.deleted_at.is_(None)),
            ).filter(
                Segment.user_id == user_id,
                Segment.deleted_at.is_(None),
                SegmentContent.content.ilike(like_pattern),
            ).group_by(
                Segment.id,
                Segment.asset_id,
                Segment.start_ms,
                Segment.end_ms,
                Asset.title,
            ).order_by(
                Segment.start_ms.asc(),
            ).limit(limit).all()

            for segment in segments:
                content = segment.content or ""
                results.append(
                    SearchResultItem(
                        type="segment",
                        id=segment.id,
                        score=self._score_text(content, normalized, semantic),
                        snippet=self._snippet(content, normalized),
                        asset_id=segment.asset_id,
                        asset_title=segment.asset_title,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                    )
                )

        results.sort(key=lambda item: item.score, reverse=True)
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

    def _score_text(self, text: str, query: str, semantic: bool) -> float:
        content = (text or "").lower()
        q = query.lower()
        if not content or not q:
            return 0.0

        exact = content.count(q)
        base = min(1.0, 0.4 + (exact * 0.2))
        if semantic:
            # Temporary uplift until embedding similarity query is wired.
            base = min(1.0, base + 0.05)
        return round(base, 4)
