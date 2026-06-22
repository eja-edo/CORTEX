import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class KnowledgeChunk:
    """
    Layer 6: Knowledge (Chunked Content)
    Documents, notes, uploaded files — chunked + embedded.
    """

    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200

    def chunk_and_store(self, user_id: str, source_type: str, source_id: str,
                        text: str, metadata: Dict[str, Any], db):
        chunks = self._chunk_text(text, self.CHUNK_SIZE, self.CHUNK_OVERLAP)

        for i, chunk_text in enumerate(chunks):
            db.execute("""
                INSERT INTO knowledge_chunks
                    (user_id, source_type, source_id, chunk_index,
                     chunk_text, metadata)
                VALUES
                    (:uid, :stype, :sid, :idx,
                     :text, CAST(:meta AS jsonb))
            """, {
                "uid": user_id,
                "stype": source_type,
                "sid": source_id,
                "idx": i,
                "text": chunk_text,
                "meta": json.dumps(metadata),
            })

        logger.info("Stored %s knowledge chunks for %s/%s", len(chunks), source_type, source_id)

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end >= len(text):
                chunks.append(text[start:])
                break
            split_pos = text.rfind(" ", start, end)
            if split_pos > start:
                end = split_pos
            chunks.append(text[start:end])
            start = end - overlap if end - overlap > start else end

        return chunks

    def retrieve_by_source(self, source_type: str, source_id: str, db) -> List[Dict[str, Any]]:
        rows = db.execute("""
            SELECT * FROM knowledge_chunks
            WHERE source_type = :stype AND source_id = :sid AND is_active = TRUE
            ORDER BY chunk_index ASC
        """, {"stype": source_type, "sid": source_id}).fetchall()

        return [dict(r) for r in rows]

    def get_full_text(self, source_type: str, source_id: str, db) -> str:
        chunks = self.retrieve_by_source(source_type, source_id, db)
        return "".join(c["chunk_text"] for c in chunks)
