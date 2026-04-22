from __future__ import annotations

import math

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models import Asset, Note, NoteEmbedding
from app.schemas import SearchResultItem
from app.services.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    parse_embedding,
    tokenize_text,
    vectorize_text,
)



